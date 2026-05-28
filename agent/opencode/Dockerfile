# BYO image for opencode CLI. Context = repo root.
#   docker build -f agent/opencode/Dockerfile -t cybench/mobilecybench:opencode_1.15.6-r1 .

FROM cybench/mobilecybench-kali:v0.1.0

RUN npm install -g opencode-ai@1.15.6 \
    && npm cache clean --force \
    && rm -rf /root/.npm

# Secrets/bloat excluded via repo-root .dockerignore.
COPY agent/__init__.py /opt/agent/
COPY agent/in_container/ /opt/agent/in_container/
COPY agent/opencode/__init__.py agent/opencode/event_parser.py agent/opencode/run_in_container.py /opt/agent/opencode/
COPY utils/__init__.py utils/logger.py utils/json_io.py /opt/utils/
COPY schemas/task.schema.json /opt/schemas/task.schema.json
COPY --chmod=0755 agent/opencode/run-agent.sh /run-agent.sh

ENV PYTHONPATH=/opt
ENTRYPOINT []
