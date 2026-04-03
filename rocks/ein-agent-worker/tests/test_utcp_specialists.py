"""Tests for specialist instruction builders and domain UTCP tool routing."""

from unittest.mock import MagicMock

from ein_agent_worker.models.domain import DomainType, SkillInfo
from ein_agent_worker.workflows.agents.factory import _get_domain_utcp_tools
from ein_agent_worker.workflows.agents.specialists import (
    build_services_section,
    build_skills_section,
)

# =============================================================================
# T6: build_services_section() with instance_names
# =============================================================================


class TestBuildServicesSection:
    def test_single_instance_no_instance_names(self):
        result = build_services_section(['kubernetes'])
        assert 'call_kubernetes_operation' in result
        assert 'search_kubernetes_operations' in result
        assert 'get_kubernetes_operation_details' in result

    def test_multi_instance(self):
        result = build_services_section(
            ['kubernetes'],
            instance_names={'kubernetes': ['kubernetes-prod', 'kubernetes-staging']},
        )
        assert 'call_kubernetes_prod_operation' in result
        assert 'call_kubernetes_staging_operation' in result
        # Read tools should still use the type name
        assert 'search_kubernetes_operations' in result

    def test_no_services(self):
        result = build_services_section([])
        assert 'no UTCP services' in result.lower() or 'No UTCP services' in result


# =============================================================================
# T7: _get_domain_utcp_tools() type-based routing
# =============================================================================


class TestGetDomainUtcpTools:
    def test_correct_tools_returned(self):
        k8s_tools = [MagicMock(name='k8s_tool_1'), MagicMock(name='k8s_tool_2')]
        grafana_tools = [MagicMock(name='grafana_tool')]
        utcp_tools = {
            'kubernetes': k8s_tools,
            'grafana': grafana_tools,
        }

        compute_tools = _get_domain_utcp_tools(DomainType.COMPUTE, utcp_tools)
        assert compute_tools == k8s_tools

        observability_tools = _get_domain_utcp_tools(DomainType.OBSERVABILITY, utcp_tools)
        assert observability_tools == grafana_tools

    def test_missing_type_returns_empty(self):
        utcp_tools = {'grafana': [MagicMock()]}
        # COMPUTE needs 'kubernetes' which is not in utcp_tools
        result = _get_domain_utcp_tools(DomainType.COMPUTE, utcp_tools)
        assert result == []

    def test_storage_gets_ceph_and_kubernetes(self):
        k8s_tools = [MagicMock(name='k8s')]
        ceph_tools = [MagicMock(name='ceph')]
        utcp_tools = {
            'kubernetes': k8s_tools,
            'ceph': ceph_tools,
        }

        storage_tools = _get_domain_utcp_tools(DomainType.STORAGE, utcp_tools)
        # Storage domain maps to both ceph and kubernetes
        assert len(storage_tools) == 2
        assert set(storage_tools) == {k8s_tools[0], ceph_tools[0]}


# =============================================================================
# T8: SkillInfo domain accepts arbitrary strings (e.g., "general")
# =============================================================================


class TestSkillInfoDomain:
    def test_accepts_domain_type_values(self):
        skill = SkillInfo(name='test', description='desc', domain='compute')
        assert skill.domain == 'compute'

    def test_accepts_general_domain(self):
        skill = SkillInfo(name='test', description='desc', domain='general')
        assert skill.domain == 'general'

    def test_auto_inject_with_content(self):
        skill = SkillInfo(
            name='test',
            description='desc',
            domain='general',
            auto_inject=True,
            content='# Best Practices\nDo not retry 403.',
        )
        assert skill.auto_inject is True
        assert skill.content == '# Best Practices\nDo not retry 403.'

    def test_auto_inject_defaults_false(self):
        skill = SkillInfo(name='test', description='desc', domain='compute')
        assert skill.auto_inject is False
        assert skill.content == ''


# =============================================================================
# T9: build_skills_section() auto-inject behavior
# =============================================================================


class TestBuildSkillsSectionAutoInject:
    def test_auto_inject_skill_content_inlined(self):
        skills = [
            SkillInfo(
                name='utcp-best-practices',
                description='UTCP guide',
                domain='general',
                auto_inject=True,
                content='# UTCP\nDo not retry 403.',
            ),
        ]
        result = build_skills_section(skills, 'compute')
        assert 'Required Knowledge (auto-loaded)' in result
        assert 'Do not retry 403.' in result

    def test_non_auto_inject_skill_not_inlined(self):
        skills = [
            SkillInfo(name='example', description='Example', domain='compute'),
        ]
        result = build_skills_section(skills, 'compute')
        assert 'Required Knowledge' not in result
        assert 'read_skill' in result

    def test_mixed_skills(self):
        skills = [
            SkillInfo(name='example', description='Example', domain='compute'),
            SkillInfo(
                name='utcp-bp',
                description='UTCP guide',
                domain='general',
                auto_inject=True,
                content='# UTCP Best Practices',
            ),
        ]
        result = build_skills_section(skills, 'compute')
        # Both listed by name
        assert 'example' in result
        assert 'utcp-bp' in result
        # Auto-inject content inlined
        assert '# UTCP Best Practices' in result
        # Lazy load instruction still present for non-auto-inject
        assert 'read_skill' in result
