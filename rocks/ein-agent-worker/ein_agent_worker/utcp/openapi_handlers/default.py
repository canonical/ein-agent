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
        """Pass spec through without modification."""
        return spec_data

    def get_api_key_pattern(self) -> str:
        """Return generic API key pattern based on service name."""
        return rf"{self._service_name}_API_KEY_\d+"
