"""Behavior tests for the egress firewall.

Nightly e2e covers the Squid lifecycle (start/stop, mode switching, real ACL
enforcement). These tests cover two things nightly cannot:

1. ``build_no_proxy`` parsing of malformed app_server — a bad parse silently
   wrong-routes app traffic; nightly only ever sees the happy-path string.
2. Squid conf policy regressions — a deleted ``rfc1918`` / ``SSL_ports`` rule
   would still leave the allowlist green in nightly while silently widening
   what the firewall blocks at the IP layer.
"""

from pathlib import Path

import pytest

from agent import firewall
from agent.firewall import proxy

IMAGE_DIR = Path(__file__).resolve().parents[2] / "agent" / "firewall" / "image"


class TestBuildNoProxy:
    """NO_PROXY must list in-cluster targets the agent reaches DIRECTLY."""

    def test_always_includes_loopback_and_proxy_self(self):
        result = firewall.build_no_proxy({}).split(",")
        assert "localhost" in result
        assert "127.0.0.1" in result
        # Proxy self prevents request recursion (agent → proxy → proxy → ...)
        assert proxy.EGRESS_PROXY_CONTAINER in result

    @pytest.mark.parametrize(
        "app_server,expected_host",
        [
            ("https://owncloud_tls_proxy:443/path", "owncloud_tls_proxy"),
            ("http://server", "server"),
            ("owncloud_tls_proxy:443", "owncloud_tls_proxy"),
            ("server:8080/x", "server"),
        ],
    )
    def test_extracts_app_host(self, app_server, expected_host):
        result = firewall.build_no_proxy({"app_server": app_server}).split(",")
        assert expected_host in result

    @pytest.mark.parametrize(
        "metadata",
        [{}, {"app_server": ""}, {"app_server": None}, {"app_server": "://"}],
    )
    def test_missing_or_unparseable_app_server_does_not_crash(self, metadata):
        # No app host extractable → safety entries still present, no exception.
        result = firewall.build_no_proxy(metadata).split(",")
        assert "localhost" in result
        assert proxy.EGRESS_PROXY_CONTAINER in result

    def test_extra_aliases_are_appended(self):
        result = firewall.build_no_proxy(
            {"app_server": "server:443"}, extra_aliases=["adb-proxy", "ssrf-listener"]
        ).split(",")
        assert "adb-proxy" in result
        assert "ssrf-listener" in result
        assert "server" in result


class TestSquidPolicyRegressions:
    """Both confs must keep baseline deny rules; permissive widens only the
    allowlist (HTTP host match), not the IP / port defenses."""

    @pytest.mark.parametrize("conf", ["squid_restricted.conf", "squid_permissive.conf"])
    def test_denies_rfc1918_and_loopback_destinations(self, conf):
        text = (IMAGE_DIR / conf).read_text()
        assert "rfc1918" in text, f"{conf} missing rfc1918 deny rule"
        assert (
            "to_localhost" in text or "loopback" in text
        ), f"{conf} missing loopback deny rule"

    @pytest.mark.parametrize("conf", ["squid_restricted.conf", "squid_permissive.conf"])
    def test_restricts_connect_to_ssl_ports(self, conf):
        text = (IMAGE_DIR / conf).read_text()
        assert (
            "SSL_ports" in text and "CONNECT" in text
        ), f"{conf} missing CONNECT/SSL_ports gating"

    def test_restricted_uses_allowed_domains_file(self):
        text = (IMAGE_DIR / "squid_restricted.conf").read_text()
        assert (
            "allowed_domains.txt" in text
        ), "restricted mode must load the exact-FQDN allowlist"
