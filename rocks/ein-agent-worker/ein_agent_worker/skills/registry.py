"""Skill registry - global storage for parsed skill manifests.

Skill manifests are loaded at worker startup (where filesystem I/O is allowed)
and stored here for workflow activities to access.
"""

import logging

from ein_agent_worker.skills.config import SkillManifest

logger = logging.getLogger(__name__)

# Global registry of parsed skill manifests
_skills: dict[str, SkillManifest] = {}


def register_skill(name: str, manifest: SkillManifest) -> None:
    """Register a parsed skill manifest.

    Args:
        name: Skill name (e.g., 'juju-troubleshooting')
        manifest: The parsed skill manifest with content
    """
    _skills[name] = manifest
    logger.info("Registered skill '%s' (domain=%s)", name, manifest.domain)


def get_skill(name: str) -> SkillManifest | None:
    """Get a registered skill manifest.

    Args:
        name: Skill name

    Returns:
        The skill manifest or None if not registered
    """
    return _skills.get(name)


def list_skills() -> list[str]:
    """List all registered skill names.

    Returns:
        List of registered skill names
    """
    return list(_skills.keys())


def clear() -> None:
    """Clear all registered skills."""
    _skills.clear()
    logger.info('Cleared skill registry')
