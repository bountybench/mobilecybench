#!/bin/sh
set -e

# Wrapper entrypoint: run original image entrypoint (if any), then ensure app is installed
# and cache/permissions are correct. This script is intentionally idempotent so it can run
# on container start and in CI reliably.

echo "[wallabag] running custom entrypoint checks..."

# Short sleep to allow linked services a moment to start
sleep 2

echo "[wallabag] running symfony install (non-fatal)..."
# Run install but do not fail the container if it errors (idempotent attempt)
php bin/console wallabag:install --env=prod -n || true

echo "[wallabag] clearing cache and fixing permissions..."
rm -rf /var/www/wallabag/var/cache/prod || true
php bin/console cache:clear --env=prod || true

# Try to set ownership. prefer nobody:nogroup like the original setup script, fall back to www-data if present
if id nobody >/dev/null 2>&1 && getent group nogroup >/dev/null 2>&1; then
  chown -R nobody:nogroup /var/www/wallabag/var || true
elif id www-data >/dev/null 2>&1; then
  chown -R www-data:www-data /var/www/wallabag/var || true
else
  echo "[wallabag] no known web user found to chown; skipping chown"
fi

chmod -R 770 /var/www/wallabag/var || true

echo "[wallabag] custom entrypoint finished, handing control to upstream entrypoint/CMD"

# If upstream docker-entrypoint exists, call it to perform its init (and it will exec the final process)
echo "[wallabag] launching service processes (php-fpm + nginx)..."

# Start php-fpm if available
if [ -x "/usr/sbin/php-fpm81" ]; then
  echo "[wallabag] starting php-fpm81"
  /usr/sbin/php-fpm81 || true &
elif command -v php-fpm >/dev/null 2>&1; then
  echo "[wallabag] starting php-fpm"
  php-fpm || true &
else
  echo "[wallabag] php-fpm binary not found; web backend may fail"
fi

# Start nginx in foreground if available. Avoid adding 'daemon off' if nginx.conf already contains a daemon directive.
if command -v nginx >/dev/null 2>&1; then
  echo "[wallabag] starting nginx"
  if grep -q "^[[:space:]]*daemon[[:space:]]" /etc/nginx/nginx.conf 2>/dev/null; then
    echo "[wallabag] nginx.conf contains daemon directive; starting nginx without extra flags"
    exec nginx
  else
    echo "[wallabag] starting nginx with daemon off"
    exec nginx -g 'daemon off;'
  fi
else
  echo "[wallabag] nginx binary not found; attempting to exec provided CMD"
  exec "$@"
fi
