FROM ubuntu/squid:latest

COPY squid_restricted.conf /etc/squid/squid_restricted.conf
COPY squid_permissive.conf /etc/squid/squid_permissive.conf
COPY allowed_domains.txt   /etc/squid/allowed_domains.txt
COPY entrypoint.sh         /usr/local/bin/entrypoint.sh

RUN chmod 0444 /etc/squid/squid_restricted.conf \
               /etc/squid/squid_permissive.conf \
               /etc/squid/allowed_domains.txt && \
    chmod 0555 /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
