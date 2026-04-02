"""Data models for Human-in-the-Loop workflow."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# Default model used when EIN_AGENT_MODEL environment variable is not set
DEFAULT_MODEL = 'gemini/gemini-2.5-flash'


# =============================================================================
# Approval Models
# =============================================================================


class ApprovalPolicy(StrEnum):
    """Policy for tool call approval.

    - NEVER: Never require approval (trust all operations)
    - ALWAYS: Always require approval for every operation
    - READ_ONLY: Auto-approve read operations, require approval for writes
    """

    NEVER = 'never'
    ALWAYS = 'always'
    READ_ONLY = 'read_only'

    @classmethod
    def default(cls) -> 'ApprovalPolicy':
        """Default policy auto-approves reads, requires approval for writes."""
        return cls.READ_ONLY


class WorkflowInterruption(BaseModel):
    """Represents a workflow interruption requiring human intervention.

    This unified model handles all types of interruptions following the OpenAI SDK pattern.
    """

    id: str = Field(description='Unique identifier for this interruption')
    type: Literal['tool_approval', 'agent_selection', 'human_input', 'user_selection'] = Field(
        description='Type of interruption'
    )
    agent_name: str = Field(description='Name of the agent requesting the interruption')
    tool_name: str | None = Field(default=None, description='Tool name for tool_approval type')
    arguments: dict[str, Any] | None = Field(
        default=None, description='Tool arguments for tool_approval type'
    )
    question: str | None = Field(default=None, description='Question for human_input type')
    options: list[str] | None = Field(
        default=None, description='Selection options for user_selection type'
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description='Additional context (risk_level, operation_description, etc.)',
    )
    timestamp: datetime | None = Field(
        default=None, description='When the interruption was created'
    )


class ApprovalDecision(BaseModel):
    """Represents a user's approval decision."""

    interruption_id: str = Field(description='ID of the interruption being decided')
    approved: bool = Field(description='Whether the operation was approved')
    always: bool = Field(
        default=False, description='If True, cache this decision for future similar operations'
    )
    reason: str | None = Field(default=None, description='Optional reason for the decision')


class SelectionResponse(BaseModel):
    """Represents a user's selection response."""

    interruption_id: str = Field(description='ID of the interruption being responded to')
    selected_option: str | None = Field(
        default=None, description='The selected option, or None if cancelled'
    )


class WorkflowStatus(StrEnum):
    """Workflow lifecycle states."""

    PENDING = 'pending'  # Created, waiting for first message
    RUNNING = 'running'  # Agent processing / waiting for user
    COMPLETED = 'completed'  # Investigation finished with report
    ENDED = 'ended'  # User terminated early
    TIMED_OUT = 'timed_out'  # Global workflow timeout reached (Temporal execution_timeout)


class ChatMessage(BaseModel):
    """A message in the conversation."""

    role: str = Field(description="Message role: 'user' or 'assistant'")
    content: str = Field(description='Message content')
    timestamp: datetime | None = Field(
        default=None, description='Message timestamp (set by workflow)'
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSelectionRequest(BaseModel):
    """Request for user to select an agent from available options."""

    from_agent: str = Field(description='Agent requesting the handoff')
    suggested_agent: str = Field(description="LLM's suggested agent to hand off to")
    reason: str = Field(description='Reason for the handoff')
    available_agents: list[str] = Field(description='List of all available agents to choose from')


class WorkflowState(BaseModel):
    """Current workflow state - returned to clients via queries."""

    status: WorkflowStatus = WorkflowStatus.PENDING
    messages: list[ChatMessage] = Field(default_factory=list)
    findings: dict[str, Any] = Field(default_factory=dict)

    # Unified interruptions (OpenAI SDK pattern)
    interruptions: list[WorkflowInterruption] = Field(
        default_factory=list, description='Pending interruptions requiring human intervention'
    )

    # Sticky approvals: maps tool names to approval status
    # When user chooses "approve always" or "reject always", we store the decision here
    # Format: "tool_name" -> True (approved) or False (rejected)
    sticky_approvals: dict[str, bool] = Field(
        default_factory=dict, description='Sticky approval decisions (always approve/reject)'
    )

    last_fetched_alerts: list[dict] = Field(default_factory=list)


class HITLConfig(BaseModel):
    """Configuration for human-in-the-loop workflow."""

    model: str = Field(
        default=DEFAULT_MODEL,
        description='LLM model to use',
    )
    alertmanager_url: str | None = Field(
        default=None,
        description='Alertmanager URL for fetching alerts',
    )
    max_turns: int = Field(
        default=50,
        ge=1,
        description='Maximum conversation turns before stopping',
    )
    agent_max_turns: int = Field(
        default=15,
        ge=1,
        description='Maximum agent turns per run before forcing a checkpoint back to planner',
    )


class WorkflowEventType(StrEnum):
    """Types of events that can be sent to the workflow."""

    MESSAGE = 'message'
    CONFIRMATION = 'confirmation'
    SELECTION = 'selection'
    SELECTION_RESPONSE = 'selection_response'
    STOP = 'stop'


class WorkflowEvent(BaseModel):
    """An event sent to the workflow."""

    type: WorkflowEventType
    payload: Any = None
    timestamp: datetime | None = Field(
        default=None, description='Event timestamp (set by workflow)'
    )
