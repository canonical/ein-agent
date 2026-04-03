"""Domain Specialist agents - Technical Experts for specific infrastructure domains.

Architecture:
- Domain experts are specialized for specific infrastructure domains
- Each domain expert receives UTCP tools relevant to their domain
- Example: StorageSpecialist receives ceph tools, kubernetes tools (for PVCs)
- Instructions are dynamically formatted at agent creation time with available
  services and skills, so agents have immediate situational awareness
"""

from collections.abc import Callable

from agents import Agent

from ein_agent_worker.models.domain import DomainType, SkillInfo
from ein_agent_worker.workflows.agents.prompt_loader import load_template

# =============================================================================
# Domain to UTCP Service Types Mapping
# =============================================================================
# Which UTCP service types are relevant for each domain.
# Tools are keyed by service type (not instance name), so multiple instances
# of the same type (e.g., kubernetes-prod, kubernetes-staging) are all included
# when matching by type.
DOMAIN_UTCP_SERVICE_TYPES: dict[DomainType, set[str]] = {
    DomainType.COMPUTE: {'kubernetes'},
    DomainType.STORAGE: {'ceph', 'kubernetes'},  # kubernetes for PVC access
    DomainType.NETWORK: {'kubernetes'},
    DomainType.OBSERVABILITY: {'grafana', 'prometheus', 'loki'},
}

DOMAIN_NAMES: dict[DomainType, str] = {
    DomainType.COMPUTE: 'ComputeSpecialist',
    DomainType.STORAGE: 'StorageSpecialist',
    DomainType.NETWORK: 'NetworkSpecialist',
    DomainType.OBSERVABILITY: 'ObservabilitySpecialist',
}

# Maps DomainType to the prompt template filename (without extension).
_DOMAIN_TEMPLATE_NAMES: dict[DomainType, str] = {
    DomainType.COMPUTE: 'compute_specialist',
    DomainType.STORAGE: 'storage_specialist',
    DomainType.NETWORK: 'network_specialist',
    DomainType.OBSERVABILITY: 'observability_specialist',
}


# =============================================================================
# Instruction Section Builders (public API - used by instructions.py too)
# =============================================================================


def build_services_section(
    available_services: list[str],
    instance_names: dict[str, list[str]] | None = None,
) -> str:
    """Build the UTCP services section for agent instructions.

    Args:
        available_services: List of service type names (e.g., ['kubernetes', 'grafana'])
        instance_names: Optional dict mapping service_type -> list of instance names.
            When provided (multi-instance), shows per-instance call tools.
            When None, call tools use the service type name directly.
    """
    if not available_services:
        return (
            'NOTE: No UTCP services are currently configured for your domain. '
            'You can only use shared context tools and skills.'
        )
    service_list = ', '.join(f'`{s}`' for s in sorted(available_services))
    tool_lines = []
    for s in sorted(available_services):
        # Read tools are always named after the service type
        tool_lines.append(f'- `search_{s}_operations` - Search for API operations by keyword')
        tool_lines.append(f'- `get_{s}_operation_details` - Get parameter schema for an operation')
        tool_lines.append(
            f'- `list_{s}_operations` - List available operations (with tag filtering)'
        )
        # Call tools: per-instance when multi-instance, otherwise by type
        instances = (instance_names or {}).get(s, [s])
        for inst in sorted(instances):
            call_name = inst.replace('-', '_')
            if len(instances) > 1:
                tool_lines.append(
                    f'- `call_{call_name}_operation` - Execute an API operation on `{inst}`'
                )
            else:
                tool_lines.append(f'- `call_{call_name}_operation` - Execute an API operation')
    tools_block = '\n'.join(tool_lines)
    return (
        f'You have UTCP tools for the following services: {service_list}.\n'
        f'Your available tools:\n{tools_block}'
    )


def build_skills_section(
    available_skills: list[SkillInfo] | None,
    domain: str,
) -> str:
    """Build the skills section for agent instructions.

    Args:
        available_skills: Skill metadata for all registered skills
        domain: Domain to highlight (skills matching this domain shown first).
                Pass empty string to show all skills without domain grouping.
    """
    if not available_skills:
        return 'No knowledge resources (skills) are currently available.'

    lines = ['You have access to the following knowledge resources (skills):']

    if domain:
        # Group by domain relevance for specialist agents
        domain_skills = [(s.name, s.description) for s in available_skills if s.domain == domain]
        other_skills = [(s.name, s.description) for s in available_skills if s.domain != domain]
        if domain_skills:
            lines.append('\n**Your domain skills** (use these first):')
            for name, desc in domain_skills:
                lines.append(f'- `{name}`: {desc}')
        if other_skills:
            lines.append('\n**Other available skills:**')
            for name, desc in other_skills:
                lines.append(f'- `{name}`: {desc}')
    else:
        # Show all skills flat (for agents that span all domains)
        lines.extend(
            f'- `{skill.name}` ({skill.domain}): {skill.description}' for skill in available_skills
        )

    lines.append(
        '\nUse `read_skill(skill_name)` to load the full content of any skill. '
        'No need to call `list_skills` first -- the available skills are listed above.'
    )
    return '\n'.join(lines)


def new_specialist_agent(
    domain: DomainType,
    model: str,
    tools: list[Callable] | None = None,
    available_services: list[str] | None = None,
    available_skills: list[SkillInfo] | None = None,
    instance_names: dict[str, list[str]] | None = None,
) -> Agent:
    """Create a new domain specialist agent with dynamic instructions.

    Instructions are formatted at creation time with the available UTCP services
    and skills, giving the agent immediate situational awareness.

    Args:
        domain: The domain type (COMPUTE, STORAGE, NETWORK, OBSERVABILITY)
        model: LLM model to use
        tools: Optional list of tools (e.g., shared context tools, UTCP tools)
        available_services: UTCP service type names available for this domain
        available_skills: Skill metadata for all registered skills
        instance_names: Optional mapping of service_type -> list of instance names.
            Used to show per-instance call tools in instructions.

    Returns:
        Configured specialist Agent
    """
    name = DOMAIN_NAMES[domain]
    template_name = _DOMAIN_TEMPLATE_NAMES[domain]

    services_section = build_services_section(
        available_services or [], instance_names=instance_names
    )
    skills_section = build_skills_section(available_skills, domain.value)

    instructions = load_template(template_name).substitute(
        available_services_section=services_section,
        available_skills_section=skills_section,
    )

    return Agent(
        name=name,
        instructions=instructions,
        model=model,
        tools=tools or [],
    )
