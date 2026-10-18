# Samedia server — multi-arch (linux/arm64 for Raspberry Pi 5 / nasOS, linux/amd64)
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY samedia ./samedia

ENV SAMEDIA_DATA_DIR=/config \
    SAMEDIA_MEDIA_ROOTS=/media \
    SAMEDIA_PORT=8097 \
    PYTHONUNBUFFERED=1

# The entrypoint fixes /config ownership, then runs the server as PUID:PGID (default 1000:1000).
COPY entrypoint.sh /entrypoint.sh
ENV PUID=1000 PGID=1000

VOLUME ["/config"]
EXPOSE 8097
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8097/healthz',timeout=4)"
ENTRYPOINT ["tini", "--", "/entrypoint.sh"]
CMD ["python", "-m", "samedia.main"]
