"""Extended HTTP protocol that supports file:// URLs for local spec files.

UTCP's default HTTP protocol only allows HTTPS or localhost URLs for security.
This extended protocol adds support for file:// URLs, enabling loading of
OpenAPI specs from local files for offline development and testing.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from utcp.data.call_template import CallTemplate
from utcp.data.register_manual_response import RegisterManualResult
from utcp.data.utcp_manual import UtcpManual, UtcpManualSerializer
from utcp_http.http_call_template import HttpCallTemplate
from utcp_http.http_communication_protocol import HttpCommunicationProtocol
from utcp_http.openapi_converter import OpenApiConverter

if TYPE_CHECKING:
    from utcp.utcp_client import UtcpClient

logger = logging.getLogger(__name__)

# Track if protocol has been registered
_protocol_registered = False

# Registry for API base URLs when using local spec files
# Maps service_name -> actual API endpoint URL
_api_base_urls: dict[str, str] = {}


def set_api_base_url(service_name: str, url: str) -> None:
    """Register the API base URL for a service.

    When loading specs from local files, we need to know the real API
    endpoint URL for making actual API calls.

    Args:
        service_name: The service name (e.g., 'kubernetes', 'grafana')
        url: The actual API endpoint URL (e.g., 'https://10.x.x.x:6443')
    """
    _api_base_urls[service_name] = url
    logger.debug(f"Registered API base URL for {service_name}: {url}")


def get_api_base_url(service_name: str) -> str | None:
    """Get the registered API base URL for a service.

    Args:
        service_name: The service name

    Returns:
        The API base URL if registered, None otherwise
    """
    return _api_base_urls.get(service_name)


class LocalFileHttpProtocol(HttpCommunicationProtocol):
    """HTTP protocol extended to support file:// URLs for local OpenAPI specs.

    For file:// URLs, reads the spec directly from disk instead of HTTP fetch.
    For all other URLs, delegates to the parent HttpCommunicationProtocol.

    This allows using local OpenAPI spec files during development without
    requiring a live API server, while still supporting live URLs in production.
    """

    async def register_manual(
        self, caller: "UtcpClient", manual_call_template: CallTemplate
    ) -> RegisterManualResult:
        """Register a manual, supporting both HTTP and file:// URLs.

        Args:
            caller: The UTCP client that is calling this method.
            manual_call_template: The call template of the manual to register.

        Returns:
            RegisterManualResult object containing the call template and manual.
        """
        if not isinstance(manual_call_template, HttpCallTemplate):
            raise ValueError(
                "LocalFileHttpProtocol can only be used with HttpCallTemplate"
            )

        url = manual_call_template.url

        # Handle file:// URLs by reading directly from disk
        if url.startswith("file://"):
            return await self._register_from_file(manual_call_template, url)

        # Delegate to parent for HTTP/HTTPS URLs
        return await super().register_manual(caller, manual_call_template)

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
            file_path = Path(file_url.replace("file://", ""))

            if not file_path.exists():
                error_msg = f"Spec file not found: {file_path}"
                logger.error(error_msg)
                return RegisterManualResult(
                    success=False,
                    manual_call_template=manual_call_template,
                    manual=UtcpManual(manual_version="0.0.0", tools=[]),
                    errors=[error_msg],
                )

            logger.info(f"Loading OpenAPI spec from local file: {file_path}")

            # Read and parse the file
            content = file_path.read_text()

            if file_path.suffix in [".yaml", ".yml"]:
                spec_data = yaml.safe_load(content)
            else:
                spec_data = json.loads(content)

            # Check if UTCP manual or OpenAPI spec
            if "utcp_version" in spec_data and "tools" in spec_data:
                logger.info(f"Detected UTCP manual from '{manual_call_template.name}'")
                utcp_manual = UtcpManualSerializer().validate_dict(spec_data)
            else:
                # Use the registered API base URL instead of the file:// URL
                # This ensures API calls go to the real endpoint, not the local file
                service_name = manual_call_template.name
                api_base_url = get_api_base_url(service_name)

                if api_base_url:
                    logger.info(
                        f"Using API base URL for '{service_name}': {api_base_url}"
                    )
                else:
                    logger.warning(
                        f"No API base URL registered for '{service_name}', "
                        f"API calls may fail"
                    )
                    api_base_url = manual_call_template.url

                logger.info(
                    f"Converting OpenAPI spec to UTCP manual for '{service_name}'"
                )
                converter = OpenApiConverter(
                    spec_data,
                    spec_url=api_base_url,
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
            error_msg = f"Error parsing spec file: {e}"
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version="0.0.0", tools=[]),
                errors=[error_msg],
            )
        except Exception as e:
            error_msg = f"Error loading spec from file: {e}"
            logger.error(error_msg)
            return RegisterManualResult(
                success=False,
                manual_call_template=manual_call_template,
                manual=UtcpManual(manual_version="0.0.0", tools=[]),
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
    registered = register_communication_protocol("http", protocol, override=True)

    if registered:
        logger.info("Registered LocalFileHttpProtocol for file:// URL support")
    else:
        logger.warning("Failed to register LocalFileHttpProtocol")

    _protocol_registered = True
