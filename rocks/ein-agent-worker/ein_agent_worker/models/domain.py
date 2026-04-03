"""Domain types and skill metadata shared across agents and models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class DomainType(StrEnum):
    """Domain types for specialist agents."""

    COMPUTE = 'compute'
    STORAGE = 'storage'
    NETWORK = 'network'
    OBSERVABILITY = 'observability'


class SkillInfo(BaseModel):
    """Lightweight skill metadata for instruction injection.

    Used to inject available skills into agent instructions at creation time,
    giving agents immediate awareness of available domain knowledge.
    """

    name: str = Field(..., description='Skill name identifier')
    description: str = Field(default='', description='Human-readable skill description')
    domain: str = Field(
        ..., description='Domain this skill belongs to (e.g., compute, storage, general)'
    )
    auto_inject: bool = Field(
        default=False, description='If True, full content is embedded in the system prompt'
    )
    content: str = Field(
        default='', description='Full skill content (populated only when auto_inject=True)'
    )
