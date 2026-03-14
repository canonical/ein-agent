"""OpenAPI handlers for UTCP services.

Each handler encapsulates service-specific logic for authentication
and OpenAPI spec preprocessing. To add a new service, create a new handler
class and register it in DEFAULT_OPENAPI_HANDLERS.
"""

from ein_agent_worker.utcp.openapi_handlers.base import BearerTokenLoader, OpenApiHandler
from ein_agent_worker.utcp.openapi_handlers.default import DefaultOpenApiHandler
from ein_agent_worker.utcp.openapi_handlers.grafana import GrafanaOpenApiHandler
from ein_agent_worker.utcp.openapi_handlers.kubernetes import KubernetesOpenApiHandler

# Registry of OpenAPI handlers keyed by service name.
# Services not in this registry will use DefaultOpenApiHandler.
DEFAULT_OPENAPI_HANDLERS: dict[str, OpenApiHandler] = {
    'kubernetes': KubernetesOpenApiHandler(),
    'grafana': GrafanaOpenApiHandler(),
}

__all__ = [
    'DEFAULT_OPENAPI_HANDLERS',
    'BearerTokenLoader',
    'DefaultOpenApiHandler',
    'GrafanaOpenApiHandler',
    'KubernetesOpenApiHandler',
    'OpenApiHandler',
]
