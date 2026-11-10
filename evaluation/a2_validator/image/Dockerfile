# Validator image: agent CLIs + local analysis tools. Deliberately NO adb,
# no sqlite client for the device, no database clients: the only path to the
# device/backend is `mcbv` -> egress proxy -> host gateway (read-only).
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 ripgrep jq ca-certificates curl file unzip \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g @anthropic-ai/claude-code@2.1.319 @openai/codex@0.135.0 @google/gemini-cli@0.67.0 \
    && npm cache clean --force
COPY mcbv /usr/local/bin/mcbv
RUN chmod 0755 /usr/local/bin/mcbv
USER node
WORKDIR /work
