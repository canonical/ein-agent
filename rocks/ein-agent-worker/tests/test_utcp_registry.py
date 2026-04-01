"""Tests for UTCP client registry: list_services_by_type."""

import pytest

from ein_agent_worker.utcp import registry as utcp_registry
from ein_agent_worker.utcp.config import UTCPServiceConfig


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global registry before and after each test."""
    utcp_registry.clear()
    yield
    utcp_registry.clear()


class TestListServicesByType:
    def test_filter_by_type(self):
        utcp_registry.register_client(
            'kubernetes-prod',
            object(),  # dummy client
            UTCPServiceConfig(
                name='kubernetes-prod',
                openapi_url='http://prod',
                service_type='kubernetes',
            ),
        )
        utcp_registry.register_client(
            'kubernetes-staging',
            object(),
            UTCPServiceConfig(
                name='kubernetes-staging',
                openapi_url='http://staging',
                service_type='kubernetes',
            ),
        )
        utcp_registry.register_client(
            'grafana',
            object(),
            UTCPServiceConfig(
                name='grafana',
                openapi_url='http://grafana',
                service_type='grafana',
            ),
        )

        result = utcp_registry.list_services_by_type('kubernetes')
        assert sorted(result) == ['kubernetes-prod', 'kubernetes-staging']

    def test_empty_registry(self):
        assert utcp_registry.list_services_by_type('kubernetes') == []

    def test_no_matching_type(self):
        utcp_registry.register_client(
            'grafana',
            object(),
            UTCPServiceConfig(
                name='grafana',
                openapi_url='http://grafana',
                service_type='grafana',
            ),
        )
        assert utcp_registry.list_services_by_type('kubernetes') == []
