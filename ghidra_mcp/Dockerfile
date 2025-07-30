FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y openjdk-21-jdk \
                       wget \
                       unzip \
                       git \
                       python3 \
                       python3-pip \
                       gcc \
                       g++ \
                       make \
                       xvfb \
                       fluxbox \
                       x11vnc && \
    rm -rf /var/lib/apt/lists/*

RUN wget -O ghidra_11.4_PUBLIC_20250620.zip \
      https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_11.4_build/ghidra_11.4_PUBLIC_20250620.zip && \
    unzip ghidra_11.4_PUBLIC_20250620.zip -d /opt && \
    mv /opt/ghidra_11.4_PUBLIC /opt/ghidra && \
    rm ghidra_11.4_PUBLIC_20250620.zip

RUN git clone https://github.com/LaurieWired/GhidraMCP.git /tmp/GhidraMCP && \
    mkdir -p /opt/ghidra/Ghidra/Extensions/GhidraMCP && \
    cp -r /tmp/GhidraMCP/* /opt/ghidra/Ghidra/Extensions/GhidraMCP && \
    chmod +x /opt/ghidra/Ghidra/Extensions/GhidraMCP/bridge_mcp_ghidra.py && \
    rm -rf /tmp/GhidraMCP

RUN pip3 install --no-cache-dir -r /opt/ghidra/Ghidra/Extensions/GhidraMCP/requirements.txt

EXPOSE 9000

# Copy over startup script to handle the MCP bridge
COPY start_ghidra_mcp.sh /usr/local/bin/start-ghidra-mcp.sh
RUN chmod +x /usr/local/bin/start-ghidra-mcp.sh

CMD ["/usr/local/bin/start-ghidra-mcp.sh"]
