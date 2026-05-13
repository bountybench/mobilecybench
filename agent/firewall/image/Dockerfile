# ubuntu/squid:latest as of 2026-05-13 (multi-arch index). Re-pin via
# `docker buildx imagetools inspect ubuntu/squid:latest`.
FROM ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029

COPY squid_restricted.conf /etc/squid/squid_restricted.conf
COPY squid_permissive.conf /etc/squid/squid_permissive.conf
COPY allowed_domains.txt   /etc/squid/allowed_domains.txt
COPY entrypoint.sh         /usr/local/bin/entrypoint.sh

RUN chmod 0444 /etc/squid/squid_restricted.conf \
               /etc/squid/squid_permissive.conf \
               /etc/squid/allowed_domains.txt && \
    chmod 0555 /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
