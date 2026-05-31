# BYO image for claude-code CLI. Context = repo root.
#   docker build -f agent/claude_code/Dockerfile -t cybench/mobilecybench:claudecode_2.1.140-r2 .

FROM cybench/mobilecybench-kali:v0.1.0

RUN npm install -g @anthropic-ai/claude-code@2.1.156 \
    && npm cache clean --force \
    && rm -rf /root/.npm

# Datadog + Anthropic event_logging denied by restricted egress.
ENV DISABLE_TELEMETRY=1

# CLI has no "allow all" wildcard; --dangerously-skip-permissions refuses
# as root. Extend list when new tools ship.
RUN mkdir -p /root/.claude && \
    printf '%s\n' '{"permissions":{"allow":["Bash","Read","Edit","Write","Grep","Glob","WebFetch","WebSearch","Agent","NotebookEdit","ToolSearch","Task","TaskOutput","TaskStop","TodoWrite","AskUserQuestion","Skill","EnterPlanMode","ExitPlanMode","EnterWorktree"]}}' \
    > /root/.claude/settings.json

# Secrets/bloat excluded via repo-root .dockerignore.
COPY agent/__init__.py /opt/agent/__init__.py
COPY agent/in_container/ /opt/agent/in_container/
COPY agent/claude_code/__init__.py agent/claude_code/event_parser.py agent/claude_code/run_in_container.py /opt/agent/claude_code/
COPY utils/__init__.py utils/logger.py utils/json_io.py /opt/utils/
COPY schemas/task.schema.json /opt/schemas/task.schema.json
COPY --chmod=0755 agent/claude_code/run-agent.sh /run-agent.sh

ENV PYTHONPATH=/opt
ENTRYPOINT []
