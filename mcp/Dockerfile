FROM python:3.11-slim

# System packages
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    android-tools-adb \
    gcc \
    g++ && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python packages
RUN pip install --no-cache-dir \
    fastmcp \
    docker

# Add ngrok
RUN curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
 && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list \
 && apt-get update && apt-get install -y ngrok

# Copy code and ngrok config
WORKDIR /app
COPY ui_connection.py .
COPY mcp_server.py .
COPY docker_setup.py .
COPY ngrok.yml /app/ngrok.yml

EXPOSE 8000

# Start FastMCP + ngrok
CMD bash -c "python3 mcp_server.py & ngrok start --config /app/ngrok.yml --all"
