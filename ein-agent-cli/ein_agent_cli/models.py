"""Pydantic models for CLI configuration and workflow parameters."""

import os

from pydantic import BaseModel, Field, field_validator


class TemporalConfig(BaseModel):
    """Temporal service configuration."""

    host: str = Field(
        default_factory=lambda: os.getenv('TEMPORAL_HOST', 'localhost:7233'),
        description='Temporal server host:port',
    )
    namespace: str = Field(
        default_factory=lambda: os.getenv('TEMPORAL_NAMESPACE', 'default'),
        description='Temporal namespace',
    )
    queue: str = Field(
        default_factory=lambda: os.getenv('TEMPORAL_QUEUE', 'ein-agent-queue'),
        description='Temporal task queue name',
    )

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate host:port format."""
        if ':' not in v:
            raise ValueError("Host must be in format 'host:port'")
        return v


class HITLWorkflowConfig(BaseModel):
    """Configuration for human-in-the-loop investigation workflow."""

    temporal: TemporalConfig = Field(
        default_factory=TemporalConfig, description='Temporal configuration'
    )
    workflow_id: str | None = Field(default=None, description='Custom workflow ID')
    alertmanager_url: str | None = Field(
        default=None, description='Alertmanager URL for fetching alerts'
    )
    max_turns: int = Field(default=50, ge=1, description='Maximum agent turns')
    workflow_timeout: int = Field(
        default=3600,
        ge=60,
        description='Global workflow execution timeout in seconds (default: 1 hour). '
        'Temporal will terminate the workflow when this timeout is reached.',
    )

    @classmethod
    def from_cli_args(
        cls,
        temporal_host: str | None,
        temporal_namespace: str | None,
        temporal_queue: str | None,
        workflow_id: str | None,
        max_turns: int,
        workflow_timeout: int = 3600,
    ) -> 'HITLWorkflowConfig':
        """Create config from CLI arguments."""
        temporal_config = TemporalConfig()
        if temporal_host is not None:
            temporal_config.host = temporal_host
        if temporal_namespace is not None:
            temporal_config.namespace = temporal_namespace
        if temporal_queue is not None:
            temporal_config.queue = temporal_queue

        return cls(
            temporal=temporal_config,
            workflow_id=workflow_id,
            max_turns=max_turns,
            workflow_timeout=workflow_timeout,
        )
