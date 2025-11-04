FROM python:3.11-slim

# System packages
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    android-tools-adb \
    gcc \
    g++ \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Python packages
# Pin to minor version to get patch releases while avoiding breaking changes
RUN pip install --no-cache-dir \
    fastmcp~=2.12.0 \
    docker \
    Pillow \
    tiktoken

# Add ngrok
RUN curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
 && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list \
 && apt-get update && apt-get install -y ngrok=3.26.0

WORKDIR /app
EXPOSE 8000

ENV PYTHONPATH=/app

# Start FastMCP + ngrok
CMD bash -c "python3 /app/mcp/mcp_server.py & ngrok start --config /app/ngrok.yml --all"
