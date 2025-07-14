FROM joplin/server:latest

USER root

RUN apt-get update && \
    apt-get install -y netcat-openbsd socat && \
    mkdir -p /home/joplin/packages/server/logs /home/joplin/packages/server/temp && \
    chown -R node:node /home/joplin/packages/server/logs /home/joplin/packages/server/temp && \
    rm -rf /var/lib/apt/lists/*

USER node

EXPOSE 22300