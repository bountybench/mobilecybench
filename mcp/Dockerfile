# Dockerfile for MCP Server
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        curl \
        docker.io \
        android-tools-adb \
        gcc \
        g++ && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install MCP dependencies
RUN pip install --no-cache-dir \
    mcp \
    docker

WORKDIR /app

# Copy MCP server code
COPY mcp_server.py .

# Make the script executable
RUN chmod +x mcp_server.py

# Keep container running for stdio communication
CMD ["tail", "-f", "/dev/null"]