"""Extended HTTP protocol that supports file:// URLs for local spec files.

UTCP's default HTTP protocol only allows HTTPS or localhost URLs for security.
This extended protocol adds support for file:// URLs, enabling loading of
OpenAPI specs from local files for offline development and testing.

Additionally, this protocol applies security preprocessing (read-only filtering)
to ALL specs (both file:// and https://) via OpenAPI handlers.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import yaml
from utcp_http.http_call_template import HttpCallTemplate
from utcp_http.http_communication_protocol import HttpCommunicationProtocol
from utcp_http.openapi_converter import OpenApiConverter

from ein_agent_worker.http.proxy import proxy_for_url
from ein_agent_worker.utcp.openapi_handlers import DEFAULT_OPENAPI_HANDLERS, OpenApiHandler
from ein_agent_worker.utcp.openapi_handlers.default import DefaultOpenApiHandler
from utcp.data.call_template import CallTemplate
from utcp.data.register_manual_response import RegisterManualResult
from utcp.data.utcp_manual import UtcpManual, UtcpManualSerializer

if TYPE_CHECKING:
    from utcp.utcp_client import UtcpClient

logger = logging.getLogger(__name__)

# Track if protocol has been registered
_protocol_registered = False

# Registry for API base URLs when using local spec files
# Maps service_name -> actual API endpoint URL
_api_base_urls: dict[str, str] = {}

# Registry for service types (instance_name -> service_type)
# Used for handler lookup when instance name differs from service type
_service_types: dict[str, str] = {}


def set_api_base_url(service_name: str, url: str) -> None:
    """Register the API base URL for a service.

    When loading specs from local files, we need to know the real API
    endpoint URL for making actual API calls.

    Args:
        service_name: The service name (e.g., 'kubernetes', 'grafana')
        url: The actual API endpoint URL (e.g., 'https://10.x.x.x:6443')
    """
    _api_base_urls[service_name] = url
    logger.debug('Registered API base URL for %s: %s', service_name, url)


def get_api_base_url(service_name: str) -> str | None:
    """Get the registered API base URL for a service.

    Args:
        service_name: The service name

    Returns:
        The API base URL if registered, None otherwise
    """
    return _api_base_urls.get(service_name)


def set_service_type(service_name: str, service_type: str) -> None:
    """Register the service type for an instance name.

    Used for OpenAPI handler lookup when instance name differs from type
    (e.g., 'kubernetes-prod' -> 'kubernetes').

    Args:
        service_name: The instance name (e.g., 'kubernetes-prod')
        service_type: The service type (e.g., 'kubernetes')
    """
    _service_types[service_name] = service_type
    logger.debug('Registered service type for %s: %s', service_name, service_type)


def get_service_type(service_name: str) -> str:
    """Get the registered service type for an instance name.

    Args:
        service_name: The instance name

    Returns:
        The service type if registered, otherwise the service_name itself
    """
    return _service_types.get(service_name, service_name)


class LocalFileHttpProtocol(HttpCommunicationProtocol):
    """HTTP protocol extended to support file:// URLs for local OpenAPI specs.

    For file:// URLs, reads the spec directly from disk instead of HTTP fetch.
    For all other URLs, delegates to the parent HttpCommunicationProtocol.

    This allows using local OpenAPI spec files during development without
    requiring a live API server, while still supporting live URLs in production.
    """

    def __init__(
        self,
        openapi_handlers: dict[str, OpenApiHandler] | None = None,
    ):
        super().__init__()
        self.openapi_handlers = openapi_handlers or DEFAULT_OPENAPI_HANDLERS

    async def register_manual(
        self, caller: 'UtcpClient', manual_call_template: CallTemplate
    ) -> RegisterManualResult:
        """Register a manual, supporting both HTTP and file:// URLs.

        For all URLs, applies security preprocessing (read-only filtering) via handlers.

        Args:
            caller: The UTCP client that is calling this method.
            manual_call_template: The call template of the manual to register.

        Returns:
            RegisterManualResult object containing the call template and manual.
        """
        if not isinstance(manual_call_template, HttpCallTemplate):
            raise ValueError('LocalFileHttpProtocol can only be used with HttpCallTemplate')

        url = manual_call_template.url

        # Handle file:// URLs by reading directly from disk
        if url.startswith('file://'):
            return await self._register_from_file(manual_call_template, url)

        # Handle HTTP/HTTPS URLs with preprocessing
        return await self._register_from_http(caller, manual_call_template, url)

    async def _register_from_file(
        self, manual_call_template: HttpCallTemplate, file_url: str
    ) -> RegisterManualResult:
        """Load OpenAPI spec from a local file.

        Args:
            manual_call_template: The call template containing configuration.
            file_url: The file:// URL pointing to the spec file.

        Returns:
            RegisterManualResult with the loaded manual or error details.
        """
        try:
            # Convert file:// URL to path
            file_path = Path(file_url.replace('file://', ''))

            if not file_path.exists():
                error_msg = f'Spec file not found: {file_path}'
                logger.error(error_msg)
                return RegisterManualResult(
                    success=False,
                    manual_call_template=manual_call_template,
                    manual=UtcpManual(manual_version='0.0.0', tools=[]),
                    errors=[error_msg],
                )

            logger.info('Loading OpenAPI spec from local file: %s', file_path)

            # Read and parse the file
            content = file_path.read_text()

            if file_path.suffix in ['.yaml', '.yml']:
                spec_data = yaml.safe_load(content)
            else:
                spec_data = json.loads(content)

            # Check if UTCP manual or OpenAPI spec
            if 'utcp_version' in spec_data and 'tools' in spec_data:
                logger.info(
                    "Detected UTCP manual from '%s'",
                    manual_call_template.name,
                )
                utcp_manual = UtcpManualSerializer().validate_dict(spec_data)
            else:
                # Convert OpenAPI spec to UTCP manual
                service_name = manual_call_template.name
                api_base_url = get_api_base_url(service_name)

                # Apply service-specific preprocessing via handler
                # Look up handler by service type first, then instance name
                svc_type = get_service_type(service_name)
                handler = self.openapi_handlers.get(
                    svc_type,
                    self.openapi_handlers.get(service_name, DefaultOpenApiHandler(service_name)),
                )
                spec_data = handler.preprocess_spec(spec_data, service_name)

                # Construct the full base URL for API operations
                # OpenApiConverter uses spec_url as the base for all API calls
                spec_url_param = None

                if api_base_url:
                    parsed = urlparse(api_base_url)

                    # Delegate URL resolution to the handler
                    resolved_url = handler.resolve_server_url(
                        spec_data, api_base_url, service_name
                    )
                    spec_data['servers'] = [{'url': resolved_url}]

                    # Set host and scheme for fallback
                    spec_data['host'] = parsed.netloc
                    spec_data['schemes'] = [parsed.scheme]

                    # Use scheme://host as spec_url
                    spec_url_param = f'{parsed.scheme}://{parsed.netloc}'
                    logger.info(
                        '[%s] Set spec: host=%s, scheme=%s, spec_url=%s',
                        service_name,
                        parsed.netloc,
                        parsed.scheme,
                        spec_url_param,
                    )
                else:
                    # No configured API base URL, fall back to spec file URL
                    spec_url_param = manual_call_template.url
                    logger.warning(
                        '[%s] No API base URL configured, falling back to spec URL: %s',
                        service_name,
                        spec_url_param,
                    )

                logger.info(
                    '[%s] Converting OpenAPI spec to UTCP manual with base URL: %s',
                    service_name,
                    spec_url_param,
                )
                converter = OpenApiConverter(
                    spec_data,
                    spec_url=spec_url_param,
                    call_template_name=manual_call_template.name,
                    auth_tools=manual_call_template.auth_tools,
                )
                utcp_manual = converter.convert()

            return RegisterManualResult(
                success=True,
                manual_call_template=manual_call_template,
                manual=utcp_manual,
                errors=[],
            )

        except (json.JSONDecodeError, yaml.YAMLError) as e:
            error_msg = f'Error parsing spec file: {e}'
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version='0.0.0', tools=[]),
                errors=[error_msg],
            )
        except Exception as e:
            error_msg = f'Error loading spec from file: {e}'
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version='0.0.0', tools=[]),
                errors=[error_msg],
            )

    async def _register_from_http(
        self,
        caller: 'UtcpClient',
        manual_call_template: HttpCallTemplate,
        http_url: str,
    ) -> RegisterManualResult:
        """Load OpenAPI spec from HTTP/HTTPS URL with preprocessing.

        Fetches the spec from a live URL and applies security preprocessing
        (read-only filtering) before converting to UTCP manual.

        Args:
            caller: The UTCP client making the request.
            manual_call_template: The call template containing configuration.
            http_url: The HTTP/HTTPS URL pointing to the spec.

        Returns:
            RegisterManualResult with the loaded manual or error details.
        """
        try:
            service_name = manual_call_template.name
            logger.info(
                '[%s] Loading OpenAPI spec from LIVE URL: %s',
                service_name,
                http_url,
            )

            # Extract auth headers from call template for spec fetching
            # (e.g., Kubernetes API requires auth even for /openapi/v2)
            headers: dict[str, str] = {}
            auth = manual_call_template.auth
            if auth and auth.auth_type == 'api_key' and auth.location == 'header':
                headers[auth.var_name] = auth.api_key
                logger.info(
                    '[%s] Using %s header for spec fetch',
                    service_name,
                    auth.var_name,
                )

            # Fetch spec from URL using httpx
            async with httpx.AsyncClient(
                verify=False,  # noqa: S501
                proxy=proxy_for_url(http_url),
                trust_env=False,
            ) as client:
                response = await client.get(http_url, headers=headers)
                response.raise_for_status()

                # Parse response
                content_type = response.headers.get('content-type', '')
                if 'yaml' in content_type or http_url.endswith(('.yaml', '.yml')):
                    spec_data = yaml.safe_load(response.text)
                else:
                    spec_data = response.json()

            # Apply service-specific preprocessing via handler
            # Look up handler by service type first, then instance name
            svc_type = get_service_type(service_name)
            handler = self.openapi_handlers.get(
                svc_type,
                self.openapi_handlers.get(service_name, DefaultOpenApiHandler(service_name)),
            )
            spec_data = handler.preprocess_spec(spec_data, service_name)

            # Convert OpenAPI spec to UTCP manual
            logger.info(
                '[%s] Converting OpenAPI spec to UTCP manual (from live URL)',
                service_name,
            )
            converter = OpenApiConverter(
                spec_data,
                spec_url=http_url,
                call_template_name=manual_call_template.name,
                auth_tools=manual_call_template.auth_tools,
            )
            utcp_manual = converter.convert()

            return RegisterManualResult(
                success=True,
                manual_call_template=manual_call_template,
                manual=utcp_manual,
                errors=[],
            )

        except httpx.HTTPStatusError as e:
            error_msg = f'HTTP error fetching spec from {http_url}: {e.response.status_code}'
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version='0.0.0', tools=[]),
                errors=[error_msg],
            )
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            error_msg = f'Error parsing spec from {http_url}: {e}'
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version='0.0.0', tools=[]),
                errors=[error_msg],
            )
        except Exception as e:
            error_msg = f'Error loading spec from {http_url}: {e}'
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version='0.0.0', tools=[]),
                errors=[error_msg],
            )


def register_local_file_protocol() -> None:
    """Register the LocalFileHttpProtocol to handle file:// URLs.

    This replaces the default HTTP protocol with our extended version that
    supports both file:// URLs and standard HTTP/HTTPS URLs.

    Safe to call multiple times - only registers once.
    """
    global _protocol_registered
    if _protocol_registered:
        return

    from utcp.plugins.discovery import register_communication_protocol

    protocol = LocalFileHttpProtocol()
    registered = register_communication_protocol('http', protocol, override=True)

    if registered:
        logger.info('Registered LocalFileHttpProtocol for file:// URL support')
    else:
        logger.warning('Failed to register LocalFileHttpProtocol')

    _protocol_registered = True
