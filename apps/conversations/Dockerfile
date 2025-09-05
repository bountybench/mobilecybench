FROM prosody/prosody:0.11.9

# Copy our custom configuration
COPY prosody.cfg.lua /etc/prosody/prosody.cfg.lua

# Generate basic certificates with minimal info
RUN echo -e ".\n.\n.\n.\n.\n10.0.2.2\n." | prosodyctl cert generate 10.0.2.2

# Fix permissions
RUN chown -R prosody:prosody /var/lib/prosody

# Copy certs to expected location
RUN mkdir -p /etc/prosody/certs
RUN cp /var/lib/prosody/10.0.2.2.* /etc/prosody/certs/
RUN chown -R prosody:prosody /etc/prosody/certs