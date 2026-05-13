#!/bin/sh
# Pick the Squid policy file based on SQUID_MODE env var.
# Default = restricted (fail-safe). Invalid values exit non-zero so a typo'd
# mode is loud, never silently downgraded.
set -eu

MODE="${SQUID_MODE:-restricted}"
case "$MODE" in
    restricted|permissive) ;;
    *)
        echo "egress-proxy: invalid SQUID_MODE=$MODE (expected: restricted|permissive)" >&2
        exit 1
        ;;
esac

exec squid -N -f "/etc/squid/squid_${MODE}.conf"
