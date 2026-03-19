"""Human-in-the-Loop Investigation Workflow.

A simple conversational workflow where:
- User converses with an investigation agent
- Agent has tools to fetch alerts from Alertmanager
- Agent can investigate infrastructure using UTCP tools
- Agent asks for clarification naturally when needed via ask_user tool
- Agent can hand off to domain specialists for deep technical analysis
"""

from datetime import timedelta
from typing import ClassVar

from agents import Agent, RunConfig, Runner, function_tool
from temporalio import workflow

from ein_agent_worker.models import (
    ApprovalDecision,
    ChatMessage,
    HITLConfig,
    SharedContext,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowInterruption,
    WorkflowState,
    WorkflowStatus,
)

with workflow.unsafe.imports_passed_through():
    from agents.exceptions import MaxTurnsExceeded

    from ein_agent_worker.activities.worker_config import load_worker_model
    from ein_agent_worker.models.gemini_litellm_provider import GeminiCompatibleLitellmProvider
    from ein_agent_worker.utcp import registry as utcp_registry
    from ein_agent_worker.utcp.temporal_utcp import create_utcp_workflow_tools
    from ein_agent_worker.workflows.agents.shared_context_tools import (
        create_shared_context_tools,
    )
    from ein_agent_worker.workflows.agents.specialists import (
        DOMAIN_UTCP_SERVICES,
        DomainType,
        new_specialist_agent,
    )

# =============================================================================
# Planning Agent Prompt
# =============================================================================
PLANNING_AGENT_PROMPT = """\
You are the Planning Agent (The Gatekeeper & Planner).

Your role: Route user requests to the right agent. You have NO infrastructure \
tools — you MUST hand off to other agents for all data retrieval and investigation.

## Your Capabilities
- **Fetch Alerts**: Use `fetch_alerts` to get current firing alerts.
- **Ask User**: Use `ask_user` to present plans and get approval.
- **Shared Context**: Use `get_shared_context` and `print_findings_report` to \
read investigation findings recorded by specialists during investigation.
- **Hand Off to ContextAgent**: Use `transfer_to_contextagent` for simple \
information retrieval queries.
- **Hand Off to InvestigationAgent**: Use `transfer_to_investigationagent` to \
start an approved investigation plan.

## Your Workflow

### MODE 1: QUICK CONTEXT (Simple Queries)
When the user is asking for information (not troubleshooting), just return \
the data they asked for. Do NOT analyze, summarize, or propose investigation \
plans. Present the results and wait for the user to decide what to do next.

For alert queries, use `fetch_alerts` directly and return the results as-is. \
For all other infrastructure queries, hand off to ContextAgent — you have \
NO UTCP tools and cannot query infrastructure yourself.

### MODE 2: INVESTIGATION PLANNING (Complex Troubleshooting)
For any request that involves troubleshooting, root cause analysis, or \
multi-step investigation, you MUST:

1. **Analyze the Request**: Understand what the user wants to investigate.
2. **Create a Plan**: Propose a structured investigation plan with:
   - What systems/domains will be investigated
   - Which specialists will be consulted (Compute, Storage, Network, Observability)
   - What specific checks will be performed
   - The order of investigation steps
3. **Present the Plan**: Use `ask_user` to present the plan and ask for approval.
   Format the plan clearly:
   ```
   Investigation Plan:
   1. [Step 1 - what will be checked and why]
   2. [Step 2 - what will be checked and why]
   3. [Step 3 - what will be checked and why]

   Specialists to involve: [list]
   Estimated scope: [brief description]

   Shall I proceed with this plan? (yes/no, or suggest changes)
   ```
4. **Wait for Approval**:
   - If user approves -> Hand off to InvestigationAgent with the approved plan
   - If user suggests changes -> Revise the plan and ask again
   - If user says no -> Ask what they'd like instead

Examples of troubleshooting requests that REQUIRE a plan:
- "why are my pods crashing?" -> Plan needed
- "investigate the storage alert" -> Plan needed
- "diagnose network connectivity issues" -> Plan needed
- "what's causing high CPU usage?" -> Plan needed
- "troubleshoot this error" -> Plan needed

### MODE 3: CHECKPOINT HANDLING (Mid-Investigation Progress)
When the InvestigationAgent hands back to you with a progress update:

1. **Read Shared Context**: Call `get_shared_context()` to retrieve all findings \
recorded by specialists during the investigation.
2. **Summarize Progress**: Compact the findings so far into a clear summary.
3. **Present to User**: Use `ask_user` to show:
   ```
   Investigation Progress:
   - Completed: [steps done so far]
   - Findings: [key findings from shared context]
   - Remaining: [steps still to do from the original plan]

   Would you like to:
   1. Continue with the remaining steps
   2. Adjust the plan based on findings
   3. Stop here — the current findings are sufficient
   ```
4. **Act on User Decision**:
   - Continue -> Hand off back to InvestigationAgent with remaining steps
   - Adjust -> Create a revised plan and ask for approval
   - Stop -> Call `print_findings_report` to generate and present the full \
findings report to the user

## CRITICAL RULES
- **YOU HAVE NO UTCP TOOLS**: Never try to query infrastructure directly. \
Hand off to ContextAgent for simple queries or InvestigationAgent for investigations.
- **NEVER HAND OFF TO InvestigationAgent WITHOUT USER APPROVAL**: You MUST \
call `ask_user` with a plan FIRST. Wait for the user to say "yes" or "approve" \
before calling `transfer_to_investigationagent`. This is NON-NEGOTIABLE — even \
if the issue seems obvious, even if you already have alert data, you MUST \
present a plan and get explicit approval before handing off.
- **HAND OFF IMMEDIATELY AFTER APPROVAL**: When the user approves a plan, \
immediately call `transfer_to_investigationagent`. Do NOT do anything else.
- **ALWAYS USE ask_user FOR PLANS**: Present investigation plans through `ask_user` \
to get explicit approval before handing off.
- **COMPACT FINDINGS**: When presenting progress updates, summarize and compact \
the findings — don't dump raw tool output.
"""

# =============================================================================
# Context Agent Prompt
# =============================================================================
CONTEXT_AGENT_PROMPT = """\
You are the Context Agent (Quick Information Retrieval).

Your role: Quickly retrieve infrastructure information for the user using UTCP tools. \
You handle simple, direct queries — no troubleshooting, no investigation plans.

## Your Capabilities
You have UTCP tools for all configured infrastructure services. \
For each service, you have:
- `search_{service}_operations` — find available API operations by keyword
- `get_{service}_operation_details` — get parameter schema for an operation
- `call_{service}_operation` — execute an API operation

Use these tools to fetch whatever data the user or Planning Agent requested.

## Your Workflow
1. Receive a query from the Planning Agent.
2. Use the appropriate UTCP tools to fetch the requested data.
3. Return the results back to the Planning Agent via `transfer_to_planningagent`.

## CRITICAL RULES
- **QUICK AND DIRECT**: Fetch the data and return. Do not analyze, troubleshoot, \
or investigate further.
- **ALWAYS RETURN TO PLANNER**: After fetching data, hand off back to \
PlanningAgent (`transfer_to_planningagent`) with the results.
- **NO INVESTIGATION**: If the query requires multi-step analysis, just fetch \
what was asked and return. The PlanningAgent will decide next steps.
"""

# =============================================================================
# Investigation Agent Prompt
# =============================================================================
INVESTIGATION_AGENT_PROMPT = """\
You are the Investigation Agent (The Coordinator).

Your role: Execute approved investigation plans by delegating to domain specialists. \
You receive plans from the Planning Agent and coordinate their execution. \
You do NOT query infrastructure directly — you delegate ALL queries to specialists.

## Your Capabilities
- **Delegate to Domain Specialists**: Hand off to specialists for ALL infrastructure queries:
  - **ComputeSpecialist**: For ALL compute/container orchestration queries \
(pods, nodes, deployments, etc.)
  - **StorageSpecialist**: For ALL storage queries (OSDs, pools, PVCs, etc.)
  - **NetworkSpecialist**: For ALL networking queries (services, DNS, ingress, etc.)
  - **ObservabilitySpecialist**: For ALL monitoring, metrics, and logging queries.
- **Shared Context**: Use `get_shared_context`, `update_shared_context`, \
and `group_findings` to manage investigation findings.
- **Ask User**: Ask for clarification or provide updates using `ask_user`.
- **Print Findings Report**: Use `print_findings_report` to generate a \
formatted summary of all investigation findings.
- **Fetch Alerts**: Use `fetch_alerts` to get current firing alerts.

## Your Workflow
1. **Follow the Approved Plan**: Execute the investigation plan that was approved \
by the user through the Planning Agent. Follow the steps in order.
2. **Delegate to Specialists**: For each step in the plan, hand off to the \
appropriate specialist. You are a coordinator — do not try to query \
infrastructure yourself.
3. **Synthesize & Group**: As findings come back from specialists, use \
`group_findings` to consolidate related findings.
4. **Checkpoint Back to Planner**: After receiving results from one specialist, \
first call `update_shared_context` for each finding, then hand off back to the \
Planning Agent (`transfer_to_planningagent`) with a progress summary. \
Do NOT try to complete the entire investigation in one go. \
The Planning Agent will present progress to the user and decide next steps.

## CRITICAL RULES
- **NEVER QUERY INFRASTRUCTURE DIRECTLY**: You have NO UTCP tools. Always delegate \
to the appropriate specialist.
- **UPDATE SHARED CONTEXT BEFORE EVERY HANDOFF**: Before handing off to ANY agent \
(PlanningAgent or specialists), you MUST call `update_shared_context` to record \
ALL findings discovered so far. This is MANDATORY — findings that are not saved \
to shared context will be LOST. Record each finding with an appropriate key \
(e.g., "pod:namespace/name", "node:name", "service:namespace/name") and confidence level.
- **CHECKPOINT FREQUENTLY**: After receiving results from one specialist, save findings \
to shared context, then hand off back to the Planning Agent. \
Do NOT run the full investigation without checkpointing.
- **FOLLOW THE PLAN**: Stick to the approved investigation plan.
- **HANDOFFS**: Use the standard transfer tools to delegate \
(e.g., `transfer_to_computespecialist`, `transfer_to_observabilityspecialist`).
- **OUTPUTTING REPORTS**: Always output the content of `print_findings_report` to the user.
"""


@workflow.defn
class HumanInTheLoopWorkflow:
    """Simple conversational investigation workflow."""

    # List of available specialist agents for user selection
    AVAILABLE_SPECIALISTS: ClassVar[list[str]] = [
        'ComputeSpecialist',
        'StorageSpecialist',
        'NetworkSpecialist',
        'ObservabilitySpecialist',
    ]

    def __init__(self):
        self._state = WorkflowState()
        self._shared_context = SharedContext()
        self._config = HITLConfig()
        self._run_config: RunConfig | None = None
        self._event_queue: list[WorkflowEvent] = []
        self._should_end = False
        self._utcp_tools: dict[str, list] = {}  # service_name -> tools

    # =========================================================================
    # Signals (user sends messages)
    # =========================================================================

    @workflow.signal
    async def send_message(self, message: str) -> None:
        """User sends a message to the agent."""
        workflow.logger.info(f'Received user message: {message[:100]}...')
        self._state.messages.append(
            ChatMessage(role='user', content=message, timestamp=workflow.now())
        )
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.MESSAGE, payload=message, timestamp=workflow.now()
            )
        )

    @workflow.signal
    async def end_workflow(self) -> None:
        """User wants to end the conversation."""
        workflow.logger.info('End workflow signal received')
        self._should_end = True
        self._event_queue.append(
            WorkflowEvent(type=WorkflowEventType.STOP, timestamp=workflow.now())
        )

    @workflow.signal
    async def provide_confirmation(self, confirmed: bool) -> None:
        """User provides confirmation for a pending action."""
        workflow.logger.info(f'Received confirmation: {confirmed}')
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.CONFIRMATION, payload=confirmed, timestamp=workflow.now()
            )
        )

    @workflow.signal
    async def provide_agent_selection(self, selected_agent: str) -> None:
        """User selects an agent from the available options.

        Args:
            selected_agent: Name of the selected agent, or empty string to cancel.
        """
        workflow.logger.info(f'Received agent selection: {selected_agent}')
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.SELECTION,
                payload=selected_agent if selected_agent else None,
                timestamp=workflow.now(),
            )
        )

    @workflow.signal
    async def provide_approval_decisions(self, decisions: list[dict]) -> None:
        """User provides approval/rejection decisions for pending interruptions.

        Args:
            decisions: List of ApprovalDecision dicts
        """
        workflow.logger.info(f'Received {len(decisions)} approval decision(s)')
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.CONFIRMATION, payload=decisions, timestamp=workflow.now()
            )
        )

    # =========================================================================
    # Queries (read state)
    # =========================================================================

    @workflow.query
    def get_state(self) -> dict:
        """Get current workflow state."""
        return self._state.model_dump(mode='json')

    @workflow.query
    def get_messages(self) -> list[dict]:
        """Get conversation history."""
        return [m.model_dump(mode='json') for m in self._state.messages]

    @workflow.query
    def get_status(self) -> str:
        """Get current workflow status."""
        return self._state.status.value

    # =========================================================================
    # Event Handling
    # =========================================================================

    async def _next_event(self) -> WorkflowEvent:
        """Wait for and return the next event from the queue."""
        await workflow.wait_condition(lambda: len(self._event_queue) > 0)
        return self._event_queue.pop(0)

    async def _wait_for_event_type(self, event_type: WorkflowEventType) -> WorkflowEvent:
        """Wait for a specific event type, skipping others."""
        while True:
            event = await self._next_event()
            if event.type == event_type or event.type == WorkflowEventType.STOP:
                return event
            workflow.logger.info(
                f'Ignoring event type {event.type} while waiting for {event_type}'
            )

    # =========================================================================
    # Main workflow
    # =========================================================================

    @workflow.run
    async def run(
        self,
        initial_message: str | None = None,
        config: HITLConfig | None = None,
    ) -> str:
        """Main conversation loop.

        Args:
            initial_message: Optional first message to start the conversation
            config: Optional configuration for the workflow

        Returns:
            Final report or termination message
        """
        if config:
            self._config = config

        self._state.status = WorkflowStatus.RUNNING
        workflow.logger.info('Human-in-the-loop workflow started')

        # Load worker model configuration from environment
        self._config.model = await workflow.execute_activity(
            load_worker_model,
            start_to_close_timeout=timedelta(seconds=10),
        )
        workflow.logger.info(f'Using model: {self._config.model}')

        # Setup run config
        self._run_config = RunConfig(
            model_provider=GeminiCompatibleLitellmProvider(),
            tracing_disabled=True,
        )

        # Initialize UTCP tools
        self._initialize_utcp_tools()

        # Create the investigation agent
        agent = self._create_investigation_agent()

        # Handle initial message or produce greeting
        if initial_message:
            # Add to messages and push a dummy event to trigger the first turn
            self._state.messages.append(
                ChatMessage(role='user', content=initial_message, timestamp=workflow.now())
            )
            self._event_queue.append(
                WorkflowEvent(
                    type=WorkflowEventType.MESSAGE,
                    payload=initial_message,
                    timestamp=workflow.now(),
                )
            )
        else:
            # No initial message - produce a greeting
            greeting = (
                "Hello! I'm your infrastructure investigation assistant. "
                'I can help you investigate alerts and infrastructure issues.\n\n'
                'You can:\n'
                '- **Quick context**: Ask me to show pods, check storage health, '
                "list alerts — I'll answer directly\n"
                '- **Investigation**: Describe an issue to troubleshoot — '
                "I'll create a plan and ask for your approval before starting\n\n"
                'How can I help today?'
            )
            self._state.messages.append(
                ChatMessage(role='assistant', content=greeting, timestamp=workflow.now())
            )
            workflow.logger.info('Sent initial greeting')

        # Conversation loop
        turn_count = 0
        while not self._should_end and turn_count < self._config.max_turns:
            # Wait for user input (MESSAGE or STOP)
            workflow.logger.info('Waiting for user message...')
            event = await self._wait_for_event_type(WorkflowEventType.MESSAGE)

            if self._should_end or event.type == WorkflowEventType.STOP:
                break

            turn_count += 1
            # Build conversation history for the agent
            conversation = self._build_conversation_input()

            workflow.logger.info(f'Running agent turn {turn_count}')

            try:
                # Run the agent with turn limit to force periodic checkpoints
                result = await Runner.run(
                    agent,
                    input=conversation,
                    max_turns=self._config.agent_max_turns,
                    run_config=self._run_config,
                )

                # Handle interruptions (tool approvals, etc.)
                while result.interruptions:
                    workflow.logger.info(
                        'Agent execution interrupted: %d interruption(s)',
                        len(result.interruptions),
                    )

                    # Convert SDK interruptions to our WorkflowInterruption model
                    self._state.interruptions = [
                        self._convert_sdk_interruption(i, agent.name) for i in result.interruptions
                    ]

                    # Wait for approval decisions from user
                    workflow.logger.info('Waiting for approval decisions...')
                    event = await self._wait_for_event_type(WorkflowEventType.CONFIRMATION)

                    if self._should_end or event.type == WorkflowEventType.STOP:
                        break

                    # Process approval decisions
                    decisions_data = event.payload
                    if not decisions_data:
                        workflow.logger.warning('No decisions provided, rejecting all')
                        decisions_data = []

                    # Parse decisions
                    decisions = [ApprovalDecision(**d) for d in decisions_data]
                    workflow.logger.info(f'Processing {len(decisions)} approval decision(s)')

                    # Apply decisions and update cache
                    state = self._apply_approval_decisions(result, decisions)

                    # Clear interruptions from state
                    self._state.interruptions = []

                    # Resume agent with decisions
                    result = await Runner.run(
                        agent,
                        input=state,
                        max_turns=self._config.agent_max_turns,
                        run_config=self._run_config,
                    )

                if self._should_end:
                    break

                response = result.final_output or 'I encountered an issue processing your request.'

                # Add agent response to history
                self._state.messages.append(
                    ChatMessage(role='assistant', content=response, timestamp=workflow.now())
                )

                workflow.logger.info(f'Agent response: {response[:200]}...')

            except MaxTurnsExceeded as e:
                # Agent hit the turn limit — extract findings from the
                # interrupted run's tool call results and save to shared context
                workflow.logger.warning(
                    'Agent hit max turns (%d), extracting findings from run data',
                    self._config.agent_max_turns,
                )

                # Build a compact summary of tool results from the interrupted run
                run_summary = self._extract_run_items_summary(e)
                workflow.logger.info(
                    'Extracted run summary (%d chars): %s',
                    len(run_summary),
                    run_summary[:500],
                )

                # Try to save findings to shared context via summarizer
                findings_before = len(self._shared_context.findings)
                await self._run_checkpoint_summarizer(run_summary)
                findings_after = len(self._shared_context.findings)
                workflow.logger.info(
                    'Summarizer added %d new findings (total: %d)',
                    findings_after - findings_before,
                    findings_after,
                )

                lines = [
                    f'Investigation paused (reached {self._config.agent_max_turns} turn limit).'
                ]
                if self._shared_context.findings:
                    lines.append('\nFindings so far:')
                    lines.append(self._shared_context.format_summary())

                    # Add suggestions based on high-confidence findings
                    root_causes = self._shared_context.get_high_confidence_root_causes()
                    if root_causes:
                        lines.append('\nSuggested actions:')
                        for i, f in enumerate(root_causes[:5], 1):
                            lines.append(f'{i}. Investigate: **{f.key}** — {f.value}')
                else:
                    # No findings saved — provide a brief status from the run
                    lines.append(
                        '\nNo findings were saved during this round. '
                        'The investigation may need more turns to reach actionable results.'
                    )

                lines.append(
                    '\nWould you like to:\n'
                    '1. **Continue** the investigation\n'
                    '2. **Adjust** the plan based on findings\n'
                    '3. **Stop** here and get the full findings report'
                )

                self._state.messages.append(
                    ChatMessage(
                        role='assistant',
                        content='\n'.join(lines),
                        timestamp=workflow.now(),
                    )
                )

            except Exception as e:
                workflow.logger.error(f'Agent error: {e}')
                error_msg = (
                    f'I encountered an error: {e!s}. Please try again or rephrase your request.'
                )
                self._state.messages.append(
                    ChatMessage(role='assistant', content=error_msg, timestamp=workflow.now())
                )

        # Workflow ended
        if self._should_end:
            self._state.status = WorkflowStatus.ENDED
            return 'Investigation ended by user.'
        else:
            self._state.status = WorkflowStatus.COMPLETED
            return 'Investigation completed (max turns reached).'

    # =========================================================================
    # Agent Creation
    # =========================================================================

    def _initialize_utcp_tools(self) -> None:
        """Initialize UTCP tools from pre-registered clients.

        UTCP clients are initialized at worker startup (where network I/O is allowed)
        and stored in the registry. This method creates the 3 meta-tools
        (search, get_details, call) for each registered service.

        These tools execute UTCP operations as Temporal activities, allowing
        network I/O to happen outside the workflow sandbox.
        """
        services = utcp_registry.list_services()

        if not services:
            workflow.logger.info('No UTCP services registered')
            return

        workflow.logger.info(f'Creating tools for {len(services)} UTCP service(s)')

        for service_name in services:
            # Get service config for approval policy
            service_config = utcp_registry.get_service_config(service_name)

            # Create workflow tools that execute as activities
            # Pass sticky_approvals dict so tools can check
            # for cached decisions. Since dicts are mutable,
            # updates will be visible to approval checkers.
            tools = create_utcp_workflow_tools(
                service_name,
                service_config=service_config,
                sticky_approvals=self._state.sticky_approvals,
            )
            self._utcp_tools[service_name] = tools
            workflow.logger.info(
                f'Created {len(tools)} tools for {service_name}: '
                f'{[getattr(t, "name", str(t)) for t in tools]}'
            )

    def _get_domain_utcp_tools(self, domain: DomainType) -> list:
        """Get UTCP tools for a specific domain.

        Args:
            domain: The domain type

        Returns:
            List of UTCP tools for the domain's services
        """
        tools = []
        services = DOMAIN_UTCP_SERVICES.get(domain, set())
        for service in services:
            if service in self._utcp_tools:
                tools.extend(self._utcp_tools[service])
        return tools

    # =========================================================================
    # Approval Handling
    # =========================================================================

    def _convert_sdk_interruption(self, sdk_interruption, agent_name: str) -> WorkflowInterruption:
        """Convert OpenAI SDK interruption to our WorkflowInterruption model.

        Args:
            sdk_interruption: Interruption from OpenAI SDK
            agent_name: Name of the agent that created the interruption

        Returns:
            WorkflowInterruption instance
        """
        # Generate unique ID for this interruption
        interruption_id = f'{sdk_interruption.tool_name}:{sdk_interruption.call_id}'

        # Parse arguments - might be dict, string, or None
        arguments = sdk_interruption.arguments
        if isinstance(arguments, str):
            import json

            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                workflow.logger.warning(f'Failed to parse arguments as JSON: {arguments}')
                arguments = {'raw': arguments}
        elif arguments is None:
            arguments = {}
        elif not isinstance(arguments, dict):
            # Some other type, wrap it
            arguments = {'value': arguments}

        return WorkflowInterruption(
            id=interruption_id,
            type='tool_approval',
            agent_name=agent_name,
            tool_name=sdk_interruption.tool_name,
            arguments=arguments,
            context={
                'call_id': sdk_interruption.call_id,
                'description': f'Tool call: {sdk_interruption.tool_name}',
            },
            timestamp=workflow.now(),
        )

    def _apply_approval_decisions(self, result, decisions: list[ApprovalDecision]):
        """Apply approval/rejection decisions and update sticky approvals.

        Args:
            result: Agent run result with interruptions
            decisions: List of user approval decisions

        Returns:
            Updated state for resuming agent execution
        """
        # Convert RunResult to RunState to access approve/reject methods
        state = result.to_state()

        # Create a map of interruption_id -> decision
        decision_map = {d.interruption_id: d for d in decisions}

        # Find matching SDK interruptions and approve/reject
        for interruption in result.interruptions:
            interruption_id = f'{interruption.tool_name}:{interruption.call_id}'

            decision = decision_map.get(interruption_id)
            if not decision:
                # No decision provided, reject by default
                workflow.logger.warning(f'No decision for {interruption_id}, rejecting')
                state.reject(interruption)
                continue

            if decision.approved:
                workflow.logger.info(f'Approving: {interruption.tool_name}')
                state.approve(interruption)

                # Store sticky approval if "always approve"
                if decision.always:
                    self._state.sticky_approvals[interruption.tool_name] = True
                    workflow.logger.info(f'Sticky approval stored for {interruption.tool_name}')
            else:
                workflow.logger.info(f'Rejecting: {interruption.tool_name}')
                state.reject(interruption)

                # Store sticky rejection if "always reject"
                if decision.always:
                    self._state.sticky_approvals[interruption.tool_name] = False
                    workflow.logger.info(f'Sticky rejection stored for {interruption.tool_name}')

        return state

    # =========================================================================
    # Checkpoint Summarizer
    # =========================================================================

    def _extract_run_items_summary(self, exc: MaxTurnsExceeded) -> str:
        """Extract a compact summary of tool calls and results from MaxTurnsExceeded.

        The exception's run_data.new_items contains all RunItems from the
        interrupted run, including ToolCallItem and ToolCallOutputItem with
        actual API results. We extract these into a text summary that the
        checkpoint summarizer can parse.

        Args:
            exc: The MaxTurnsExceeded exception with run_data

        Returns:
            Compact text summary of tool calls and their results
        """
        lines = ['## Tool Call Results from Interrupted Run\n']

        run_data = getattr(exc, 'run_data', None)
        if not run_data:
            lines.append('No run data available.')
            return '\n'.join(lines)

        new_items = getattr(run_data, 'new_items', None)
        if not new_items:
            lines.append('No items in run data.')
            return '\n'.join(lines)

        for item in new_items:
            item_type = getattr(item, 'type', '')
            agent_obj = getattr(item, 'agent', None)
            agent_name = getattr(agent_obj, 'name', 'unknown') if agent_obj else 'unknown'

            if item_type == 'tool_call_item':
                raw = getattr(item, 'raw_item', None)
                tool_name = getattr(raw, 'name', None) or str(raw)
                arguments = getattr(raw, 'arguments', '')
                lines.append(f'**[{agent_name}] Tool Call:** {tool_name}')
                # Truncate long arguments
                if arguments and len(str(arguments)) < 500:
                    lines.append(f'  Args: {arguments}')

            elif item_type == 'tool_call_output_item':
                output = getattr(item, 'output', '')
                output_str = str(output)
                # Truncate long outputs but keep enough for the summarizer
                if len(output_str) > 2000:
                    output_str = output_str[:2000] + '... (truncated)'
                lines.append(f'**[{agent_name}] Tool Result:**')
                lines.append(output_str)
                lines.append('')

            elif item_type == 'message_output_item':
                raw = getattr(item, 'raw_item', None)
                content = ''
                if raw and hasattr(raw, 'content'):
                    for part in raw.content:
                        if hasattr(part, 'text'):
                            content += part.text
                if content:
                    lines.append(f'**[{agent_name}] Message:** {content[:1000]}')
                    lines.append('')

        workflow.logger.info('Extracted %d lines from %d run items', len(lines), len(new_items))
        return '\n'.join(lines)

    async def _run_checkpoint_summarizer(self, run_summary: str) -> None:
        """Run a short-lived agent to extract and save findings to shared context.

        Called when MaxTurnsExceeded fires. Receives a compact summary of the
        interrupted run's tool call results (extracted from MaxTurnsExceeded.run_data).

        Args:
            run_summary: Text summary of tool calls and results from the interrupted run
        """
        update_tool, get_tool, _print_tool, _group_tool = create_shared_context_tools(
            self._shared_context, agent_name='CheckpointSummarizer'
        )

        summarizer = Agent(
            name='CheckpointSummarizer',
            model=self._config.model,
            instructions=(
                'You are a summarizer. Your ONLY job is to extract key findings '
                'from the tool call results below and save them to shared context.\n\n'
                'Read the tool results carefully. For each important finding '
                '(pod status, node issue, error, metric, alert, etc.), call '
                '`update_shared_context` with:\n'
                '- key: resource identifier (e.g., "pod:namespace/name", "node:name")\n'
                '- value: concise summary of the finding\n'
                '- confidence: 0.5 for raw observations, 0.8+ for clear issues\n\n'
                'Be selective — save only meaningful findings, not raw data dumps.\n'
                'After saving all findings, output a one-line summary of what you saved.\n'
                'Do NOT query any infrastructure. Just extract from the provided data.'
            ),
            tools=[update_tool, get_tool],
        )

        try:
            await Runner.run(
                summarizer,
                input=run_summary,
                max_turns=5,
                run_config=self._run_config,
            )
            saved = len(self._shared_context.findings)
            workflow.logger.info(
                'Checkpoint summarizer saved %d findings to shared context', saved
            )
        except Exception as e:
            workflow.logger.error(f'Checkpoint summarizer failed: {e}')

    # =========================================================================
    # Agent Creation
    # =========================================================================

    def _create_investigation_agent(self) -> Agent:
        """Create the planning agent (entry point) and investigation agent with specialists."""
        # Create shared context tools for the Investigation Agent
        update_tool, get_tool, print_report_tool, group_tool = create_shared_context_tools(
            self._shared_context, agent_name='InvestigationAgent'
        )

        # Collect ALL UTCP tools for direct queries
        all_utcp_tools = []
        for service_name in self._utcp_tools:
            all_utcp_tools.extend(self._utcp_tools[service_name])
        workflow.logger.info(f'Agents have {len(all_utcp_tools)} UTCP tools')

        # Create tools for ComputeSpecialist (shared context + UTCP tools)
        comp_update, comp_get, comp_print, comp_group = create_shared_context_tools(
            self._shared_context, agent_name='ComputeSpecialist'
        )
        compute_utcp_tools = self._get_domain_utcp_tools(DomainType.COMPUTE)
        compute_spec = new_specialist_agent(
            domain=DomainType.COMPUTE,
            model=self._config.model,
            tools=[comp_update, comp_get, comp_print, comp_group, *compute_utcp_tools],
        )

        # Create tools for StorageSpecialist (shared context + UTCP tools)
        stor_update, stor_get, stor_print, stor_group = create_shared_context_tools(
            self._shared_context, agent_name='StorageSpecialist'
        )
        storage_utcp_tools = self._get_domain_utcp_tools(DomainType.STORAGE)
        storage_spec = new_specialist_agent(
            domain=DomainType.STORAGE,
            model=self._config.model,
            tools=[stor_update, stor_get, stor_print, stor_group, *storage_utcp_tools],
        )

        # Create tools for NetworkSpecialist (shared context + UTCP tools)
        net_update, net_get, net_print, net_group = create_shared_context_tools(
            self._shared_context, agent_name='NetworkSpecialist'
        )
        network_utcp_tools = self._get_domain_utcp_tools(DomainType.NETWORK)
        network_spec = new_specialist_agent(
            domain=DomainType.NETWORK,
            model=self._config.model,
            tools=[net_update, net_get, net_print, net_group, *network_utcp_tools],
        )

        # Create tools for ObservabilitySpecialist (shared context + UTCP tools)
        obs_update, obs_get, obs_print, obs_group = create_shared_context_tools(
            self._shared_context, agent_name='ObservabilitySpecialist'
        )
        observability_utcp_tools = self._get_domain_utcp_tools(DomainType.OBSERVABILITY)
        observability_spec = new_specialist_agent(
            domain=DomainType.OBSERVABILITY,
            model=self._config.model,
            tools=[obs_update, obs_get, obs_print, obs_group, *observability_utcp_tools],
        )

        # Create tools
        ask_user_tool = self._create_ask_user_tool()
        fetch_alerts_tool = self._create_fetch_alerts_tool()

        # Create Investigation Agent (coordinator) — no UTCP tools,
        # delegates all infrastructure queries to specialists
        investigation_agent = Agent(
            name='InvestigationAgent',
            model=self._config.model,
            instructions=INVESTIGATION_AGENT_PROMPT,
            handoff_description='Execute an approved investigation plan by coordinating '
            'domain specialists. Delegates all infrastructure queries to specialists.',
            tools=[
                ask_user_tool,
                fetch_alerts_tool,
                print_report_tool,
                get_tool,
                update_tool,
                group_tool,
            ],
            handoffs=[compute_spec, storage_spec, network_spec, observability_spec],
        )

        # Create Context Agent (quick info retrieval) with ALL UTCP tools
        context_agent = Agent(
            name='ContextAgent',
            model=self._config.model,
            instructions=CONTEXT_AGENT_PROMPT,
            handoff_description='Quickly retrieve infrastructure information using '
            'UTCP tools. For simple queries like listing pods, checking health, etc.',
            tools=[*all_utcp_tools],
        )

        # Create shared context tools for the Planning Agent (read-only access)
        _planner_sc_update, planner_sc_get, planner_sc_print, _planner_sc_group = (
            create_shared_context_tools(self._shared_context, agent_name='PlanningAgent')
        )

        # Create Planning Agent (entry point) — NO UTCP tools,
        # routes to ContextAgent or InvestigationAgent
        # Has shared context tools to read findings during checkpoint handling
        planning_agent = Agent(
            name='PlanningAgent',
            model=self._config.model,
            instructions=PLANNING_AGENT_PROMPT,
            tools=[
                ask_user_tool,
                fetch_alerts_tool,
                planner_sc_get,
                planner_sc_print,
            ],
            handoffs=[context_agent, investigation_agent],
        )

        # Wire back-handoffs
        context_agent.handoffs = [planning_agent]
        compute_spec.handoffs = [investigation_agent]
        storage_spec.handoffs = [investigation_agent]
        network_spec.handoffs = [investigation_agent]
        observability_spec.handoffs = [investigation_agent]
        investigation_agent.handoffs = [
            compute_spec,
            storage_spec,
            network_spec,
            observability_spec,
            planning_agent,
        ]

        return planning_agent

    # =========================================================================
    # Tool Creation
    # =========================================================================

    def _create_ask_user_tool(self):
        """Create the ask_user tool that pauses for user input."""
        workflow_ref = self

        @function_tool
        async def ask_user(question: str) -> str:
            """Ask the user for clarification or additional information.

            Args:
                question: The question to ask the user.
            """
            workflow.logger.info(f'ask_user called: {question}')

            # Set pending question in state for UI
            workflow_ref._state.pending_question = question

            # Wait for user response
            event = await workflow_ref._wait_for_event_type(WorkflowEventType.MESSAGE)

            # Clear pending question
            workflow_ref._state.pending_question = None

            if event.type == WorkflowEventType.STOP:
                return 'User ended the conversation.'

            response = event.payload or ''
            workflow.logger.info(f'User responded to ask_user: {response[:100]}...')
            return response

        return ask_user

    def _create_fetch_alerts_tool(self):
        """Create the fetch_alerts tool."""

        @function_tool
        async def fetch_alerts(
            status: str = 'firing',
            alertname: str | None = None,
        ) -> str:
            """Fetch alerts from Alertmanager."""
            workflow.logger.info(f'fetch_alerts called: status={status}, alertname={alertname}')

            params = {
                'alertmanager_url': self._config.alertmanager_url,
                'status': status,
                'alertname': alertname,
            }

            try:
                alerts = await workflow.execute_activity(
                    'fetch_alerts_activity',
                    params,
                    start_to_close_timeout=timedelta(seconds=60),
                )
                self._state.last_fetched_alerts = alerts
            except Exception as e:
                workflow.logger.error(f'Failed to fetch alerts: {e}')
                return f'Error: Failed to fetch alerts from Alertmanager: {e}'

            if not alerts:
                return f'No {status} alerts found' + (f" for '{alertname}'." if alertname else '.')

            lines = [f'Found {len(alerts)} {status} alerts:']
            for alert in alerts:
                labels = alert.get('labels', {})
                name = labels.get('alertname', 'N/A')
                fingerprint = alert.get('fingerprint', 'N/A')
                summary = alert.get('annotations', {}).get('summary', 'No summary.')
                lines.append(f'- **{name}** (Fingerprint: `{fingerprint}`): {summary}')
                for key, value in labels.items():
                    if key not in ['alertname', 'severity']:
                        lines.append(f'  - {key}: {value}')

            return '\n'.join(lines)

        return fetch_alerts

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_conversation_input(self) -> str:
        """Build the conversation history as input for the agent."""
        if not self._state.messages:
            return "Hello, I'm ready to help investigate infrastructure issues."

        lines = ['## Conversation History\n']
        for msg in self._state.messages[-10:]:
            role = 'User' if msg.role == 'user' else 'Assistant'
            lines.append(f'**{role}:** {msg.content}\n')

        if self._shared_context.findings:
            lines.append('\n## Current Investigation Findings\n')
            lines.append(self._shared_context.format_summary())

        return '\n'.join(lines)
