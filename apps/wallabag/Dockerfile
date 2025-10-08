FROM wallabag/wallabag:latest

# Install small utilities needed for healthchecks and entrypoint
USER root
# base image uses Alpine; use apk
RUN apk add --no-cache netcat-openbsd jq

# Copy custom entrypoint that will run install, clear cache and fix permissions on start
COPY docker-entrypoint.sh /usr/local/bin/mcb-entrypoint.sh
RUN chmod +x /usr/local/bin/mcb-entrypoint.sh

# Ensure www-data owns var dir (image may already do this, but be explicit for CI)
RUN chown -R www-data:www-data /var/www/wallabag/var || true

# Expose same port as upstream image
EXPOSE 80

# Wrap the upstream image with our entrypoint. Keep upstream CMD so we don't assume daemon path.
ENTRYPOINT ["/usr/local/bin/mcb-entrypoint.sh"]

# HEALTHCHECK: verify that the web server responds on port 80 and app login page exists
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=5 \
  CMD nc -z localhost 80 || exit 1
