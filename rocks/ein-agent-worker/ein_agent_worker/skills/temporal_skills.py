"""Temporal skill integration - read-only skill tools as Temporal activities.

This module provides skill discovery and reading within Temporal workflows
by running each operation as a separate activity. This allows filesystem I/O
to happen outside the workflow sandbox.

Pattern follows the UTCP integration in ein_agent_worker.utcp.temporal_utcp.
"""

import dataclasses
import json
import logging
from collections.abc import Callable, Sequence
from datetime import timedelta

from agents import function_tool
from temporalio import activity, workflow
from temporalio.workflow import ActivityConfig

from ein_agent_worker.skills import registry as skill_registry

logger = logging.getLogger(__name__)


# =============================================================================
# Activity Arguments
# =============================================================================


@dataclasses.dataclass
class _ListSkillsArguments:
    """Arguments for listing available skills."""

    pass


@dataclasses.dataclass
class _ReadSkillArguments:
    """Arguments for reading a skill's full content."""

    skill_name: str


# =============================================================================
# Activity Definitions
# =============================================================================


def get_skill_activities() -> Sequence[Callable]:
    """Get skill activity functions to register with the worker.

    Returns:
        Sequence of activity functions
    """

    @activity.defn(name='skill-list-skills')
    async def list_skills(args: _ListSkillsArguments) -> str:  # noqa: RUF029
        """List all available skills with their names, descriptions, and domains."""
        skill_names = skill_registry.list_skills()

        result = []
        for name in skill_names:
            manifest = skill_registry.get_skill(name)
            if manifest:
                result.append({
                    'name': manifest.name,
                    'description': manifest.description,
                    'domain': manifest.domain,
                })

        return json.dumps(
            {
                'total': len(result),
                'skills': result,
            },
            indent=2,
        )

    @activity.defn(name='skill-read-skill')
    async def read_skill(args: _ReadSkillArguments) -> str:  # noqa: RUF029
        """Read the full content of a skill."""
        manifest = skill_registry.get_skill(args.skill_name)
        if not manifest:
            return json.dumps({'error': f"Skill '{args.skill_name}' not found"})

        return json.dumps(
            {
                'name': manifest.name,
                'description': manifest.description,
                'domain': manifest.domain,
                'content': manifest.content,
            },
            indent=2,
        )

    return (list_skills, read_skill)


# =============================================================================
# Workflow Tool Wrappers
# =============================================================================


def create_skill_workflow_tools(
    config: ActivityConfig | None = None,
) -> list[Callable]:
    """Create skill tools for use in Temporal workflows.

    These tools read skill metadata and content as activities, allowing
    filesystem I/O to happen outside the workflow sandbox.

    Args:
        config: Optional activity configuration

    Returns:
        List of function tools for the agent
    """
    activity_config = config or ActivityConfig(start_to_close_timeout=timedelta(seconds=10))

    @function_tool(name_override='list_skills')
    async def list_skills() -> str:
        """List available knowledge resources (skills).

        Skills are domain-specific guides, runbooks, and troubleshooting
        documentation. Use this to discover what knowledge is available
        before reading a specific skill.

        Returns:
            JSON list of available skills with name, description, and domain.
        """
        return await workflow.execute_activity(
            'skill-list-skills',
            _ListSkillsArguments(),
            result_type=str,
            **activity_config,
        )

    @function_tool(name_override='read_skill')
    async def read_skill(skill_name: str) -> str:
        """Read the full content of a knowledge resource (skill).

        Use this after listing skills to read the full guide, runbook,
        or troubleshooting documentation for a specific skill.

        Args:
            skill_name: The exact name of the skill to read
                (e.g., "juju-troubleshooting")

        Returns:
            The full skill content including description and documentation.
        """
        return await workflow.execute_activity(
            'skill-read-skill',
            _ReadSkillArguments(skill_name),
            result_type=str,
            **activity_config,
        )

    return [list_skills, read_skill]
