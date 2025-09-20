FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20 (required for @openai/codex)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Install Codex CLI via npm
RUN npm install -g @openai/codex

# Create Codex CLI config directory and copy configuration
RUN mkdir -p /root/.codex
COPY agent/codex/config.toml /root/.codex/config.toml

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    requests \
    python-dotenv \
    fastmcp

# Create working directory
WORKDIR /app

# Create agent directory and copy files with correct structure
RUN mkdir -p /app/agent
COPY agent/codex_agent.py /app/
COPY agent/codex_cli_provider.py /app/agent/
COPY agent/codex_prompts.py /app/agent/
COPY agent/mcp/mcp_proxy.py /app/
COPY utils/ /app/utils/

# Copy app codebase (will be different for each app)
ARG APP_NAME=termux
COPY apps/${APP_NAME}/codebase/ /app/codebase/

# Set environment variables
ENV OPENAI_API_KEY=""
ENV PYTHONPATH="/app"

# Create a simple runner script
RUN echo '#!/usr/bin/env python3\n\
import sys\n\
import os\n\
sys.path.insert(0, "/app")\n\
from codex_agent import CodexAgent\n\
\n\
if __name__ == "__main__":\n\
    agent = CodexAgent(\n\
        app_name="termux",\n\
        max_iterations=10\n\
    )\n\
    result = agent.run()\n\
    status = result.get("status", "unknown")\n\
    print(f"Analysis completed with status: {status}")\n\
' > /app/run_agent.py && chmod +x /app/run_agent.py

# Run the Python Codex agent
CMD ["python3", "run_agent.py"]