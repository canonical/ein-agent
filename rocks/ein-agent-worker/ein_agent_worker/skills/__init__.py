"""Skills system - read-only knowledge resources for agents.

Skills are directories containing domain knowledge (runbooks, troubleshooting
guides, reference docs) that agents can discover and read on demand via
progressive disclosure: list available skills first, then read full content
only when needed.

All actual infrastructure commands go through UTCP tools. Skills only provide
the knowledge context for agents to use those tools effectively.
"""

from ein_agent_worker.skills.config import SkillManifest, SkillsConfig
from ein_agent_worker.skills.registry import (
    clear,
    get_skill,
    list_skills,
    register_skill,
)
from ein_agent_worker.skills.temporal_skills import (
    create_skill_workflow_tools,
    get_skill_activities,
)

__all__ = [
    'SkillManifest',
    'SkillsConfig',
    'clear',
    'create_skill_workflow_tools',
    'get_skill',
    'get_skill_activities',
    'list_skills',
    'register_skill',
]
