"""UTCP (Universal Tool Calling Protocol) module for Ein Agent.

This module provides tools generated from OpenAPI specifications,
replacing the previous MCP-based approach.

Architecture:
- UTCP clients are initialized at worker startup (in worker.py)
- Clients are stored in the registry for workflows to access
- Workflows create 3 lightweight meta-tools per service:
  - search_{service}_operations: Search available API operations
  - get_{service}_operation_details: Get parameter schema for an operation
  - call_{service}_operation: Execute an API operation
- This keeps agent context small while enabling dynamic API discovery
"""

from ein_agent_worker.utcp import registry
from ein_agent_worker.utcp.aiohttp_config import AiohttpConfigManager
from ein_agent_worker.utcp.config import (
    DEFAULT_VERSIONS,
    SUPPORTED_VERSIONS,
    CephVersion,
    GrafanaVersion,
    KubernetesVersion,
    LokiVersion,
    UTCPConfig,
    UTCPServiceConfig,
)
from ein_agent_worker.utcp.loader import ToolLoader, create_utcp_tools
from ein_agent_worker.utcp.local_file_protocol import (
    LocalFileHttpProtocol,
    get_api_base_url,
    register_local_file_protocol,
    set_api_base_url,
)
from ein_agent_worker.utcp.openapi_handlers import (
    DEFAULT_OPENAPI_HANDLERS,
    BearerTokenLoader,
    DefaultOpenApiHandler,
    GrafanaOpenApiHandler,
    KubernetesOpenApiHandler,
    OpenApiHandler,
)
from ein_agent_worker.utcp.spec import (
    LiveURLStrategy,
    LocalFileStrategy,
    SpecSource,
    SpecSourceStrategy,
)
from ein_agent_worker.utcp.temporal_utcp import (
    create_utcp_workflow_tools,
    get_utcp_activities,
)

__all__ = [
    'DEFAULT_OPENAPI_HANDLERS',
    'DEFAULT_VERSIONS',
    'SUPPORTED_VERSIONS',
    'AiohttpConfigManager',
    'BearerTokenLoader',
    'CephVersion',
    'DefaultOpenApiHandler',
    'GrafanaOpenApiHandler',
    'GrafanaVersion',
    'KubernetesOpenApiHandler',
    'KubernetesVersion',
    'LiveURLStrategy',
    'LocalFileHttpProtocol',
    'LocalFileStrategy',
    'LokiVersion',
    'OpenApiHandler',
    'SpecSource',
    'SpecSourceStrategy',
    'ToolLoader',
    'UTCPConfig',
    'UTCPServiceConfig',
    'create_utcp_tools',
    'create_utcp_workflow_tools',
    'get_api_base_url',
    'get_utcp_activities',
    'register_local_file_protocol',
    'registry',
    'set_api_base_url',
]
