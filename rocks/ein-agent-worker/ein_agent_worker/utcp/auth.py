"""Authentication providers for UTCP services.

Each auth type is implemented as a separate AuthProvider subclass,
enabling atomic testing and clean separation of concerns.

Usage:
    provider = AuthProviderRegistry.get("kubeconfig")
    result = provider.resolve("kubernetes-prod")
    # result.auth_dict -> dict for call_template['auth']
    # result.variable_loaders -> list of variable loaders
"""

import abc
import base64
import logging
import os
from typing import ClassVar

import yaml
from pydantic import BaseModel, Field

from ein_agent_worker.utcp.openapi_handlers.base import OpenApiHandler

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models
# =============================================================================


class AuthResult(BaseModel):
    """Result of an authentication resolution.

    Attributes:
        auth_dict: Auth configuration dict for the UTCP call template,
            or None when no authentication is needed.
        variable_loaders: Variable loader dicts for the UTCP client config.
    """

    auth_dict: dict | None = None
    variable_loaders: list = Field(default_factory=list)

    @property
    def has_auth(self) -> bool:
        """Whether this result carries authentication configuration."""
        return self.auth_dict is not None


# =============================================================================
# Base Class
# =============================================================================


class AuthProvider(abc.ABC):
    """Base class for UTCP authentication providers."""

    @abc.abstractmethod
    def resolve(
        self, service_name: str, *, token: str = '', handler: OpenApiHandler | None = None
    ) -> AuthResult:
        """Resolve authentication for a service instance.

        Args:
            service_name: Service instance name (e.g., 'kubernetes-prod').
            token: Optional token parameter (meaning depends on provider).
            handler: Optional OpenAPI handler for variable loader creation.

        Returns:
            AuthResult with auth configuration.

        Raises:
            ValueError: If required credentials are missing or invalid.
        """


# =============================================================================
# Concrete Providers
# =============================================================================


def _service_env_key(service_name: str) -> str:
    """Convert service name to uppercase env-var fragment."""
    return service_name.upper().replace('-', '_')


def _build_bearer_auth_dict(bearer_token: str) -> dict:
    """Build the standard bearer auth dict for a UTCP call template."""
    return {
        'auth_type': 'api_key',
        'api_key': f'Bearer {bearer_token}',
        'var_name': 'Authorization',
        'location': 'header',
    }


def _build_variable_loaders(
    handler: OpenApiHandler | None, bearer_token: str, instance_name: str = ''
) -> list:
    """Build variable loaders from an OpenAPI handler if available."""
    if handler is None:
        return []
    loader = handler.get_variable_loader(bearer_token, instance_name=instance_name)
    return [loader] if loader else []


class KubeconfigAuthProvider(AuthProvider):
    """Resolve auth from a base64-encoded kubeconfig in an env var.

    Expects ``UTCP_{SERVICE}_KUBECONFIG_CONTENT`` to be set.
    The kubeconfig is decoded and parsed entirely in memory.
    """

    def resolve(  # noqa: D102
        self, service_name: str, *, token: str = '', handler: OpenApiHandler | None = None
    ) -> AuthResult:
        env_key = f'UTCP_{_service_env_key(service_name)}_KUBECONFIG_CONTENT'
        kubeconfig_b64 = os.getenv(env_key)

        if not kubeconfig_b64:
            raise ValueError(
                f'[{service_name}] {env_key} environment variable not found. '
                'Ensure Juju secret with kubeconfig-content is granted.'
            )

        try:
            kubeconfig_yaml = base64.b64decode(kubeconfig_b64).decode('utf-8')
            kubeconfig_data = yaml.safe_load(kubeconfig_yaml)
            bearer_token = extract_token_from_kubeconfig(kubeconfig_data, service_name)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f'[{service_name}] Failed to process kubeconfig: {e}') from e

        logger.info(
            '[%s] Token extracted from kubeconfig (in-memory, no disk write)', service_name
        )

        return AuthResult(
            auth_dict=_build_bearer_auth_dict(bearer_token),
            variable_loaders=_build_variable_loaders(
                handler, bearer_token, instance_name=service_name
            ),
        )


class BearerAuthProvider(AuthProvider):
    """Resolve auth from a bearer token env var or explicit parameter.

    Checks ``UTCP_{SERVICE}_TOKEN`` first, then falls back to the *token* parameter.
    """

    def resolve(  # noqa: D102
        self, service_name: str, *, token: str = '', handler: OpenApiHandler | None = None
    ) -> AuthResult:
        env_key = f'UTCP_{_service_env_key(service_name)}_TOKEN'
        bearer_token = os.getenv(env_key) or token

        if not bearer_token:
            raise ValueError(
                f'[{service_name}] {env_key} environment variable not found. '
                'Ensure Juju secret with token is granted.'
            )

        logger.info('[%s] Using bearer token from environment', service_name)

        return AuthResult(
            auth_dict=_build_bearer_auth_dict(bearer_token),
            variable_loaders=_build_variable_loaders(
                handler, bearer_token, instance_name=service_name
            ),
        )


class NoAuthProvider(AuthProvider):
    """No-op provider for services that require no authentication."""

    def resolve(  # noqa: D102
        self, service_name: str, *, token: str = '', handler: OpenApiHandler | None = None
    ) -> AuthResult:
        logger.info('[%s] No authentication configured (auth_type=none)', service_name)
        return AuthResult()


# =============================================================================
# Registry
# =============================================================================


class AuthProviderRegistry:
    """Registry mapping auth_type strings to AuthProvider instances."""

    _providers: ClassVar[dict[str, AuthProvider]] = {
        'kubeconfig': KubeconfigAuthProvider(),
        'bearer': BearerAuthProvider(),
        'none': NoAuthProvider(),
    }

    @classmethod
    def get(cls, auth_type: str) -> AuthProvider:
        """Look up a provider by auth_type.

        Falls back to NoAuthProvider for unknown types (e.g., 'proxy').
        """
        return cls._providers.get(auth_type, NoAuthProvider())

    @classmethod
    def register(cls, auth_type: str, provider: AuthProvider) -> None:
        """Register a custom auth provider."""
        cls._providers[auth_type] = provider


# =============================================================================
# Kubeconfig Token Extraction
# =============================================================================


def extract_token_from_kubeconfig(kubeconfig_data: dict, service_name: str) -> str:
    """Extract bearer token from a parsed kubeconfig dict (in memory).

    Args:
        kubeconfig_data: Parsed kubeconfig as dictionary.
        service_name: Service name for logging.

    Returns:
        Bearer token string (without ``Bearer `` prefix).

    Raises:
        ValueError: If token cannot be extracted from kubeconfig.
    """
    try:
        current_context = kubeconfig_data.get('current-context')
        if not current_context:
            raise ValueError('No current-context found in kubeconfig')

        contexts = {c['name']: c['context'] for c in kubeconfig_data.get('contexts', [])}
        users = {u['name']: u['user'] for u in kubeconfig_data.get('users', [])}

        if current_context not in contexts:
            raise ValueError(f"Current context '{current_context}' not found in kubeconfig")

        context = contexts[current_context]
        user_name = context.get('user')
        if not user_name:
            raise ValueError(f"No user found in context '{current_context}'")

        user = users.get(user_name, {})
        if not user:
            raise ValueError(f"User '{user_name}' not found in kubeconfig users list")

        token = user.get('token', '')

        if not token:
            token_file = user.get('tokenFile', '')
            if token_file:
                logger.warning(
                    '[%s] kubeconfig uses tokenFile reference: %s. '
                    'For better security, embed the token directly in kubeconfig.',
                    service_name,
                    token_file,
                )
                try:
                    with open(token_file) as f:
                        token = f.read().strip()
                except Exception as e:
                    raise ValueError(f'Failed to read token from {token_file}: {e}') from e

        if not token:
            raise ValueError(
                f"No token found for user '{user_name}'. "
                "Ensure kubeconfig contains 'token' field in user configuration."
            )

        logger.debug(
            '[%s] Token extracted successfully (length: %d chars)',
            service_name,
            len(token),
        )
        return token

    except ValueError:
        raise
    except Exception as e:
        logger.error('[%s] Kubeconfig parsing error: %s', service_name, e)
        raise ValueError(f'Kubeconfig parsing failed: {e}') from e
