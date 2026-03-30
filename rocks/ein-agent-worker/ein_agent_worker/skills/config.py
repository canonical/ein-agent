"""Skill configuration - manifest parsing and environment variable loading."""

import dataclasses
import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SkillManifest:
    """Parsed skill manifest with content."""

    name: str
    description: str
    domain: str  # Maps to DomainType: compute, storage, network, observability
    content: str  # Full markdown content from content.md


@dataclasses.dataclass
class SkillsConfig:
    """Configuration for the skills system."""

    skills: list[SkillManifest] = dataclasses.field(default_factory=list)

    @classmethod
    def from_env(cls) -> 'SkillsConfig':
        """Load skills configuration by scanning the skills directory.

        Environment variables:
            SKILLS_DIR: Base directory containing skill subdirectories
                        (default: 'skills/' relative to worker package)
            SKILLS_ENABLED: Comma-separated list of skill names to enable,
                            or '*' for all (default: '*')

        Returns:
            SkillsConfig with parsed skill manifests
        """
        default_dir = str(Path(__file__).parent.parent.parent / 'skills')
        skills_dir = Path(os.getenv('SKILLS_DIR', default_dir))
        enabled_filter = os.getenv('SKILLS_ENABLED', '*').strip()

        if not skills_dir.is_dir():
            logger.info('Skills directory not found: %s', skills_dir)
            return cls()

        # Parse enabled list
        if enabled_filter == '*':
            enabled_set = None  # All enabled
        else:
            enabled_set = {s.strip() for s in enabled_filter.split(',') if s.strip()}

        skills = []
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue

            manifest_path = entry / 'skill.yaml'
            if not manifest_path.exists():
                logger.debug('No skill.yaml in %s, skipping', entry.name)
                continue

            manifest = _load_skill(entry, manifest_path)
            if manifest is None:
                continue

            # Check enabled filter
            if enabled_set is not None and manifest.name not in enabled_set:
                logger.info('Skill %s is disabled by SKILLS_ENABLED', manifest.name)
                continue

            skills.append(manifest)
            logger.info('Loaded skill: %s (domain=%s)', manifest.name, manifest.domain)

        return cls(skills=skills)


def _load_skill(skill_dir: Path, manifest_path: Path) -> SkillManifest | None:
    """Parse a single skill directory.

    Args:
        skill_dir: Path to the skill directory
        manifest_path: Path to the skill.yaml file

    Returns:
        SkillManifest or None if parsing fails
    """
    try:
        with open(manifest_path) as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            logger.error('Invalid skill.yaml in %s: not a mapping', skill_dir.name)
            return None

        name = data.get('name', '')
        description = data.get('description', '')
        domain = data.get('domain', '')

        if not name:
            logger.error('Skill in %s missing required field: name', skill_dir.name)
            return None

        if not domain:
            logger.error('Skill %s missing required field: domain', name)
            return None

        # Read content.md
        content_path = skill_dir / 'content.md'
        if content_path.exists():
            content = content_path.read_text()
        else:
            logger.warning('Skill %s has no content.md', name)
            content = ''

        return SkillManifest(
            name=name,
            description=description,
            domain=domain,
            content=content,
        )

    except yaml.YAMLError as e:
        logger.error('Failed to parse skill.yaml in %s: %s', skill_dir.name, e)
        return None
    except Exception as e:
        logger.error('Failed to load skill from %s: %s', skill_dir.name, e)
        return None
