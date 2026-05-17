# BYO image for codex CLI. Context = repo root.
#   docker build -f agent/codex/Dockerfile -t cybench/mobilecybench:codex_0.130.0-r2 .

FROM cybench/mobilecybench-kali:v0.1.0

RUN npm install -g @openai/codex@0.130.0 \
    && npm cache clean --force \
    && rm -rf /root/.npm

# Plugin/apps marketplace fetches github.com + chatgpt.com on boot; restricted egress denies.
RUN mkdir -p /root/.codex && \
    printf '[features]\nplugins = false\napps = false\n' > /root/.codex/config.toml

# Secrets/bloat excluded via repo-root .dockerignore.
COPY agent/__init__.py /opt/agent/__init__.py
COPY agent/in_container/ /opt/agent/in_container/
COPY agent/codex/__init__.py agent/codex/event_parser.py agent/codex/run_in_container.py /opt/agent/codex/
COPY utils/__init__.py utils/logger.py utils/json_io.py /opt/utils/
COPY schemas/task.schema.json /opt/schemas/task.schema.json
COPY --chmod=0755 agent/codex/run-agent.sh /run-agent.sh

ENV PYTHONPATH=/opt
ENTRYPOINT []
