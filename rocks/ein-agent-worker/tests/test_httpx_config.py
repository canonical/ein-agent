import httpx
import pytest
from httpx._utils import URLPattern

from ein_agent_worker.http.httpx_config import HttpxConfigManager, _matches_with_cidr


@pytest.fixture(autouse=True)
def _enable_httpx_cidr():
    """Ensure httpx CIDR patch is applied for all tests."""
    HttpxConfigManager.enable_cidr_no_proxy()


class TestMatchesWithCidr:
    """Tests for CIDR-aware URLPattern.matches."""

    def test_cidr_match_10_network(self):
        pattern = URLPattern('all://10.0.0.0/8')
        assert pattern.matches(httpx.URL('http://10.42.0.5:9090/'))
        assert pattern.matches(httpx.URL('http://10.0.0.1/'))
        assert pattern.matches(httpx.URL('http://10.255.255.255/'))
        assert pattern.matches(httpx.URL('https://10.1.2.3:443/'))

    def test_cidr_no_match_outside_range(self):
        pattern = URLPattern('all://10.0.0.0/8')
        assert not pattern.matches(httpx.URL('http://11.0.0.1/'))
        assert not pattern.matches(httpx.URL('http://172.16.0.1/'))
        assert not pattern.matches(httpx.URL('http://8.8.8.8/'))

    def test_cidr_192_168_range(self):
        pattern = URLPattern('all://192.168.0.0/16')
        assert pattern.matches(httpx.URL('http://192.168.1.100/'))
        assert pattern.matches(httpx.URL('http://192.168.255.255/'))
        assert not pattern.matches(httpx.URL('http://192.169.0.1/'))

    def test_cidr_172_16_range(self):
        pattern = URLPattern('all://172.16.0.0/12')
        assert pattern.matches(httpx.URL('http://172.16.0.1/'))
        assert pattern.matches(httpx.URL('http://172.31.255.255/'))
        assert not pattern.matches(httpx.URL('http://172.32.0.1/'))

    def test_non_cidr_pattern_falls_through(self):
        # Normal patterns should still work via original matches
        pattern = URLPattern('https://')
        assert pattern.matches(httpx.URL('https://example.com/'))
        assert not pattern.matches(httpx.URL('http://example.com/'))

    def test_exact_host_pattern(self):
        pattern = URLPattern('all://example.com')
        assert pattern.matches(httpx.URL('http://example.com/'))
        assert not pattern.matches(httpx.URL('http://other.com/'))

    def test_cidr_with_hostname_no_match(self):
        # Hostnames (not IPs) should not match CIDR patterns
        pattern = URLPattern('all://10.0.0.0/8')
        assert not pattern.matches(httpx.URL('http://example.com/'))

    def test_cidr_ipv6_not_supported(self):
        # httpx can't parse IPv6 CIDR as URL patterns (colons conflict with port)
        # This is a known httpx limitation — verify it raises rather than silently failing
        with pytest.raises(httpx.InvalidURL):
            URLPattern('all://fd00::/8')


class TestHttpxConfigManager:
    """Tests for HttpxConfigManager."""

    def test_patch_applied(self):
        assert URLPattern.matches is _matches_with_cidr

    def test_idempotent(self):
        HttpxConfigManager.enable_cidr_no_proxy()
        HttpxConfigManager.enable_cidr_no_proxy()
        assert URLPattern.matches is _matches_with_cidr
