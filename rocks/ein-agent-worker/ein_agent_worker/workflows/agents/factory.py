"""Agent factory - creates the multi-agent investigation graph.

Constructs the full agent hierarchy:
  OrchestratorAgent (entry point, all UTCP tools)
    -> InvestigationAgent (coordinator)
       -> ComputeSpecialist
       -> StorageSpecialist
       -> NetworkSpecialist
       -> ObservabilitySpecialist
"""

import logging
from collections.abc import Callable
from datetime import datetime

from agents import Agent, handoff

from ein_agent_worker.models.domain import DomainType, SkillInfo
from ein_agent_worker.models.investigation import SharedContext, SpecialistHandoffReport
from ein_agent_worker.utcp import registry as utcp_registry
from ein_agent_worker.workflows.agents.instructions import (
    format_investigation_instructions,
    format_orchestrator_instructions,
)
from ein_agent_worker.workflows.agents.shared_context_tools import (
    create_shared_context_tools,
)
from ein_agent_worker.workflows.agents.specialists import (
    DOMAIN_NAMES,
    DOMAIN_UTCP_SERVICE_TYPES,
    new_specialist_agent,
)

logger = logging.getLogger(__name__)


def get_available_skills_metadata(skill_registry) -> list[SkillInfo]:
    """Get metadata for all registered skills.

    Reads from the in-memory skill registry (populated at worker startup),
    so no filesystem I/O is needed. For auto-inject skills, includes full
    content so it can be embedded in agent system prompts.

    Args:
        skill_registry: The skill registry module (ein_agent_worker.skills.registry)

    Returns:
        List of SkillInfo with name, description, domain, and optionally content
    """
    result = []
    auto_injected = []
    for name in skill_registry.list_skills():
        manifest = skill_registry.get_skill(name)
        if manifest:
            result.append(
                SkillInfo(
                    name=manifest.name,
                    description=manifest.description,
                    domain=manifest.domain,
                    auto_inject=manifest.auto_inject,
                    content=manifest.content if manifest.auto_inject else '',
                )
            )
            if manifest.auto_inject:
                auto_injected.append(manifest.name)
    if auto_injected:
        logger.info(
            'Auto-injecting %d skill(s) into system prompt: %s',
            len(auto_injected),
            auto_injected,
        )
    return result


def create_investigation_agent_graph(
    model: str,
    shared_context: SharedContext,
    utcp_tools: dict[str, list],
    skill_tools: list,
    ask_user_tool: Callable,
    ask_selection_tool: Callable,
    fetch_alerts_tool: Callable,
    available_skills: list[SkillInfo],
) -> Agent:
    """Create the full multi-agent investigation graph.

    Args:
        model: LLM model identifier
        shared_context: Shared context instance for cross-agent findings
        utcp_tools: Dict mapping service_name -> list of UTCP tools
        skill_tools: List of skill discovery/reading tools
        ask_user_tool: Pre-created ask_user tool (workflow-bound)
        ask_selection_tool: Pre-created ask_selection tool (workflow-bound)
        fetch_alerts_tool: Pre-created fetch_alerts tool (workflow-bound)
        available_skills: Metadata for all registered skills

    Returns:
        The OrchestratorAgent (entry point of the agent graph)
    """
    available_services = list(utcp_tools.keys())
    logger.info(
        'Creating agent graph: %d UTCP services, %d skills',
        len(available_services),
        len(available_skills),
    )

    # --- Global instance name mapping (for all agents) ---
    all_instance_names: dict[str, list[str]] = {}
    for svc_type in available_services:
        instances = utcp_registry.list_services_by_type(svc_type)
        if instances:
            all_instance_names[svc_type] = instances

    # --- Specialists (one per domain) ---
    specialists: dict[DomainType, Agent] = {}
    for domain in DomainType:
        # Shared context tools for this specialist
        sc_update, sc_get, sc_print, sc_group, sc_compact = create_shared_context_tools(
            shared_context, agent_name=DOMAIN_NAMES[domain]
        )

        # UTCP tools for this domain's services
        domain_utcp_tools = _get_domain_utcp_tools(domain, utcp_tools)

        # Active UTCP service types for this domain (for instruction formatting)
        active_services = [
            s for s in sorted(DOMAIN_UTCP_SERVICE_TYPES.get(domain, set())) if s in utcp_tools
        ]

        # Filter global instance_names to this domain's service types
        domain_instance_names = {
            svc_type: all_instance_names[svc_type]
            for svc_type in active_services
            if svc_type in all_instance_names
        }

        specialists[domain] = new_specialist_agent(
            domain=domain,
            model=model,
            tools=[
                sc_update,
                sc_get,
                sc_print,
                sc_group,
                sc_compact,
                *domain_utcp_tools,
                *skill_tools,
            ],
            available_services=active_services,
            available_skills=available_skills,
            instance_names=domain_instance_names,
        )

    # --- Investigation Agent (coordinator) ---
    inv_update, inv_get, inv_print, inv_group, inv_compact = create_shared_context_tools(
        shared_context, agent_name='InvestigationAgent'
    )
    investigation_agent = Agent(
        name='InvestigationAgent',
        model=model,
        instructions=format_investigation_instructions(
            available_services, instance_names=all_instance_names
        ),
        handoff_description='Execute an approved investigation plan by coordinating '
        'domain specialists. Delegates all infrastructure queries to specialists.',
        tools=[
            ask_user_tool,
            ask_selection_tool,
            fetch_alerts_tool,
            inv_print,
            inv_get,
            inv_update,
            inv_group,
            inv_compact,
        ],
        handoffs=list(specialists.values()),
    )

    # --- Orchestrator Agent (entry point, all tools) ---
    all_utcp_tools = [t for tools in utcp_tools.values() for t in tools]
    orch_update, orch_get, orch_print, orch_group, orch_compact = create_shared_context_tools(
        shared_context, agent_name='OrchestratorAgent'
    )
    orchestrator_agent = Agent(
        name='OrchestratorAgent',
        model=model,
        instructions=format_orchestrator_instructions(
            available_services, available_skills, instance_names=all_instance_names
        ),
        tools=[
            ask_user_tool,
            ask_selection_tool,
            fetch_alerts_tool,
            *all_utcp_tools,
            *skill_tools,
            orch_update,
            orch_get,
            orch_print,
            orch_group,
            orch_compact,
        ],
        handoffs=[investigation_agent],
    )

    # Specialists use structured handoffs: the SDK forces structured findings
    # output and the on_handoff callback auto-persists to SharedContext.
    for domain, spec in specialists.items():
        spec.handoffs = [
            handoff(
                agent=investigation_agent,
                input_type=SpecialistHandoffReport,
                on_handoff=_create_specialist_handoff_callback(
                    shared_context=shared_context,
                    agent_name=DOMAIN_NAMES[domain],
                ),
                tool_description_override=(
                    'Hand off back to InvestigationAgent with your structured findings '
                    'report. You MUST provide all findings from your investigation.'
                ),
            )
        ]

    investigation_agent.handoffs = [
        *specialists.values(),
        orchestrator_agent,
    ]

    logger.info(
        'Agent graph created: OrchestratorAgent -> [InvestigationAgent -> %d specs]',
        len(specialists),
    )
    return orchestrator_agent


def _create_specialist_handoff_callback(
    shared_context: SharedContext,
    agent_name: str,
    get_timestamp: Callable[[], datetime] | None = None,
):
    """Create an on_handoff callback that auto-persists specialist findings.

    When a specialist hands off to InvestigationAgent, the SDK validates the
    structured report and this callback saves all findings to SharedContext.
    This eliminates the risk of findings being lost when the LLM forgets to
    call update_shared_context.

    Args:
        shared_context: The shared context to persist findings to
        agent_name: Name of the specialist agent
        get_timestamp: Optional callable to get current timestamp
            (use workflow.now in Temporal workflows)
    """

    async def on_specialist_handoff(ctx, report: SpecialistHandoffReport):  # noqa: RUF029
        timestamp = get_timestamp() if get_timestamp else None
        for finding in report.findings:
            # add_finding handles semantic dedup: same key + higher confidence
            # updates in place, same key + equal/lower confidence is skipped.
            shared_context.add_finding(
                key=finding.key,
                value=finding.value,
                confidence=finding.confidence,
                agent_name=agent_name,
                metadata={
                    'domain': report.domain,
                    'root_cause_identified': report.root_cause_identified,
                    'source': 'structured_handoff',
                },
                timestamp=timestamp,
            )
        logger.info(
            '[Auto-persist] %s handoff: %d findings in report, %d total in context',
            agent_name,
            len(report.findings),
            len(shared_context.findings),
        )

    return on_specialist_handoff


def _get_domain_utcp_tools(domain: DomainType, utcp_tools: dict[str, list]) -> list:
    """Get UTCP tools for a specific domain's service types.

    utcp_tools is keyed by service_type (e.g., 'kubernetes'), so matching
    is a direct key lookup against DOMAIN_UTCP_SERVICE_TYPES.
    """
    tools = []
    for service_type in DOMAIN_UTCP_SERVICE_TYPES.get(domain, set()):
        if service_type in utcp_tools:
            tools.extend(utcp_tools[service_type])
    return tools
