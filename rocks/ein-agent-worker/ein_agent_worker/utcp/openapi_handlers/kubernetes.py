"""Kubernetes OpenAPI handler."""

import logging
from typing import Optional

from utcp.data.variable_loader import VariableLoader

from ein_agent_worker.utcp.openapi_handlers.base import BearerTokenLoader, OpenApiHandler

logger = logging.getLogger(__name__)


class KubernetesOpenApiHandler(OpenApiHandler):
    """Handler for Kubernetes API service.

    Kubernetes only supports kubeconfig-based authentication for long-term
    credential management. Supported auth types are defined in config.SERVICE_AUTH_TYPES.
    """

    def get_variable_loader(self, token: str) -> Optional[VariableLoader]:
        """Create a bearer token loader for Kubernetes API key variables.

        Note: Token is extracted from kubeconfig by the loader, then used
        for API authentication via the BearerTokenLoader.
        """
        return BearerTokenLoader(
            token=token,
            patterns=[
                r"k8s_API_KEY_\d+",
                r"kubernetes_API_KEY_\d+",
            ],
        )

    def preprocess_spec(self, spec_data: dict, service_name: str) -> dict:
        """Pass spec through without modification."""
        return spec_data

    def get_api_key_pattern(self) -> str:
        """Return Kubernetes API key patterns."""
        return r"(k8s|kubernetes)_API_KEY_\d+"
