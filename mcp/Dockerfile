# Dockerfile for MCP Server
FROM python:3.11-slim

# Install Docker CLI and required packages
RUN apt-get update && \
    apt-get install -y \
        curl \
        docker.io \
        android-tools-adb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install MCP dependencies
RUN pip install mcp docker

WORKDIR /app

# Copy MCP server code
COPY mcp_server.py .

# Expose MCP server port
EXPOSE 8000

# Run the MCP server
CMD ["python", "mcp_server.py"]