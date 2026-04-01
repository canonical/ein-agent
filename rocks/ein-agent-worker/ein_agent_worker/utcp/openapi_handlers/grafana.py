"""Grafana OpenAPI handler."""

import logging

from ein_agent_worker.utcp.openapi_handlers.base import (
    BearerTokenLoader,
    OpenApiHandler,
    utcp_namespace_prefix,
)
from utcp.data.variable_loader import VariableLoader

logger = logging.getLogger(__name__)


class GrafanaOpenApiHandler(OpenApiHandler):
    """Handler for Grafana API service.

    Handles 'grafana_API_KEY_*' variable pattern for bearer token
    authentication and preprocesses OpenAPI specs to force token-based
    auth (removing basic auth).
    Grafana uses service account tokens.
    Supported auth types are defined in config.SERVICE_AUTH_TYPES.
    """

    def get_variable_loader(self, token: str, instance_name: str = '') -> VariableLoader | None:
        """Create a bearer token loader for Grafana API key variables."""
        if instance_name:
            prefix = utcp_namespace_prefix(instance_name)
            patterns = [rf'{prefix}_API_KEY_\d+']
        else:
            patterns = [r'grafana_API_KEY_\d+']
        return BearerTokenLoader(token=token, patterns=patterns)

    def preprocess_spec(self, spec_data: dict, service_name: str) -> dict:
        """Force api_key security, remove basic auth, and filter to read-only.

        We use service account tokens, not username/password, so basic auth
        definitions are removed from the spec. Then filter to only GET operations
        for security.
        """
        if 'security' in spec_data:
            spec_data['security'] = [{'api_key': []}]
            logger.info(
                '[%s] Forcing api_key security (token-based auth)',
                service_name,
            )

        if 'securityDefinitions' in spec_data and 'basic' in spec_data['securityDefinitions']:
            del spec_data['securityDefinitions']['basic']
            logger.info(
                '[%s] Removed basic auth from security definitions',
                service_name,
            )

        # Filter to read-only operations
        return self.filter_readonly_operations(spec_data, service_name)

    def get_api_key_pattern(self) -> str:
        """Return Grafana API key pattern."""
        return r'grafana_API_KEY_\d+'

    def resolve_server_url(self, spec_data: dict, api_base_url: str, service_name: str) -> str:
        """Grafana Swagger 2.0 spec has basePath=/api -- combine with api_base_url."""
        base_path = spec_data.get('basePath', '')
        if base_path:
            resolved = f'{api_base_url.rstrip("/")}{base_path}'
            logger.info(
                '[%s] Resolved server URL: %s (api_base_url + basePath)',
                service_name,
                resolved,
            )
            return resolved
        logger.info('[%s] Resolved server URL: %s', service_name, api_base_url)
        return api_base_url
