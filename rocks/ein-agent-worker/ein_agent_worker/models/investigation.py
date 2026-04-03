"""Data models for investigation using Pydantic."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class SharedFinding(BaseModel):
    """A single finding recorded in the shared context.

    Attributes:
        id: Stable finding identifier (auto-assigned by SharedContext)
        key: Resource identifier (e.g., 'host:compute-01', 'service:api-gateway')
        value: The observed status or identified issue
        confidence: Certainty level (0.0 - 1.0) of this finding
        agent_name: Name of the agent that recorded this finding
        timestamp: When this finding was recorded (optional, set by caller)
        metadata: Additional context about the finding
    """

    id: int = Field(..., description='Stable finding identifier (auto-assigned)')
    key: str = Field(..., description="Resource identifier (e.g., 'host:compute-01')")
    value: str = Field(..., description='The observed status or identified issue')
    confidence: float = Field(..., ge=0.0, le=1.0, description='Certainty level (0.0 - 1.0)')
    agent_name: str = Field(..., description='Name of the agent that recorded this')
    timestamp: datetime | None = Field(default=None, description='When recorded (set by workflow)')
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestigationGroup(BaseModel):
    """A grouping of related findings representing a specific incident or root cause."""

    name: str = Field(..., description="Name of the group (e.g., 'Ceph Cluster Failure')")
    finding_ids: list[int] = Field(..., description='Stable IDs of findings in this group')
    analysis: str = Field(..., description='Analysis of how these findings are related')
    agent_name: str = Field(..., description='Name of the agent creating the group')
    timestamp: datetime | None = Field(default=None, description='When created')


class SpecialistFinding(BaseModel):
    """A single finding for the structured handoff report.

    Used as part of SpecialistHandoffReport to guarantee findings are captured
    when a specialist hands off to the InvestigationAgent.
    """

    key: str = Field(
        ..., description="Resource identifier (e.g., 'node:worker-1', 'osd:osd.5', 'pod:ns/name')"
    )
    value: str = Field(..., description='Concise description of the finding')
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description='Certainty: 0.9-1.0 confirmed, 0.7-0.8 likely, 0.5-0.6 possible',
    )


class SpecialistHandoffReport(BaseModel):
    """Structured report that specialists MUST provide when handing off.

    The SDK validates this schema and the on_handoff callback auto-persists
    findings to SharedContext, eliminating the risk of lost findings.
    """

    findings: list[SpecialistFinding] = Field(
        ..., description='All findings discovered during investigation'
    )
    summary: str = Field(..., description='One-paragraph summary of investigation results')
    domain: str = Field(
        ..., description='Domain investigated (compute, storage, network, observability)'
    )
    resources_checked: list[str] = Field(
        default_factory=list,
        description='Resources that were checked (e.g., pod names, node names)',
    )
    root_cause_identified: bool = Field(
        default=False,
        description='Whether a root cause was identified with high confidence',
    )


class SharedContext(BaseModel):
    """The Blackboard - a shared context for all agents.

    This class maintains a collection of findings that can be read and written
    by any agent in the investigation workflow. It enables cross-agent
    correlation and prevents redundant investigations.

    Findings have stable auto-incrementing IDs and key-based semantic
    deduplication (higher confidence wins for the same key).
    """

    findings: list[SharedFinding] = Field(default_factory=list)
    groups: list[InvestigationGroup] = Field(default_factory=list)
    _next_finding_id: int = PrivateAttr(default=1)

    def add_finding(
        self,
        key: str,
        value: str,
        confidence: float,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> SharedFinding:
        """Add or update a finding in the shared context.

        Uses key-based semantic dedup: if a finding with the same key exists
        and the new confidence is higher, the existing finding is updated
        in place. Otherwise the existing finding is kept unchanged.

        Args:
            key: Resource identifier
            value: Observed status or issue
            confidence: Certainty level (0.0 - 1.0)
            agent_name: Name of the recording agent
            metadata: Additional context
            timestamp: When the finding was recorded (use workflow.now() in workflows)

        Returns:
            The created or existing SharedFinding
        """
        existing = next((f for f in self.findings if f.key == key), None)
        if existing is not None:
            if confidence > existing.confidence:
                existing.value = value
                existing.confidence = confidence
                existing.agent_name = agent_name
                existing.metadata = metadata or {}
                existing.timestamp = timestamp
            return existing

        finding_id = self._next_finding_id
        self._next_finding_id += 1
        finding = SharedFinding(
            id=finding_id,
            key=key,
            value=value,
            confidence=confidence,
            agent_name=agent_name,
            metadata=metadata or {},
            timestamp=timestamp,
        )
        self.findings.append(finding)
        return finding

    def get_finding_by_id(self, finding_id: int) -> SharedFinding | None:
        """Get a finding by its stable ID.

        Args:
            finding_id: The finding's stable identifier

        Returns:
            The finding, or None if not found
        """
        return next((f for f in self.findings if f.id == finding_id), None)

    def add_group(
        self,
        name: str,
        finding_ids: list[int],
        analysis: str,
        agent_name: str,
        timestamp: datetime | None = None,
    ) -> InvestigationGroup:
        """Add a new group of findings.

        Args:
            name: Group name
            finding_ids: List of stable finding IDs
            analysis: Root cause analysis
            agent_name: Agent creating the group
            timestamp: Creation timestamp

        Returns:
            The created InvestigationGroup
        """
        group = InvestigationGroup(
            name=name,
            finding_ids=finding_ids,
            analysis=analysis,
            agent_name=agent_name,
            timestamp=timestamp,
        )
        self.groups.append(group)
        return group

    def compact(self, min_confidence: float = 0.3) -> dict[str, int]:
        """Remove low-confidence findings and clean up orphaned groups.

        Args:
            min_confidence: Drop findings below this confidence

        Returns:
            Dict with 'dropped' count and 'remaining' count
        """
        before_count = len(self.findings)
        self.findings = [f for f in self.findings if f.confidence >= min_confidence]
        dropped = before_count - len(self.findings)

        remaining_ids = {f.id for f in self.findings}
        for group in self.groups:
            group.finding_ids = [fid for fid in group.finding_ids if fid in remaining_ids]
        self.groups = [g for g in self.groups if g.finding_ids]

        return {'dropped': dropped, 'remaining': len(self.findings)}

    def get_findings(
        self, filter_key: str | None = None, min_confidence: float = 0.0
    ) -> list[SharedFinding]:
        """Retrieve findings from the shared context.

        Args:
            filter_key: Optional key prefix to filter by (e.g., 'host:' or 'service:')
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching findings
        """
        results = []
        for finding in self.findings:
            if min_confidence > 0 and finding.confidence < min_confidence:
                continue
            if (
                filter_key
                and not finding.key.startswith(filter_key)
                and filter_key not in finding.key
            ):
                continue
            results.append(finding)
        return results

    def get_high_confidence_root_causes(self, threshold: float = 0.8) -> list[SharedFinding]:
        """Get findings that likely represent root causes.

        Args:
            threshold: Minimum confidence to consider as root cause

        Returns:
            High-confidence findings sorted by confidence (descending)
        """
        high_conf = [f for f in self.findings if f.confidence >= threshold]
        return sorted(high_conf, key=lambda x: x.confidence, reverse=True)

    def has_root_cause_for_resource(self, resource_key: str, threshold: float = 0.8) -> bool:
        """Check if a root cause has already been identified for a resource.

        Args:
            resource_key: The resource to check
            threshold: Confidence threshold for root cause

        Returns:
            True if a high-confidence finding exists for this resource
        """
        for finding in self.findings:
            if finding.key == resource_key and finding.confidence >= threshold:
                return True
        return False

    def format_summary(self) -> str:
        """Format all findings as a human-readable summary.

        Returns:
            Formatted string of all findings
        """
        if not self.findings:
            return 'No findings recorded yet.'

        lines = ['=== Shared Context Findings ===']
        lines.extend(
            f'[#{f.id}] [{f.agent_name}] {f.key}: {f.value} (confidence: {f.confidence:.2f})'
            for f in self.findings
        )
        return '\n'.join(lines)
