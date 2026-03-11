"""Base class for OpenAPI service handlers.

OpenAPI handlers encapsulate service-specific customization points for
UTCP services, including authentication variable loading and OpenAPI
spec preprocessing before conversion to UTCP manuals.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from utcp.data.variable_loader import VariableLoader

logger = logging.getLogger(__name__)


class BearerTokenLoader(VariableLoader):
    """Generic variable loader that provides bearer tokens for API key variables.

    Matches API key variable names against configurable regex patterns and
    returns the bearer token for matching variables. This replaces the need
    for service-specific loader classes.
    """

    variable_loader_type: str = "bearer"
    token: str
    patterns: list[str]

    def __init__(self, token: str, patterns: list[str], **kwargs):
        super().__init__(token=token, patterns=patterns, **kwargs)

    def get(self, key: str) -> Optional[str]:
        """Return bearer token if key matches any configured pattern."""
        for pattern in self.patterns:
            if re.match(pattern, key):
                return f"Bearer {self.token}"
        return None


class OpenApiHandler(ABC):
    """Base class for service-specific OpenAPI handlers.

    Subclass this to add custom behavior for a UTCP service, such as
    special authentication or OpenAPI spec preprocessing before conversion.

    Note: Supported auth types are defined in config.SERVICE_AUTH_TYPES to avoid
    circular imports between config.py and handlers.
    """

    @abstractmethod
    def get_variable_loader(self, token: str) -> Optional[VariableLoader]:
        """Create a variable loader for bearer token authentication.

        Args:
            token: The bearer token to use for authentication.

        Returns:
            A VariableLoader instance, or None if no loader is needed.
        """

    @abstractmethod
    def preprocess_spec(self, spec_data: dict, service_name: str) -> dict:
        """Preprocess OpenAPI spec before conversion to UTCP manual.

        This is called during local file loading to apply service-specific
        transformations to the spec data.

        Args:
            spec_data: The parsed OpenAPI spec dictionary.
            service_name: The service name.

        Returns:
            The (possibly modified) spec data dictionary.
        """

    @abstractmethod
    def get_api_key_pattern(self) -> str:
        """Return regex pattern for API key variable matching.

        Returns:
            A regex pattern string that matches API key variable names
            for this service (e.g., r"kubernetes_API_KEY_\\d+").
        """
