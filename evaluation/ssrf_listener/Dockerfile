FROM python:3.12-slim

WORKDIR /app

# Copy the SSRF listener server
COPY ssrf_server.py /app/

# Create directory for logs
RUN mkdir -p /app/logs

# Set environment variables
ENV SSRF_LISTEN_PORT=8080
ENV SSRF_LOG_FILE=/app/logs/ssrf_requests.json

# Expose the port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2)" || exit 1

# Run the server
CMD ["python", "ssrf_server.py"]
