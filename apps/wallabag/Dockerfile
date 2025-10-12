FROM wallabag/wallabag:latest

# Install small utilities needed for healthchecks and entrypoint
USER root
# base image uses Alpine; use apk
RUN apk add --no-cache netcat-openbsd jq curl

# Copy custom entrypoint that will run install, clear cache and fix permissions on start
COPY docker-entrypoint.sh /usr/local/bin/mcb-entrypoint.sh
RUN chmod +x /usr/local/bin/mcb-entrypoint.sh

# Ensure www-data owns var dir (image may already do this, but be explicit for CI)
RUN chown -R www-data:www-data /var/www/wallabag/var || true

# Expose same port as upstream image
EXPOSE 80

# Wrap the upstream image with our entrypoint. Keep upstream CMD so we don't assume daemon path.
ENTRYPOINT ["/usr/local/bin/mcb-entrypoint.sh"]

# HEALTHCHECK: verify that the web server responds and the login page is accessible
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD nc -z localhost 80 && curl -f http://localhost/login > /dev/null 2>&1 || exit 1
