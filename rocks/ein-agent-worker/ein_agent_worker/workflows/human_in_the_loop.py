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

from agents import Agent, RunConfig, Runner
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
    from ein_agent_worker.skills import registry as skill_registry
    from ein_agent_worker.skills.temporal_skills import create_skill_workflow_tools
    from ein_agent_worker.utcp import registry as utcp_registry
    from ein_agent_worker.utcp.config import UTCPServiceConfig  # noqa: TC001
    from ein_agent_worker.utcp.temporal_utcp import create_grouped_utcp_workflow_tools
    from ein_agent_worker.workflows.agents import (
        create_ask_selection_tool,
        create_ask_user_tool,
        create_fetch_alerts_tool,
        create_investigation_agent_graph,
        get_available_skills_metadata,
    )
    from ein_agent_worker.workflows.agents.shared_context_tools import (
        create_shared_context_tools,
    )


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
        self._skill_tools: list = []  # skill discovery/reading tools

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
    async def provide_selection_response(self, response: dict) -> None:
        """User provides a selection response for a user_selection interruption.

        Args:
            response: SelectionResponse dict with interruption_id and selected_option
        """
        selected = response.get('selected_option')
        workflow.logger.info(f'Received selection response: {selected}')
        self._event_queue.append(
            WorkflowEvent(
                type=WorkflowEventType.SELECTION_RESPONSE,
                payload=selected,
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

        # Initialize UTCP tools and skill tools
        self._initialize_utcp_tools()
        self._initialize_skill_tools()

        # Create the agent graph using the factory
        ask_user_tool = create_ask_user_tool(
            set_pending_question=lambda q: setattr(self._state, 'pending_question', q),
            wait_for_message=lambda: self._wait_for_event_type(WorkflowEventType.MESSAGE),
        )
        ask_selection_tool = create_ask_selection_tool(
            add_interruption=lambda i: self._state.interruptions.append(i),
            clear_interruptions=lambda: setattr(self._state, 'interruptions', []),
            wait_for_selection_response=lambda: self._wait_for_event_type(
                WorkflowEventType.SELECTION_RESPONSE
            ),
        )
        fetch_alerts_tool = create_fetch_alerts_tool(
            get_alertmanager_url=lambda: self._config.alertmanager_url,
            store_alerts=lambda alerts: setattr(self._state, 'last_fetched_alerts', alerts),
        )
        available_skills = get_available_skills_metadata(skill_registry)

        agent = create_investigation_agent_graph(
            model=self._config.model,
            shared_context=self._shared_context,
            utcp_tools=self._utcp_tools,
            skill_tools=self._skill_tools,
            ask_user_tool=ask_user_tool,
            ask_selection_tool=ask_selection_tool,
            fetch_alerts_tool=fetch_alerts_tool,
            available_skills=available_skills,
        )

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
    # Tool Initialization
    # =========================================================================

    def _initialize_utcp_tools(self) -> None:
        """Initialize UTCP tools from pre-registered clients.

        UTCP clients are initialized at worker startup (where network I/O is allowed)
        and stored in the registry. This method creates grouped tools per service type:
        - Shared read tools (search/list/get_details) per type
        - Per-instance call tools for each instance

        Tools are keyed by service_type in self._utcp_tools so that domain routing
        works by type (e.g., COMPUTE -> 'kubernetes' -> all kubernetes tools).
        """
        services = utcp_registry.list_services()

        if not services:
            workflow.logger.info('No UTCP services registered')
            return

        workflow.logger.info(f'Creating tools for {len(services)} UTCP service(s)')

        # Group instances by service type
        type_groups: dict[str, dict[str, UTCPServiceConfig | None]] = {}
        for service_name in services:
            service_config = utcp_registry.get_service_config(service_name)
            svc_type = service_config.resolved_type if service_config else service_name
            if svc_type not in type_groups:
                type_groups[svc_type] = {}
            type_groups[svc_type][service_name] = service_config

        # Create grouped tools per service type
        for svc_type, instances in type_groups.items():
            tools = create_grouped_utcp_workflow_tools(
                service_type=svc_type,
                instances=instances,
                sticky_approvals=self._state.sticky_approvals,
            )
            self._utcp_tools[svc_type] = tools
            instance_names = list(instances.keys())
            workflow.logger.info(
                f'Created {len(tools)} tools for type {svc_type} '
                f'(instances: {instance_names}): '
                f'{[getattr(t, "name", str(t)) for t in tools]}'
            )

    def _initialize_skill_tools(self) -> None:
        """Initialize skill tools from pre-registered skill manifests.

        Skills are loaded at worker startup and stored in the registry.
        This method creates 2 tools (list_skills, read_skill) for agents
        to discover and read domain knowledge on demand.
        """
        skill_names = skill_registry.list_skills()

        if not skill_names:
            workflow.logger.info('No skills registered')
            return

        workflow.logger.info(f'Creating tools for {len(skill_names)} skill(s)')
        self._skill_tools = create_skill_workflow_tools()
        workflow.logger.info(
            f'Created {len(self._skill_tools)} skill tools: '
            f'{[getattr(t, "name", str(t)) for t in self._skill_tools]}'
        )

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
