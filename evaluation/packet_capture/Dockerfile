FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tcpdump \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY packet_capture.py /app/

ENV PACKET_CAPTURE_OUTPUT=/captures/packet_capture.json
ENV PACKET_CAPTURE_INTERFACE=any
ENV PACKET_CAPTURE_FILTER=tcp port 14378 or tcp port 80
ENV PACKET_CAPTURE_SENTINEL_URL=http://127.0.0.1:14378/_mobilecybench/packet_capture_sentinel

CMD ["python", "packet_capture.py"]
