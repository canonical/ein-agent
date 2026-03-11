"""Grafana OpenAPI handler."""

import logging
from typing import Optional

from utcp.data.variable_loader import VariableLoader

from ein_agent_worker.utcp.openapi_handlers.base import BearerTokenLoader, OpenApiHandler

logger = logging.getLogger(__name__)


class GrafanaOpenApiHandler(OpenApiHandler):
    """Handler for Grafana API service.

    Handles 'grafana_API_KEY_*' variable pattern for bearer token authentication
    and preprocesses OpenAPI specs to force token-based auth (removing basic auth).
    Grafana uses service account tokens. Supported auth types are defined in config.SERVICE_AUTH_TYPES.
    """

    def get_variable_loader(self, token: str) -> Optional[VariableLoader]:
        """Create a bearer token loader for Grafana API key variables."""
        return BearerTokenLoader(
            token=token,
            patterns=[r"grafana_API_KEY_\d+"],
        )

    def preprocess_spec(self, spec_data: dict, service_name: str) -> dict:
        """Force api_key security and remove basic auth from Grafana specs.

        We use service account tokens, not username/password, so basic auth
        definitions are removed from the spec.
        """
        if "security" in spec_data:
            spec_data["security"] = [{"api_key": []}]
            logger.info(f"[{service_name}] Forcing api_key security (token-based auth)")

        if "securityDefinitions" in spec_data and "basic" in spec_data["securityDefinitions"]:
            del spec_data["securityDefinitions"]["basic"]
            logger.info(f"[{service_name}] Removed basic auth from security definitions")

        return spec_data

    def get_api_key_pattern(self) -> str:
        """Return Grafana API key pattern."""
        return r"grafana_API_KEY_\d+"
