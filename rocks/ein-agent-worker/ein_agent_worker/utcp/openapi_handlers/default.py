"""Default OpenAPI handler for services without custom logic."""

import logging
from typing import Optional

from utcp.data.variable_loader import VariableLoader

from ein_agent_worker.utcp.openapi_handlers.base import BearerTokenLoader, OpenApiHandler

logger = logging.getLogger(__name__)


class DefaultOpenApiHandler(OpenApiHandler):
    """Default handler for services without custom requirements.

    Provides a generic bearer token loader based on service name and
    passes specs through without modification.
    Supported auth types are defined in config.SERVICE_AUTH_TYPES.
    """

    def __init__(self, service_name: str = ""):
        self._service_name = service_name

    def get_variable_loader(self, token: str) -> Optional[VariableLoader]:
        """Create a generic bearer token loader for the service."""
        if not self._service_name:
            return None
        pattern = rf"{self._service_name}_API_KEY_\d+"
        return BearerTokenLoader(token=token, patterns=[pattern])

    def preprocess_spec(self, spec_data: dict, service_name: str) -> dict:
        """Filter to read-only operations for security."""
        return self.filter_readonly_operations(spec_data, service_name)

    def get_api_key_pattern(self) -> str:
        """Return generic API key pattern based on service name."""
        return rf"{self._service_name}_API_KEY_\d+"

    def resolve_server_url(self, spec_data: dict, api_base_url: str, service_name: str) -> str:
        """Resolve server URL for generic services.

        Handles both Swagger 2.0 (basePath) and OpenAPI 3.x (servers with
        relative URLs) specs.
        """
        # Swagger 2.0: basePath
        if 'basePath' in spec_data:
            resolved = f"{api_base_url.rstrip('/')}{spec_data['basePath']}"
            logger.info(
                f"[{service_name}] Resolved server URL: {resolved} (api_base_url + basePath)"
            )
            return resolved

        # OpenAPI 3.x: relative servers[0].url
        if 'servers' in spec_data and spec_data['servers']:
            original_server_url = spec_data['servers'][0].get('url', '')
            if original_server_url and not original_server_url.startswith('http'):
                resolved = f"{api_base_url.rstrip('/')}{original_server_url}"
                logger.info(
                    f"[{service_name}] Resolved server URL: {resolved} (api_base_url + servers[0].url)"
                )
                return resolved

        logger.info(f"[{service_name}] Resolved server URL: {api_base_url}")
        return api_base_url
