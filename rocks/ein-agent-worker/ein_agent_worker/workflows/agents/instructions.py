"""Instruction templates and section builders for non-specialist agents.

Contains the Orchestrator Agent and Investigation Agent instruction templates.
These are formatted at agent creation time with environment-aware information
(available services, skills, specialist capabilities).

Specialist templates live in specialists.py (tightly coupled to domain logic).
"""

from ein_agent_worker.models.domain import DomainType, SkillInfo
from ein_agent_worker.workflows.agents.prompt_loader import load_template
from ein_agent_worker.workflows.agents.specialists import (
    DOMAIN_NAMES,
    DOMAIN_UTCP_SERVICE_TYPES,
)

# =============================================================================
# Section Builders
# =============================================================================


def _build_environment_section(
    utcp_services: list[str],
    available_skills: list[SkillInfo],
    instance_names: dict[str, list[str]] | None = None,
) -> str:
    """Build environment context for the planning agent."""
    lines = ['## Environment']
    if utcp_services:
        lines.append(f'Configured infrastructure services: {", ".join(sorted(utcp_services))}')
        # Show instance details for multi-instance service types
        if instance_names:
            for svc_type in sorted(utcp_services):
                instances = instance_names.get(svc_type, [])
                if len(instances) > 1:
                    inst_list = ', '.join(f'`{i}`' for i in sorted(instances))
                    lines.append(f'  - `{svc_type}` instances: {inst_list}')
    else:
        lines.append('No infrastructure services are currently configured.')
    if available_skills:
        lines.append(f'Available knowledge resources: {len(available_skills)} skill(s)')
        lines.extend(
            f'  - `{skill.name}` ({skill.domain}): {skill.description}'
            for skill in available_skills
        )
    else:
        lines.append('No knowledge resources (skills) are available.')

    # Show specialist capabilities
    lines.append('\n## Specialist Capabilities')
    for domain in DomainType:
        domain_services = DOMAIN_UTCP_SERVICE_TYPES.get(domain, set())
        active = [s for s in sorted(domain_services) if s in utcp_services]
        status = f'tools for {", ".join(active)}' if active else 'no UTCP services configured'
        lines.append(f'- **{DOMAIN_NAMES[domain]}**: {status}')

    return '\n'.join(lines)


def _build_specialists_status_section(
    utcp_services: list[str],
    instance_names: dict[str, list[str]] | None = None,
) -> str:
    """Build specialist status section for the investigation agent."""
    descriptions = {
        DomainType.COMPUTE: 'For compute/container orchestration queries (pods, nodes)',
        DomainType.STORAGE: 'For storage queries (OSDs, pools, PVCs)',
        DomainType.NETWORK: 'For networking queries (services, DNS, ingress)',
        DomainType.OBSERVABILITY: 'For monitoring, metrics, and logging queries',
    }
    lines = []
    for domain in DomainType:
        domain_services = DOMAIN_UTCP_SERVICE_TYPES.get(domain, set())
        active = [s for s in sorted(domain_services) if s in utcp_services]
        name = DOMAIN_NAMES[domain]
        desc = descriptions.get(domain, '')
        if active:
            details = f'{desc} (tools: {", ".join(active)})'
            # Show instances if multi-instance
            for svc_type in active:
                instances = (instance_names or {}).get(svc_type, [])
                if len(instances) > 1:
                    inst_list = ', '.join(f'`{i}`' for i in sorted(instances))
                    details += f'\n    - `{svc_type}` instances: {inst_list}'
            lines.append(f'  - **{name}**: {details}')
        else:
            lines.append(f'  - **{name}**: {desc} (no UTCP services configured)')
    return '\n'.join(lines)


# =============================================================================
# Public API - convenience functions that encapsulate template substitution
# =============================================================================


def format_orchestrator_instructions(
    utcp_services: list[str],
    available_skills: list[SkillInfo],
    instance_names: dict[str, list[str]] | None = None,
) -> str:
    """Format orchestrator agent instructions with environment context."""
    return load_template('orchestrator_agent').substitute(
        environment_section=_build_environment_section(
            utcp_services, available_skills, instance_names=instance_names
        ),
    )


def format_investigation_instructions(
    utcp_services: list[str],
    instance_names: dict[str, list[str]] | None = None,
) -> str:
    """Format investigation agent instructions with specialist status."""
    return load_template('investigation_agent').substitute(
        specialists_status_section=_build_specialists_status_section(
            utcp_services, instance_names=instance_names
        ),
    )
