import os
from unittest.mock import patch

from ein_agent_worker.http.proxy import proxy_for_url, should_bypass_proxy


class TestShouldBypassProxy:
    """Tests for CIDR-aware should_bypass_proxy."""

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,192.168.0.0/16'})
    def test_cidr_ipv4_match(self):
        assert should_bypass_proxy('10.42.0.5') is True
        assert should_bypass_proxy('10.0.0.1') is True
        assert should_bypass_proxy('10.142.166.251') is True
        assert should_bypass_proxy('10.255.255.255') is True
        assert should_bypass_proxy('192.168.1.100') is True

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,192.168.0.0/16'})
    def test_cidr_ipv4_no_match(self):
        assert should_bypass_proxy('172.16.0.1') is False
        assert should_bypass_proxy('8.8.8.8') is False
        assert should_bypass_proxy('11.0.0.1') is False

    @patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost'})
    def test_exact_ip_match(self):
        assert should_bypass_proxy('127.0.0.1') is True
        assert should_bypass_proxy('127.0.0.2') is False

    @patch.dict(os.environ, {'NO_PROXY': '*'})
    def test_wildcard_bypasses_all(self):
        assert should_bypass_proxy('10.0.0.1') is True
        assert should_bypass_proxy('8.8.8.8') is True
        assert should_bypass_proxy('example.com') is True

    @patch.dict(os.environ, {}, clear=False)
    def test_no_proxy_empty(self):
        os.environ.pop('NO_PROXY', None)
        os.environ.pop('no_proxy', None)
        assert should_bypass_proxy('10.0.0.1') is False

    @patch.dict(os.environ, {'no_proxy': '10.0.0.0/8'})
    def test_lowercase_no_proxy(self):
        os.environ.pop('NO_PROXY', None)
        assert should_bypass_proxy('10.1.2.3') is True

    @patch.dict(os.environ, {'NO_PROXY': '.svc.cluster.local,.canonical.com'})
    def test_domain_suffix_match(self):
        assert should_bypass_proxy('kubernetes.default.svc.cluster.local') is True
        assert should_bypass_proxy('svc.cluster.local') is True
        assert should_bypass_proxy('foo.canonical.com') is True
        assert should_bypass_proxy('canonical.com') is True
        assert should_bypass_proxy('example.com') is False

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8, 192.168.0.0/16 , 127.0.0.1'})
    def test_whitespace_in_entries(self):
        assert should_bypass_proxy('10.1.1.1') is True
        assert should_bypass_proxy('192.168.1.1') is True
        assert should_bypass_proxy('127.0.0.1') is True

    @patch.dict(os.environ, {'NO_PROXY': '10.0.0.0/8,,,,192.168.0.0/16'})
    def test_empty_entries_ignored(self):
        assert should_bypass_proxy('10.1.1.1') is True
        assert should_bypass_proxy('192.168.1.1') is True

    @patch.dict(os.environ, {'NO_PROXY': 'invalid-cidr/99,10.0.0.0/8'})
    def test_invalid_cidr_skipped(self):
        assert should_bypass_proxy('10.1.1.1') is True

    @patch.dict(os.environ, {'NO_PROXY': 'fd00::/8'})
    def test_ipv6_cidr(self):
        assert should_bypass_proxy('fd00::1') is True
        assert should_bypass_proxy('fe80::1') is False


class TestProxyForUrl:
    """Tests for proxy_for_url."""

    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'HTTPS_PROXY': 'http://squid:3128',
            'NO_PROXY': '10.0.0.0/8,192.168.0.0/16',
        },
    )
    def test_bypassed_returns_none(self):
        assert proxy_for_url('http://10.142.166.251/api/v2/alerts') is None
        assert proxy_for_url('http://192.168.1.1:9090/metrics') is None

    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'HTTPS_PROXY': 'http://squid:3128',
            'NO_PROXY': '10.0.0.0/8',
        },
    )
    def test_not_bypassed_returns_proxy(self):
        assert proxy_for_url('http://8.8.8.8/') == 'http://squid:3128'

    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'HTTPS_PROXY': 'https://squid:3129',
            'NO_PROXY': '',
        },
    )
    def test_scheme_selects_correct_proxy(self):
        assert proxy_for_url('http://example.com/') == 'http://squid:3128'
        assert proxy_for_url('https://example.com/') == 'https://squid:3129'

    @patch.dict(os.environ, {}, clear=False)
    def test_no_proxy_env_returns_none(self):
        os.environ.pop('HTTP_PROXY', None)
        os.environ.pop('http_proxy', None)
        os.environ.pop('NO_PROXY', None)
        os.environ.pop('no_proxy', None)
        assert proxy_for_url('http://example.com/') is None

    @patch.dict(
        os.environ,
        {
            'HTTP_PROXY': 'http://squid:3128',
            'NO_PROXY': '10.0.0.0/8',
        },
    )
    def test_alertmanager_real_scenario(self):
        """The exact scenario that triggered this fix."""
        url = 'http://10.142.166.251/cos-alertmanager/api/v2/alerts'
        assert proxy_for_url(url) is None
