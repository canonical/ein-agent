"""UTCP configuration from environment variables.

Configuration Format:
    UTCP_SERVICES: Comma-separated list of service instance names
        (e.g., "kubernetes,grafana,ceph" or "kubernetes-prod,kubernetes-staging,grafana")
    UTCP_{SERVICE}_OPENAPI_URL: URL to the OpenAPI spec (required)
    UTCP_{SERVICE}_AUTH_TYPE: Auth type - 'proxy', 'bearer', 'api_key', 'jwt', 'kubeconfig'
    UTCP_{SERVICE}_TOKEN: Bearer token for direct API access (required when AUTH_TYPE=bearer)
    UTCP_{SERVICE}_KUBECONFIG_CONTENT: Base64-encoded kubeconfig (when AUTH_TYPE=kubeconfig)
    UTCP_{SERVICE}_INSECURE: Skip TLS verification (default: false)
    UTCP_{SERVICE}_ENABLED: Enable/disable the service (default: true)
    UTCP_{SERVICE}_VERSION: Version of the spec to use (default: latest supported)
    UTCP_{SERVICE}_SPEC_SOURCE: Where to load OpenAPI spec - 'local' or 'live' (default: local)
    UTCP_{SERVICE}_TYPE: Explicit service type override (e.g., 'kubernetes')

Multi-Instance Support:
    Multiple instances of the same service type can be configured by using unique
    instance names with a type suffix (e.g., "kubernetes-prod", "kubernetes-staging").
    The service type is auto-detected by stripping hyphen-suffixes from the instance
    name, or can be set explicitly via UTCP_{SERVICE}_TYPE.

Example (single Kubernetes instance):
    export UTCP_SERVICES="kubernetes,grafana"
    export UTCP_KUBERNETES_OPENAPI_URL="https://10.0.0.1:6443/openapi/v2"
    export UTCP_KUBERNETES_AUTH_TYPE="kubeconfig"
    export UTCP_KUBERNETES_KUBECONFIG_CONTENT="<base64-encoded-kubeconfig>"

Example (multiple Kubernetes clusters):
    export UTCP_SERVICES="kubernetes-prod,kubernetes-staging,grafana"
    export UTCP_KUBERNETES_PROD_OPENAPI_URL="https://prod-k8s:6443/openapi/v2"
    export UTCP_KUBERNETES_PROD_AUTH_TYPE="kubeconfig"
    export UTCP_KUBERNETES_PROD_KUBECONFIG_CONTENT="<base64>"
    export UTCP_KUBERNETES_STAGING_OPENAPI_URL="https://staging-k8s:6443/openapi/v2"
    export UTCP_KUBERNETES_STAGING_AUTH_TYPE="kubeconfig"
    export UTCP_KUBERNETES_STAGING_KUBECONFIG_CONTENT="<base64>"
"""

import logging
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


# =============================================================================
# Approval Policies
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


# HTTP methods that are considered "write" operations
WRITE_HTTP_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE', 'CREATE', 'UPDATE'}

# HTTP methods that are considered "read" operations
READ_HTTP_METHODS = {'GET', 'LIST', 'WATCH', 'READ'}


# =============================================================================
# Supported Versions
# =============================================================================


class KubernetesVersion(StrEnum):
    """Supported Kubernetes versions (N-2 support policy)."""

    V1_35 = '1.35'
    V1_34 = '1.34'
    V1_33 = '1.33'

    @classmethod
    def default(cls) -> 'KubernetesVersion':
        """Return the default Kubernetes version."""
        return cls.V1_35


class CephVersion(StrEnum):
    """Supported Ceph versions (active stable releases)."""

    TENTACLE = 'tentacle'  # v20.x
    SQUID = 'squid'  # v19.x
    REEF = 'reef'  # v18.x

    @classmethod
    def default(cls) -> 'CephVersion':
        """Return the default Ceph version."""
        return cls.TENTACLE


class GrafanaVersion(StrEnum):
    """Supported Grafana versions."""

    V12 = '12'
    V11 = '11'

    @classmethod
    def default(cls) -> 'GrafanaVersion':
        """Return the default Grafana version."""
        return cls.V12


class PrometheusVersion(StrEnum):
    """Supported Prometheus versions."""

    V3_5_0 = '3.5.0'

    @classmethod
    def default(cls) -> 'PrometheusVersion':
        """Return the default Prometheus version."""
        return cls.V3_5_0


class LokiVersion(StrEnum):
    """Supported Loki versions."""

    V3 = '3'

    @classmethod
    def default(cls) -> 'LokiVersion':
        """Return the default Loki version."""
        return cls.V3


# Mapping of service names to their version enums
SUPPORTED_VERSIONS = {
    'kubernetes': KubernetesVersion,
    'ceph': CephVersion,
    'grafana': GrafanaVersion,
    'prometheus': PrometheusVersion,
    'loki': LokiVersion,
}

# Default versions for each service
DEFAULT_VERSIONS: dict[str, str] = {
    'kubernetes': KubernetesVersion.default().value,
    'ceph': CephVersion.default().value,
    'grafana': GrafanaVersion.default().value,
    'prometheus': PrometheusVersion.default().value,
    'loki': LokiVersion.default().value,
}

# Known service types (derived from SUPPORTED_VERSIONS)
KNOWN_SERVICE_TYPES: set[str] = set(SUPPORTED_VERSIONS.keys())


# =============================================================================
# Instance Name Validation and Type Resolution
# =============================================================================

# Valid instance name: lowercase letters/digits separated by single hyphens
_INSTANCE_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')


def validate_instance_name(name: str) -> bool:
    """Validate UTCP service instance name format.

    Rules:
    - Must match pattern: lowercase letters/digits separated by single hyphens
    - No leading/trailing hyphens, no consecutive hyphens
    - Must start with a letter
    - Minimum length: 1 character

    Examples:
        Valid: 'kubernetes', 'kubernetes-prod', 'k8s-cluster-01'
        Invalid: 'Kubernetes', 'kubernetes_prod', '-kubernetes', 'kubernetes-'

    Args:
        name: The instance name to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not name:
        return False
    return bool(_INSTANCE_NAME_PATTERN.match(name))


def resolve_service_type(instance_name: str) -> str:
    """Resolve the service type from an instance name.

    Resolution order:
    1. Explicit env var: UTCP_{INSTANCE_KEY}_TYPE
    2. Instance name is itself a known type (e.g., 'kubernetes')
    3. Strip last hyphen-segment progressively (e.g., 'kubernetes-prod' -> 'kubernetes')
    4. Fall back to instance name

    Args:
        instance_name: The unique instance name (e.g., 'kubernetes-prod').

    Returns:
        The resolved service type string (e.g., 'kubernetes').
    """
    instance_key = instance_name.upper().replace('-', '_')

    # 1. Explicit override via env var
    explicit_type = os.getenv(f'UTCP_{instance_key}_TYPE', '').lower()
    if explicit_type:
        if explicit_type not in KNOWN_SERVICE_TYPES:
            logger.warning(
                "UTCP service '%s' has explicit TYPE='%s' which is not a known type (%s)",
                instance_name,
                explicit_type,
                ', '.join(sorted(KNOWN_SERVICE_TYPES)),
            )
        return explicit_type

    # 2. Instance name is itself a known type
    if instance_name in KNOWN_SERVICE_TYPES:
        return instance_name

    # 3. Progressive suffix stripping
    parts = instance_name.split('-')
    for i in range(len(parts) - 1, 0, -1):
        candidate = '-'.join(parts[:i])
        if candidate in KNOWN_SERVICE_TYPES:
            return candidate

    # 4. Fallback to instance name
    return instance_name


# =============================================================================
# Auth Validation Helpers
# =============================================================================

# Service-specific supported auth types mapping
# This avoids circular imports while maintaining service-specific validation
SERVICE_AUTH_TYPES: dict[str, tuple[str, ...]] = {
    'kubernetes': ('kubeconfig',),
    'grafana': ('bearer',),
    'prometheus': ('none', 'bearer'),
    'loki': ('none', 'bearer'),
    # Default for other services
    '_default': ('proxy', 'bearer', 'api_key', 'jwt'),
}

# Service-specific supported spec sources
# Services without a live OpenAPI endpoint should only support 'local'
SERVICE_SPEC_SOURCES: dict[str, tuple[str, ...]] = {
    'loki': ('local',),  # Loki does not serve an OpenAPI spec
    'prometheus': ('local',),  # Prometheus spec is hand-curated from GitHub
    # Default: all sources available
    '_default': ('local', 'live'),
}


def _get_supported_auth_types(service_name: str) -> tuple[str, ...]:
    """Get supported auth types for a service.

    Args:
        service_name: Service name

    Returns:
        Tuple of supported auth type strings
    """
    return SERVICE_AUTH_TYPES.get(service_name, SERVICE_AUTH_TYPES['_default'])


def _validate_kubeconfig_auth(service_name: str, service_key: str) -> bool:
    """Validate kubeconfig authentication configuration.

    Args:
        service_name: Service name for logging
        service_key: Uppercase service key for env var lookup

    Returns:
        True if valid, False otherwise
    """
    kubeconfig_key = f'UTCP_{service_key}_KUBECONFIG_CONTENT'
    kubeconfig_content = os.getenv(kubeconfig_key)

    if not kubeconfig_content:
        logger.error(
            "UTCP service '%s' has auth_type='kubeconfig' but %s is not set. "
            'Ensure Juju secret with kubeconfig-content is granted.',
            service_name,
            kubeconfig_key,
        )
        return False

    logger.info("UTCP service '%s' configured with kubeconfig authentication", service_name)
    return True


def _validate_bearer_auth(service_name: str, service_key: str) -> bool:
    """Validate bearer token authentication configuration.

    Args:
        service_name: Service name for logging
        service_key: Uppercase service key for env var lookup

    Returns:
        True if valid, False otherwise
    """
    token_key = f'UTCP_{service_key}_TOKEN'
    token = os.getenv(token_key, '')

    if not token:
        logger.error(
            "UTCP service '%s' has auth_type='bearer' but %s is not set",
            service_name,
            token_key,
        )
        return False

    logger.info("UTCP service '%s' configured with bearer token authentication", service_name)
    return True


@dataclass
class UTCPServiceConfig:
    """Configuration for a single UTCP service instance.

    Attributes:
        name: Unique instance name (e.g., 'kubernetes', 'kubernetes-prod')
        openapi_url: URL to the OpenAPI specification endpoint (for runtime calls)
        service_type: Resolved service type (e.g., 'kubernetes'). Used for
            validation rules, spec file lookup, and domain routing.
        auth_type: Authentication type ('proxy', 'bearer', 'api_key', 'jwt')
        token: Bearer token for direct API access (required when auth_type='bearer')
        insecure: Skip TLS verification for self-signed certificates
        enabled: Whether the service is enabled
        version: Version of the OpenAPI spec to use (e.g., '1.30', 'reef', '11')
        dynamic: If True, generate tools at runtime from OpenAPI URL
        approval_policy: Policy for requiring human approval (never, always, read_only)
        spec_source: Where to load spec: 'local' or 'live'
    """

    name: str
    openapi_url: str
    service_type: str = ''
    auth_type: str = 'proxy'
    token: str = ''
    insecure: bool = False
    enabled: bool = True
    version: str = ''
    dynamic: bool = False
    approval_policy: str = 'read_only'  # Default: auto-approve reads, require approval for writes
    spec_source: str = 'local'  # Where to load spec: 'local' or 'live'

    @property
    def resolved_type(self) -> str:
        """Return service_type if set, otherwise fall back to name."""
        return self.service_type if self.service_type else self.name


@dataclass
class UTCPConfig:
    """Global UTCP configuration loaded from environment variables."""

    services: list[UTCPServiceConfig] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> 'UTCPConfig':
        """Load UTCP configuration from environment variables."""
        config = cls()
        services_str = os.getenv('UTCP_SERVICES', '')

        if not services_str:
            logger.info('UTCP_SERVICES not set, no UTCP services configured')
            return config

        service_names = [name.strip() for name in services_str.split(',') if name.strip()]

        if not service_names:
            logger.warning('UTCP_SERVICES is empty')
            return config

        logger.info(
            'Loading configuration for %d UTCP service(s): %s',
            len(service_names),
            ', '.join(service_names),
        )

        for service_name in service_names:
            service_config = cls._load_service_config(service_name)
            if service_config:
                config.services.append(service_config)
                logger.info(
                    'Loaded UTCP service config: %s (enabled=%s, dynamic=%s)',
                    service_name,
                    service_config.enabled,
                    service_config.dynamic,
                )

        return config

    @staticmethod
    def _load_service_config(service_name: str) -> UTCPServiceConfig | None:
        """Load configuration for a single UTCP service instance."""
        # Validate instance name format
        if not validate_instance_name(service_name):
            logger.error(
                "UTCP service '%s' has invalid instance name. "
                'Names must be lowercase alphanumeric with hyphens '
                "(e.g., 'kubernetes', 'kubernetes-prod'). Skipping.",
                service_name,
            )
            return None

        service_key = service_name.upper().replace('-', '_')

        # Resolve service type (e.g., 'kubernetes-prod' -> 'kubernetes')
        service_type = resolve_service_type(service_name)
        if service_type != service_name:
            logger.info(
                "UTCP service '%s' resolved to type '%s'",
                service_name,
                service_type,
            )

        # Check if enabled
        enabled_key = f'UTCP_{service_key}_ENABLED'
        enabled = os.getenv(enabled_key, 'true').lower() == 'true'

        # Get OpenAPI URL (required)
        url_key = f'UTCP_{service_key}_OPENAPI_URL'
        openapi_url = os.getenv(url_key)

        if not openapi_url:
            logger.warning(
                "UTCP service '%s' missing required %s, skipping",
                service_name,
                url_key,
            )
            return None

        # Get auth type - validate against service type (not instance name)
        auth_type_key = f'UTCP_{service_key}_AUTH_TYPE'
        auth_type = os.getenv(auth_type_key, 'proxy').lower()

        supported_auth_types = _get_supported_auth_types(service_type)
        if auth_type not in supported_auth_types:
            logger.error(
                "UTCP service '%s' (type=%s) has invalid auth type '%s' (supported: %s)",
                service_name,
                service_type,
                auth_type,
                ', '.join(supported_auth_types),
            )
            return None

        # Validate auth-specific requirements
        if (
            auth_type == 'kubeconfig' and not _validate_kubeconfig_auth(service_name, service_key)
        ) or (auth_type == 'bearer' and not _validate_bearer_auth(service_name, service_key)):
            return None

        # Get token for bearer auth (will be empty for kubeconfig)
        token_key = f'UTCP_{service_key}_TOKEN'
        token = os.getenv(token_key, '')

        # Get insecure flag (skip TLS verification)
        insecure_key = f'UTCP_{service_key}_INSECURE'
        insecure = os.getenv(insecure_key, 'false').lower() == 'true'

        # Get version (for loading the correct spec file)
        version_key = f'UTCP_{service_key}_VERSION'
        version = os.getenv(version_key, '')

        # Get dynamic flag (generate tools at runtime from OpenAPI URL)
        dynamic_key = f'UTCP_{service_key}_DYNAMIC'
        dynamic = os.getenv(dynamic_key, 'false').lower() == 'true'

        # Get approval policy: per-service overrides global, global overrides default
        global_approval_policy = os.getenv('UTCP_APPROVAL_POLICY', 'read_only').lower()
        approval_policy_key = f'UTCP_{service_key}_APPROVAL_POLICY'
        approval_policy = os.getenv(approval_policy_key, global_approval_policy).lower()

        # Validate approval policy
        valid_policies = {'never', 'always', 'read_only'}
        if approval_policy not in valid_policies:
            logger.warning(
                "UTCP service '%s' has invalid approval_policy '%s' "
                "(valid: %s), using default 'read_only'",
                service_name,
                approval_policy,
                ', '.join(valid_policies),
            )
            approval_policy = 'read_only'

        # Get spec source strategy - validate against service type
        spec_source_key = f'UTCP_{service_key}_SPEC_SOURCE'
        spec_source = os.getenv(spec_source_key, 'local').lower()

        supported_spec_sources = SERVICE_SPEC_SOURCES.get(
            service_type, SERVICE_SPEC_SOURCES['_default']
        )
        if spec_source not in supported_spec_sources:
            logger.warning(
                "UTCP service '%s' (type=%s) does not support spec_source '%s' "
                "(supported: %s), using default 'local'",
                service_name,
                service_type,
                spec_source,
                ', '.join(supported_spec_sources),
            )
            spec_source = 'local'

        return UTCPServiceConfig(
            name=service_name,
            openapi_url=openapi_url,
            service_type=service_type,
            auth_type=auth_type,
            token=token,
            insecure=insecure,
            enabled=enabled,
            version=version,
            dynamic=dynamic,
            approval_policy=approval_policy,
            spec_source=spec_source,
        )

    @property
    def enabled_services(self) -> list[UTCPServiceConfig]:
        """Get only enabled UTCP services."""
        return [s for s in self.services if s.enabled]

    def get_service(self, name: str) -> UTCPServiceConfig | None:
        """Get configuration for a specific service by name."""
        for service in self.services:
            if service.name.lower() == name.lower():
                return service
        return None
