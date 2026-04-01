"""Agent factory - creates the multi-agent investigation graph.

Constructs the full agent hierarchy:
  PlanningAgent (entry point)
    -> ContextAgent (quick queries, all UTCP tools)
    -> InvestigationAgent (coordinator)
       -> ComputeSpecialist
       -> StorageSpecialist
       -> NetworkSpecialist
       -> ObservabilitySpecialist
"""

import logging
from collections.abc import Callable

from agents import Agent

from ein_agent_worker.models.domain import DomainType, SkillInfo
from ein_agent_worker.models.investigation import SharedContext
from ein_agent_worker.utcp import registry as utcp_registry
from ein_agent_worker.workflows.agents.instructions import (
    format_context_instructions,
    format_investigation_instructions,
    format_planning_instructions,
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
    """Get lightweight metadata for all registered skills.

    Reads from the in-memory skill registry (populated at worker startup),
    so no filesystem I/O is needed. Converts string domain values to
    DomainType enums via Pydantic validation.

    Args:
        skill_registry: The skill registry module (ein_agent_worker.skills.registry)

    Returns:
        List of SkillInfo with name, description, and typed domain
    """
    result = []
    for name in skill_registry.list_skills():
        manifest = skill_registry.get_skill(name)
        if manifest:
            result.append(
                SkillInfo(
                    name=manifest.name,
                    description=manifest.description,
                    domain=manifest.domain,
                )
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
        The PlanningAgent (entry point of the agent graph)
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
        sc_update, sc_get, sc_print, sc_group = create_shared_context_tools(
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
                *domain_utcp_tools,
                *skill_tools,
            ],
            available_services=active_services,
            available_skills=available_skills,
            instance_names=domain_instance_names,
        )

    # --- Investigation Agent (coordinator) ---
    inv_update, inv_get, inv_print, inv_group = create_shared_context_tools(
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
        ],
        handoffs=list(specialists.values()),
    )

    # --- Context Agent (quick info retrieval) ---
    all_utcp_tools = [t for tools in utcp_tools.values() for t in tools]
    context_agent = Agent(
        name='ContextAgent',
        model=model,
        instructions=format_context_instructions(
            available_services, available_skills, instance_names=all_instance_names
        ),
        handoff_description='Quickly retrieve infrastructure information using '
        'UTCP tools. For simple queries like listing pods, checking health, etc.',
        tools=[*all_utcp_tools, *skill_tools],
    )

    # --- Planning Agent (entry point) ---
    _planner_update, planner_get, planner_print, _planner_group = create_shared_context_tools(
        shared_context, agent_name='PlanningAgent'
    )
    planning_agent = Agent(
        name='PlanningAgent',
        model=model,
        instructions=format_planning_instructions(
            available_services, available_skills, instance_names=all_instance_names
        ),
        tools=[
            ask_user_tool,
            ask_selection_tool,
            fetch_alerts_tool,
            planner_get,
            planner_print,
        ],
        handoffs=[context_agent, investigation_agent],
    )

    # --- Wire back-handoffs ---
    context_agent.handoffs = [planning_agent]
    for spec in specialists.values():
        spec.handoffs = [investigation_agent]
    investigation_agent.handoffs = [
        *specialists.values(),
        planning_agent,
    ]

    logger.info(
        'Agent graph created: PlanningAgent -> [ContextAgent, InvestigationAgent -> %d specs]',
        len(specialists),
    )
    return planning_agent


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
