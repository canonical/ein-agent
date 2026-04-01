"""Tests for UTCP config: instance name validation, type resolution, and service config."""

import pytest

from ein_agent_worker.utcp.config import (
    UTCPServiceConfig,
    resolve_service_type,
    validate_instance_name,
)

# =============================================================================
# T1: validate_instance_name()
# =============================================================================


class TestValidateInstanceName:
    @pytest.mark.parametrize(
        'name',
        ['kubernetes', 'kubernetes-prod', 'k8s-cluster-01'],
    )
    def test_valid_names(self, name: str):
        assert validate_instance_name(name) is True

    @pytest.mark.parametrize(
        'name',
        [
            '',
            'Kubernetes',
            'kubernetes_prod',
            '-kubernetes',
            'kubernetes-',
            '123abc',
        ],
    )
    def test_invalid_names(self, name: str):
        assert validate_instance_name(name) is False


# =============================================================================
# T2: resolve_service_type()
# =============================================================================


class TestResolveServiceType:
    def test_direct_known_type(self):
        assert resolve_service_type('kubernetes') == 'kubernetes'

    def test_suffix_strip(self):
        assert resolve_service_type('kubernetes-prod') == 'kubernetes'

    def test_multi_suffix_strip(self):
        assert resolve_service_type('kubernetes-prod-us') == 'kubernetes'

    def test_explicit_env_override(self, monkeypatch):
        monkeypatch.setenv('UTCP_CUSTOM_SVC_TYPE', 'kubernetes')
        assert resolve_service_type('custom-svc') == 'kubernetes'

    def test_unknown_fallback(self):
        assert resolve_service_type('unknown-service') == 'unknown-service'


# =============================================================================
# T3: UTCPServiceConfig.resolved_type
# =============================================================================


class TestUTCPServiceConfigResolvedType:
    def test_with_service_type_set(self):
        config = UTCPServiceConfig(
            name='kubernetes-prod',
            openapi_url='http://example.com',
            service_type='kubernetes',
        )
        assert config.resolved_type == 'kubernetes'

    def test_without_service_type(self):
        config = UTCPServiceConfig(
            name='kubernetes',
            openapi_url='http://example.com',
        )
        assert config.resolved_type == 'kubernetes'

    def test_without_service_type_falls_back_to_name(self):
        config = UTCPServiceConfig(
            name='my-custom-service',
            openapi_url='http://example.com',
        )
        assert config.resolved_type == 'my-custom-service'
