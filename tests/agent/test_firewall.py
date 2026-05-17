"""Behavior tests for build_no_proxy parsing and Squid conf policy invariants."""

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import docker.errors
import pytest

from agent import firewall
from agent.firewall import proxy

IMAGE_DIR = Path(__file__).resolve().parents[2] / "agent" / "firewall" / "image"


def _make_tar(arcname: str, content: str) -> bytes:
    data = content.encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(arcname)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


class TestBuildNoProxy:
    """NO_PROXY must list in-cluster targets the agent reaches DIRECTLY."""

    def test_always_includes_loopback_and_proxy_self(self):
        result = firewall.build_no_proxy({}).split(",")
        assert "localhost" in result
        assert "127.0.0.1" in result
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


class TestSquidLogCapture:
    @patch("agent.firewall.proxy.docker.from_env")
    def test_save_logs_copies_access_and_cache_logs(self, mock_from_env, tmp_path):
        client = MagicMock()
        container = MagicMock()
        mock_from_env.return_value = client
        client.containers.get.return_value = container
        container.exec_run.return_value = MagicMock(exit_code=0)
        container.get_archive.side_effect = [
            (iter([_make_tar("access.log", "TCP_DENIED example.com\n")]), {}),
            (iter([_make_tar("cache.log", "Squid cache entry\n")]), {}),
        ]

        captured = proxy.save_logs(tmp_path)

        assert (tmp_path / "squid_access.log").read_text() == "TCP_DENIED example.com\n"
        assert (tmp_path / "squid_cache.log").read_text() == "Squid cache entry\n"
        assert captured == {
            "squid_access.log": tmp_path / "squid_access.log",
            "squid_cache.log": tmp_path / "squid_cache.log",
        }
        assert container.get_archive.call_args_list == [
            call("/var/log/squid/access.log"),
            call("/var/log/squid/cache.log"),
        ]

    @patch("agent.firewall.proxy.docker.from_env")
    def test_save_logs_skips_missing_sidecar(self, mock_from_env, tmp_path):
        client = MagicMock()
        mock_from_env.return_value = client
        client.containers.get.side_effect = docker.errors.NotFound("not found")

        assert proxy.save_logs(tmp_path) == {}
        assert not (tmp_path / "squid_access.log").exists()
        assert not (tmp_path / "squid_cache.log").exists()
