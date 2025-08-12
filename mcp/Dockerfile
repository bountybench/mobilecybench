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
RUN NGROK_VERSION=3.26.0 \
 && wget -qO /tmp/ngrok_${NGROK_VERSION}_linux_amd64.zip https://dl.ngrok.com/ngrok_${NGROK_VERSION}_linux_amd64.zip \
 && unzip /tmp/ngrok_${NGROK_VERSION}_linux_amd64.zip -d /tmp \
 && mv /tmp/ngrok /usr/local/bin/ngrok \
 && chmod +x /usr/local/bin/ngrok \
 && ngrok version

# Copy code and ngrok config
WORKDIR /app
COPY ui_connection.py .
COPY mcp_server.py .

EXPOSE 8000

# Start FastMCP + ngrok
CMD bash -c "python3 mcp_server.py & ngrok start --config /app/ngrok.yml --all"
