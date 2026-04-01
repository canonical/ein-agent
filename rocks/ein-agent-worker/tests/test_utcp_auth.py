"""Tests for UTCP auth providers: KubeconfigAuthProvider, BearerAuthProvider, NoAuthProvider."""

import base64
from unittest.mock import MagicMock

import pytest

from ein_agent_worker.utcp.auth import (
    AuthProviderRegistry,
    AuthResult,
    BearerAuthProvider,
    KubeconfigAuthProvider,
    NoAuthProvider,
    extract_token_from_kubeconfig,
)

# =============================================================================
# AuthResult model
# =============================================================================


class TestAuthResult:
    def test_empty_result(self):
        result = AuthResult()
        assert result.auth_dict is None
        assert result.variable_loaders == []
        assert result.has_auth is False

    def test_result_with_auth(self):
        result = AuthResult(auth_dict={'auth_type': 'api_key'})
        assert result.has_auth is True


# =============================================================================
# extract_token_from_kubeconfig
# =============================================================================

VALID_KUBECONFIG = {
    'current-context': 'test-context',
    'contexts': [{'name': 'test-context', 'context': {'cluster': 'test', 'user': 'test-user'}}],
    'users': [{'name': 'test-user', 'user': {'token': 'my-secret-token'}}],
}


class TestExtractTokenFromKubeconfig:
    def test_valid_kubeconfig(self):
        token = extract_token_from_kubeconfig(VALID_KUBECONFIG, 'kubernetes')
        assert token == 'my-secret-token'

    def test_missing_current_context(self):
        with pytest.raises(ValueError, match='No current-context'):
            extract_token_from_kubeconfig({}, 'kubernetes')

    def test_missing_user(self):
        kubeconfig = {
            'current-context': 'ctx',
            'contexts': [{'name': 'ctx', 'context': {'cluster': 'c', 'user': 'missing'}}],
            'users': [],
        }
        with pytest.raises(ValueError, match="User 'missing' not found"):
            extract_token_from_kubeconfig(kubeconfig, 'kubernetes')

    def test_no_token_in_user(self):
        kubeconfig = {
            'current-context': 'ctx',
            'contexts': [{'name': 'ctx', 'context': {'cluster': 'c', 'user': 'u'}}],
            'users': [{'name': 'u', 'user': {'client-certificate': 'cert.pem'}}],
        }
        with pytest.raises(ValueError, match='No token found'):
            extract_token_from_kubeconfig(kubeconfig, 'kubernetes')


# =============================================================================
# KubeconfigAuthProvider
# =============================================================================


class TestKubeconfigAuthProvider:
    def test_resolve_success(self, monkeypatch):
        kubeconfig_yaml = (
            'current-context: ctx\n'
            'contexts:\n'
            '  - name: ctx\n'
            '    context:\n'
            '      cluster: c\n'
            '      user: u\n'
            'users:\n'
            '  - name: u\n'
            '    user:\n'
            '      token: k8s-token-123\n'
        )
        b64 = base64.b64encode(kubeconfig_yaml.encode()).decode()
        monkeypatch.setenv('UTCP_KUBERNETES_PROD_KUBECONFIG_CONTENT', b64)

        result = KubeconfigAuthProvider().resolve('kubernetes-prod')

        assert result.has_auth is True
        assert 'k8s-token-123' in result.auth_dict['api_key']

    def test_resolve_missing_env_var(self, monkeypatch):
        monkeypatch.delenv('UTCP_KUBERNETES_PROD_KUBECONFIG_CONTENT', raising=False)

        with pytest.raises(ValueError, match='environment variable not found'):
            KubeconfigAuthProvider().resolve('kubernetes-prod')

    def test_resolve_with_handler_variable_loader(self, monkeypatch):
        kubeconfig_yaml = (
            'current-context: ctx\n'
            'contexts:\n'
            '  - name: ctx\n'
            '    context: {cluster: c, user: u}\n'
            'users:\n'
            '  - name: u\n'
            '    user: {token: tok}\n'
        )
        b64 = base64.b64encode(kubeconfig_yaml.encode()).decode()
        monkeypatch.setenv('UTCP_KUBERNETES_KUBECONFIG_CONTENT', b64)

        handler = MagicMock()
        handler.get_variable_loader.return_value = MagicMock()

        result = KubeconfigAuthProvider().resolve('kubernetes', handler=handler)

        assert len(result.variable_loaders) == 1
        handler.get_variable_loader.assert_called_once_with('tok', instance_name='kubernetes')


# =============================================================================
# BearerAuthProvider
# =============================================================================


class TestBearerAuthProvider:
    def test_resolve_from_env(self, monkeypatch):
        monkeypatch.setenv('UTCP_GRAFANA_TOKEN', 'grafana-token-abc')

        result = BearerAuthProvider().resolve('grafana')

        assert result.has_auth is True
        assert result.auth_dict['api_key'] == 'Bearer grafana-token-abc'

    def test_resolve_from_parameter(self, monkeypatch):
        monkeypatch.delenv('UTCP_GRAFANA_TOKEN', raising=False)

        result = BearerAuthProvider().resolve('grafana', token='param-token')

        assert result.auth_dict['api_key'] == 'Bearer param-token'

    def test_env_takes_precedence_over_parameter(self, monkeypatch):
        monkeypatch.setenv('UTCP_GRAFANA_TOKEN', 'env-token')

        result = BearerAuthProvider().resolve('grafana', token='param-token')

        assert result.auth_dict['api_key'] == 'Bearer env-token'

    def test_resolve_missing_token(self, monkeypatch):
        monkeypatch.delenv('UTCP_GRAFANA_TOKEN', raising=False)

        with pytest.raises(ValueError, match='environment variable not found'):
            BearerAuthProvider().resolve('grafana')

    def test_resolve_hyphenated_service_name(self, monkeypatch):
        monkeypatch.setenv('UTCP_GRAFANA_PROD_TOKEN', 'gp-token')

        result = BearerAuthProvider().resolve('grafana-prod')

        assert result.auth_dict['api_key'] == 'Bearer gp-token'


# =============================================================================
# NoAuthProvider
# =============================================================================


class TestNoAuthProvider:
    def test_resolve_returns_empty(self):
        result = NoAuthProvider().resolve('prometheus')
        assert result.has_auth is False
        assert result.auth_dict is None
        assert result.variable_loaders == []


# =============================================================================
# AuthProviderRegistry
# =============================================================================


class TestAuthProviderRegistry:
    def test_known_types(self):
        assert isinstance(AuthProviderRegistry.get('kubeconfig'), KubeconfigAuthProvider)
        assert isinstance(AuthProviderRegistry.get('bearer'), BearerAuthProvider)
        assert isinstance(AuthProviderRegistry.get('none'), NoAuthProvider)

    def test_unknown_type_returns_no_auth(self):
        provider = AuthProviderRegistry.get('proxy')
        assert isinstance(provider, NoAuthProvider)

    def test_register_custom_provider(self):
        custom = MagicMock()
        AuthProviderRegistry.register('custom', custom)
        assert AuthProviderRegistry.get('custom') is custom
        # Cleanup
        AuthProviderRegistry._providers.pop('custom', None)
