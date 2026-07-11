# Vulnerable-baseline backend for wallabag/report-2 (server-side IDOR).
#
# Mirrors apps/wallabag/Dockerfile but parameterizes the base so the build
# script can pin the *vulnerable* baseline (2.6.10) instead of the app's
# default (2.6.14). scripts/build_zeroday_backend_images.sh builds this, then
# layers fix.patch on top for the patched image.
#
# NOTE: copy apps/wallabag/docker-entrypoint.sh next to this Dockerfile (the
# build context) so the COPY below resolves. git is needed for the patched
# layer's `git apply`; the wallabag base image ships it, but add it here if a
# future base drops it.
ARG BASE_IMAGE=wallabag/wallabag:2.6.10
FROM ${BASE_IMAGE}

USER root
RUN apk add --no-cache netcat-openbsd jq curl git

COPY docker-entrypoint.sh /usr/local/bin/mcb-entrypoint.sh
RUN chmod +x /usr/local/bin/mcb-entrypoint.sh
RUN chown -R www-data:www-data /var/www/wallabag/var || true

EXPOSE 80
ENTRYPOINT ["/usr/local/bin/mcb-entrypoint.sh"]
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
  CMD nc -z localhost 80 && curl -f http://localhost/login > /dev/null 2>&1 || exit 1
