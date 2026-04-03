"""Tests for SharedContext model and related functionality."""

from datetime import datetime

import pytest

from ein_agent_worker.models.investigation import (
    InvestigationGroup,
    SharedContext,
    SharedFinding,
    SpecialistFinding,
    SpecialistHandoffReport,
)
from ein_agent_worker.workflows.agents.factory import _create_specialist_handoff_callback

# =============================================================================
# SharedFinding ID field
# =============================================================================


class TestSharedFindingId:
    def test_finding_requires_id(self):
        f = SharedFinding(id=1, key='host:a', value='ok', confidence=0.5, agent_name='A')
        assert f.id == 1


# =============================================================================
# SharedContext.add_finding — stable IDs
# =============================================================================


class TestAddFindingStableIds:
    def test_assigns_sequential_ids(self):
        ctx = SharedContext()
        f1 = ctx.add_finding(key='host:a', value='ok', confidence=0.5, agent_name='A')
        f2 = ctx.add_finding(key='host:b', value='ok', confidence=0.5, agent_name='A')
        assert f1.id == 1
        assert f2.id == 2

    def test_ids_never_reused_after_compact(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.1, agent_name='A')
        f2 = ctx.add_finding(key='b', value='v', confidence=0.9, agent_name='A')
        ctx.compact(min_confidence=0.5)
        f3 = ctx.add_finding(key='c', value='v', confidence=0.8, agent_name='A')
        assert f3.id == 3  # not 2
        assert f2.id == 2


# =============================================================================
# SharedContext.add_finding — semantic dedup
# =============================================================================


class TestAddFindingSemanticDedup:
    def test_same_key_higher_confidence_updates(self):
        ctx = SharedContext()
        f1 = ctx.add_finding(key='host:a', value='maybe bad', confidence=0.5, agent_name='A')
        f2 = ctx.add_finding(key='host:a', value='definitely bad', confidence=0.9, agent_name='B')
        assert len(ctx.findings) == 1
        assert f2.id == f1.id
        assert ctx.findings[0].value == 'definitely bad'
        assert ctx.findings[0].confidence == 0.9
        assert ctx.findings[0].agent_name == 'B'

    def test_same_key_lower_confidence_skips(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='bad', confidence=0.9, agent_name='A')
        f2 = ctx.add_finding(key='host:a', value='maybe bad', confidence=0.5, agent_name='B')
        assert len(ctx.findings) == 1
        assert ctx.findings[0].value == 'bad'
        assert f2.value == 'bad'  # returns existing

    def test_same_key_equal_confidence_skips(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='bad', confidence=0.7, agent_name='A')
        ctx.add_finding(key='host:a', value='also bad', confidence=0.7, agent_name='B')
        assert len(ctx.findings) == 1
        assert ctx.findings[0].value == 'bad'  # first one wins on tie

    def test_different_keys_both_kept(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='v1', confidence=0.5, agent_name='A')
        ctx.add_finding(key='host:b', value='v2', confidence=0.5, agent_name='A')
        assert len(ctx.findings) == 2

    def test_update_preserves_metadata(self):
        ctx = SharedContext()
        ctx.add_finding(
            key='host:a',
            value='v1',
            confidence=0.5,
            agent_name='A',
            metadata={'source': 'tool'},
        )
        ctx.add_finding(
            key='host:a',
            value='v2',
            confidence=0.9,
            agent_name='B',
            metadata={'source': 'handoff'},
        )
        assert ctx.findings[0].metadata == {'source': 'handoff'}

    def test_update_preserves_timestamp(self):
        ctx = SharedContext()
        t1 = datetime(2025, 1, 1)
        t2 = datetime(2025, 6, 1)
        ctx.add_finding(key='host:a', value='v1', confidence=0.5, agent_name='A', timestamp=t1)
        ctx.add_finding(key='host:a', value='v2', confidence=0.9, agent_name='B', timestamp=t2)
        assert ctx.findings[0].timestamp == t2


# =============================================================================
# SharedContext.get_finding_by_id
# =============================================================================


class TestGetFindingById:
    def test_found(self):
        ctx = SharedContext()
        f = ctx.add_finding(key='x', value='y', confidence=0.5, agent_name='A')
        assert ctx.get_finding_by_id(f.id) is f

    def test_not_found(self):
        ctx = SharedContext()
        assert ctx.get_finding_by_id(999) is None

    def test_after_multiple_findings(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.5, agent_name='A')
        f2 = ctx.add_finding(key='b', value='v', confidence=0.5, agent_name='A')
        ctx.add_finding(key='c', value='v', confidence=0.5, agent_name='A')
        assert ctx.get_finding_by_id(f2.id) is f2


# =============================================================================
# SharedContext.compact
# =============================================================================


class TestCompact:
    def test_drops_low_confidence(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.2, agent_name='A')
        ctx.add_finding(key='b', value='v', confidence=0.5, agent_name='A')
        result = ctx.compact(min_confidence=0.3)
        assert result == {'dropped': 1, 'remaining': 1}
        assert ctx.findings[0].key == 'b'

    def test_keeps_findings_at_threshold(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.3, agent_name='A')
        result = ctx.compact(min_confidence=0.3)
        assert result == {'dropped': 0, 'remaining': 1}

    def test_cleans_orphaned_group_refs(self):
        ctx = SharedContext()
        f1 = ctx.add_finding(key='a', value='v', confidence=0.2, agent_name='A')
        f2 = ctx.add_finding(key='b', value='v', confidence=0.8, agent_name='A')
        ctx.add_group(name='G', finding_ids=[f1.id, f2.id], analysis='x', agent_name='A')
        ctx.compact(min_confidence=0.3)
        assert ctx.groups[0].finding_ids == [f2.id]

    def test_removes_empty_groups(self):
        ctx = SharedContext()
        f1 = ctx.add_finding(key='a', value='v', confidence=0.1, agent_name='A')
        ctx.add_group(name='G', finding_ids=[f1.id], analysis='x', agent_name='A')
        ctx.compact(min_confidence=0.3)
        assert len(ctx.groups) == 0

    def test_empty_context(self):
        ctx = SharedContext()
        result = ctx.compact()
        assert result == {'dropped': 0, 'remaining': 0}


# =============================================================================
# InvestigationGroup with finding_ids
# =============================================================================


class TestInvestigationGroup:
    def test_uses_finding_ids(self):
        ctx = SharedContext()
        f1 = ctx.add_finding(key='a', value='v', confidence=0.9, agent_name='A')
        f2 = ctx.add_finding(key='b', value='v', confidence=0.8, agent_name='A')
        g = ctx.add_group(name='G', finding_ids=[f1.id, f2.id], analysis='related', agent_name='A')
        assert g.finding_ids == [1, 2]

    def test_group_model_field_name(self):
        g = InvestigationGroup(name='G', finding_ids=[1, 2], analysis='x', agent_name='A')
        assert g.finding_ids == [1, 2]


# =============================================================================
# SharedContext.format_summary
# =============================================================================


class TestFormatSummary:
    def test_empty(self):
        ctx = SharedContext()
        assert ctx.format_summary() == 'No findings recorded yet.'

    def test_shows_finding_ids(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='down', confidence=0.9, agent_name='A')
        ctx.add_finding(key='host:b', value='ok', confidence=0.5, agent_name='B')
        summary = ctx.format_summary()
        assert '[#1]' in summary
        assert '[#2]' in summary
        assert 'host:a' in summary
        assert 'host:b' in summary


# =============================================================================
# Existing methods still work with new ID system
# =============================================================================


class TestExistingMethods:
    def test_get_findings_filter_key(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='v', confidence=0.5, agent_name='A')
        ctx.add_finding(key='pod:b', value='v', confidence=0.5, agent_name='A')
        results = ctx.get_findings(filter_key='host:')
        assert len(results) == 1
        assert results[0].key == 'host:a'

    def test_get_findings_min_confidence(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.3, agent_name='A')
        ctx.add_finding(key='b', value='v', confidence=0.8, agent_name='A')
        results = ctx.get_findings(min_confidence=0.5)
        assert len(results) == 1
        assert results[0].key == 'b'

    def test_get_high_confidence_root_causes(self):
        ctx = SharedContext()
        ctx.add_finding(key='a', value='v', confidence=0.5, agent_name='A')
        ctx.add_finding(key='b', value='v', confidence=0.9, agent_name='A')
        results = ctx.get_high_confidence_root_causes()
        assert len(results) == 1
        assert results[0].key == 'b'

    def test_has_root_cause_for_resource(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='v', confidence=0.9, agent_name='A')
        assert ctx.has_root_cause_for_resource('host:a') is True
        assert ctx.has_root_cause_for_resource('host:b') is False


# =============================================================================
# Specialist handoff callback with semantic dedup
# =============================================================================


class TestSpecialistHandoffCallback:
    @pytest.mark.asyncio
    async def test_handoff_uses_semantic_dedup_lower_skipped(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='bad', confidence=0.9, agent_name='Spec')
        callback = _create_specialist_handoff_callback(
            shared_context=ctx,
            agent_name='Spec',
            get_timestamp=lambda: datetime(2025, 1, 1),
        )
        report = SpecialistHandoffReport(
            findings=[SpecialistFinding(key='host:a', value='also bad', confidence=0.7)],
            summary='test',
            domain='compute',
        )
        await callback(None, report)
        assert len(ctx.findings) == 1
        assert ctx.findings[0].value == 'bad'  # unchanged

    @pytest.mark.asyncio
    async def test_handoff_uses_semantic_dedup_higher_updates(self):
        ctx = SharedContext()
        ctx.add_finding(key='host:a', value='maybe bad', confidence=0.5, agent_name='Spec')
        callback = _create_specialist_handoff_callback(
            shared_context=ctx,
            agent_name='Spec',
            get_timestamp=lambda: datetime(2025, 1, 1),
        )
        report = SpecialistHandoffReport(
            findings=[SpecialistFinding(key='host:a', value='confirmed bad', confidence=0.95)],
            summary='test',
            domain='compute',
        )
        await callback(None, report)
        assert len(ctx.findings) == 1
        assert ctx.findings[0].value == 'confirmed bad'
        assert ctx.findings[0].confidence == 0.95

    @pytest.mark.asyncio
    async def test_handoff_new_finding_added(self):
        ctx = SharedContext()
        callback = _create_specialist_handoff_callback(
            shared_context=ctx,
            agent_name='Spec',
            get_timestamp=lambda: datetime(2025, 1, 1),
        )
        report = SpecialistHandoffReport(
            findings=[SpecialistFinding(key='host:a', value='bad', confidence=0.9)],
            summary='test',
            domain='compute',
        )
        await callback(None, report)
        assert len(ctx.findings) == 1
        assert ctx.findings[0].key == 'host:a'
        assert ctx.findings[0].id == 1
