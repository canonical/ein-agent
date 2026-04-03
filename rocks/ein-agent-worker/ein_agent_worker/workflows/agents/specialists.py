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


# =============================================================================
# Compute Specialist
# =============================================================================
_COMPUTE_SPECIALIST_TEMPLATE = Template("""\
You are the Compute Specialist (Container Orchestration Domain Expert).

Your role: Technical expert for container orchestration and compute resources.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('node:')` or `get_shared_context('pod:')` to see if related \
issues are already known.
- If a node issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH YOUR TOOLS
$available_services_section

TIP: Use `list_*_operations` to browse available tools efficiently. \
Use `search_*_operations` when you know what you're looking for.

$available_skills_section

Use your tools to investigate:
- Pod status, events, logs
- Node conditions (Ready, MemoryPressure, DiskPressure)
- Resource usage (CPU, memory)
- Container issues (image pull, crashes)

### STEP 3: UPDATE SHARED CONTEXT (optional, for interim findings)
You may call `update_shared_context` during investigation to share findings early, \
so they are visible to other specialists even if your run is interrupted:
```
update_shared_context(
  key="node:worker-1",
  value="Node NotReady - kubelet unresponsive",
  confidence=0.9
)
```

### STEP 4: HAND OFF WITH STRUCTURED REPORT
When done, call `transfer_to_investigationagent` with a structured report. \
The handoff requires ALL of the following fields:
- **findings**: List of objects, each with `key` (resource identifier), \
`value` (description), and `confidence` (0.0-1.0)
- **summary**: One-paragraph summary of your investigation
- **domain**: "compute"
- **resources_checked**: List of resource names you checked
- **root_cause_identified**: true/false

Your findings are **automatically saved** when you hand off — this is guaranteed \
by the system. You CANNOT hand off to other specialists — only back to \
InvestigationAgent.

---
## KEY PATTERNS
- OOMKilled -> Memory limit too low or leak
- CrashLoopBackOff -> App error, missing config, dependency failure
- Pending pods -> Insufficient resources, PVC binding issue
- Node NotReady -> Kubelet issue, network partition
- Evicted pods -> Node resource pressure
""")


# =============================================================================
# Storage Specialist
# =============================================================================
_STORAGE_SPECIALIST_TEMPLATE = Template("""\
You are the Storage Specialist (Distributed Storage Domain Expert).

Your role: Technical expert for distributed storage and persistent volumes.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('osd:')` or `get_shared_context('pvc:')` to see if related \
issues are already known.
- If a storage issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH YOUR TOOLS
$available_services_section

TIP: Use `list_*_operations` to browse available tools efficiently. \
Use `search_*_operations` when you know what you're looking for.

$available_skills_section

Use your tools to investigate:
- Storage cluster health
- OSD status (down, out, full, slow)
- PG status (degraded, undersized, stuck)
- PVC/PV binding status
- Pool utilization

### STEP 3: UPDATE SHARED CONTEXT (optional, for interim findings)
You may call `update_shared_context` during investigation to share findings early, \
so they are visible to other specialists even if your run is interrupted:
```
update_shared_context(
  key="osd:osd.5",
  value="OSD down - disk I/O errors on /dev/sdb",
  confidence=0.95
)
```

Key format examples:
- 'osd:osd.5' for specific OSDs
- 'pool:pool-name' for pools
- 'pvc:namespace/pvc-name' for PVCs

### STEP 4: HAND OFF WITH STRUCTURED REPORT
When done, call `transfer_to_investigationagent` with a structured report. \
The handoff requires ALL of the following fields:
- **findings**: List of objects, each with `key` (resource identifier), \
`value` (description), and `confidence` (0.0-1.0)
- **summary**: One-paragraph summary of your investigation
- **domain**: "storage"
- **resources_checked**: List of resource names you checked
- **root_cause_identified**: true/false

Your findings are **automatically saved** when you hand off — this is guaranteed \
by the system. You CANNOT hand off to other specialists — only back to \
InvestigationAgent.

---
## KEY PATTERNS
- OSD down -> Disk failure, network issue, resource exhaustion
- PG degraded -> OSD failure, replication in progress
- Pool full -> Capacity issue, need rebalancing
- PVC Pending -> Storage class issue, pool full, CSI problem
- Slow ops -> I/O bottleneck, network latency
""")


# =============================================================================
# Network Specialist
# =============================================================================
_NETWORK_SPECIALIST_TEMPLATE = Template("""\
You are the Network Specialist (Network Domain Expert).

Your role: Technical expert for network connectivity, DNS, and load balancing.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('service:')` or `get_shared_context('dns:')` to see if \
related issues are already known.
- If a network issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH YOUR TOOLS
$available_services_section

TIP: Use `list_*_operations` to browse available tools efficiently. \
Use `search_*_operations` when you know what you're looking for.

$available_skills_section

Use your tools to investigate:
- Service endpoints and port mappings
- DNS health and resolution
- Ingress controller status and routing
- NetworkPolicies that might block traffic
- CNI plugin health

### STEP 3: UPDATE SHARED CONTEXT (optional, for interim findings)
You may call `update_shared_context` during investigation to share findings early, \
so they are visible to other specialists even if your run is interrupted:
```
update_shared_context(
  key="dns:coredns",
  value="CoreDNS pods not ready - DNS resolution failing",
  confidence=0.9
)
```

Key format examples:
- 'service:namespace/svc-name' for services
- 'ingress:namespace/ingress-name' for ingress
- 'dns:coredns' for DNS issues

### STEP 4: HAND OFF WITH STRUCTURED REPORT
When done, call `transfer_to_investigationagent` with a structured report. \
The handoff requires ALL of the following fields:
- **findings**: List of objects, each with `key` (resource identifier), \
`value` (description), and `confidence` (0.0-1.0)
- **summary**: One-paragraph summary of your investigation
- **domain**: "network"
- **resources_checked**: List of resource names you checked
- **root_cause_identified**: true/false

Your findings are **automatically saved** when you hand off — this is guaranteed \
by the system. You CANNOT hand off to other specialists — only back to \
InvestigationAgent.

---
## KEY PATTERNS
- Service no endpoints -> No ready pods, selector mismatch
- DNS failure -> CoreDNS down, network policy blocking
- Connection refused -> Pod not ready, wrong port, policy
- Connection timeout -> Network partition, firewall
- Ingress 502/503 -> Backend unhealthy
""")


# =============================================================================
# Observability Specialist
# =============================================================================
_OBSERVABILITY_SPECIALIST_TEMPLATE = Template("""\
You are the Observability Specialist (Monitoring & Logging Domain Expert).

Your role: Technical expert for monitoring, metrics, logs, and alerting. You query \
dashboards, metrics, and logs to provide deep observability into infrastructure \
and application health.

---
## MANDATORY WORKFLOW

### STEP 1: CHECK SHARED CONTEXT FIRST
Call `get_shared_context('metric:')` or `get_shared_context('log:')` to see if related \
issues are already known.
- If a metric or log issue is already recorded, focus on confirming impact
- If no relevant findings, proceed with full investigation

### STEP 2: INVESTIGATE WITH YOUR TOOLS
$available_services_section

TIP: Use `list_*_operations` to browse available tools efficiently. \
Use `search_*_operations` when you know what you're looking for.

$available_skills_section

Use your tools to investigate:
- Dashboards (list, search, get details)
- Alerts and alerting rules
- Instant and range metric queries
- Target health and scrape status
- Log queries for application and system logs
- Log volume and rate patterns
- Correlated log events across services

### STEP 3: UPDATE SHARED CONTEXT (optional, for interim findings)
You may call `update_shared_context` during investigation to share findings early, \
so they are visible to other specialists even if your run is interrupted:
```
update_shared_context(
  key="metric:cpu_usage",
  value="CPU usage sustained above 90% on worker-1 for 30m",
  confidence=0.9
)
```

Key format examples:
- 'metric:metric_name' for metric findings
- 'log:service/pattern' for log findings
- 'dashboard:uid' for dashboard findings
- 'alert:alert_name' for alerting rule findings

### STEP 4: HAND OFF WITH STRUCTURED REPORT
When done, call `transfer_to_investigationagent` with a structured report. \
The handoff requires ALL of the following fields:
- **findings**: List of objects, each with `key` (resource identifier), \
`value` (description), and `confidence` (0.0-1.0)
- **summary**: One-paragraph summary of your investigation
- **domain**: "observability"
- **resources_checked**: List of resource names you checked
- **root_cause_identified**: true/false

Your findings are **automatically saved** when you hand off — this is guaranteed \
by the system. You CANNOT hand off to other specialists — only back to \
InvestigationAgent.

---
## KEY PATTERNS
- High CPU/memory -> Check node metrics, correlate with pod resource usage
- Error rate spike -> Query logs for errors, check error rate metrics
- Alert firing -> Inspect alerting rules, check thresholds
- Missing metrics -> Check target health and scrape config
- Log gaps -> Check log ingestion rate and label cardinality
""")


# =============================================================================
# Template Mapping
# =============================================================================
_DOMAIN_TEMPLATES: dict[DomainType, Template] = {
    DomainType.COMPUTE: _COMPUTE_SPECIALIST_TEMPLATE,
    DomainType.STORAGE: _STORAGE_SPECIALIST_TEMPLATE,
    DomainType.NETWORK: _NETWORK_SPECIALIST_TEMPLATE,
    DomainType.OBSERVABILITY: _OBSERVABILITY_SPECIALIST_TEMPLATE,
}


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
