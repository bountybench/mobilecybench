# BYO-contract reference image for the claude-code CLI agent.
# Build context = repo root.
#   docker build -f agent/claude_code/Dockerfile -t cybench/mobilecybench:claudecode_<ver> .

FROM cybench/mobilecybench-kali:v0.1.0

RUN npm install -g @anthropic-ai/claude-code@2.1.140 \
    && npm cache clean --force \
    && rm -rf /root/.npm

# Suppress Datadog log uploads + Anthropic event_logging / eval pre-flight,
# all of which the restricted-mode egress firewall would deny.
ENV DISABLE_TELEMETRY=1

# Pre-allow all tools so the CLI doesn't prompt for permissions
# (--dangerously-skip-permissions refuses to run as root). Claude Code has
# no "allow all" wildcard; update this list if new tools ship.
RUN mkdir -p /root/.claude && \
    printf '%s\n' '{"permissions":{"allow":["Bash","Read","Edit","Write","Grep","Glob","WebFetch","WebSearch","Agent","NotebookEdit","ToolSearch","Task","TaskOutput","TaskStop","TodoWrite","AskUserQuestion","Skill","EnterPlanMode","ExitPlanMode","EnterWorktree"]}}' \
    > /root/.claude/settings.json

# Explicit-allowlist COPYs (no wildcards) so we never bake anything
# unintended into image layer history.
COPY agent/__init__.py /opt/agent/__init__.py
COPY agent/in_container/__init__.py /opt/agent/in_container/__init__.py
COPY agent/in_container/runner.py /opt/agent/in_container/runner.py
COPY agent/claude_code/__init__.py /opt/agent/claude_code/__init__.py
COPY agent/claude_code/event_parser.py /opt/agent/claude_code/event_parser.py
COPY agent/claude_code/run_in_container.py /opt/agent/claude_code/run_in_container.py
COPY utils/__init__.py /opt/utils/__init__.py
COPY utils/logger.py /opt/utils/logger.py
COPY utils/json_io.py /opt/utils/json_io.py
COPY schemas/task.schema.json /opt/schemas/task.schema.json
COPY agent/claude_code/run-agent.sh /run-agent.sh
RUN chmod +x /run-agent.sh

ENV PYTHONPATH=/opt
ENTRYPOINT []
