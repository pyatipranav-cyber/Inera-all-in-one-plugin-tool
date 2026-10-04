# InEra All-in-One Plugins — production image
FROM python:3.12-slim

# Set to "false" to build a ~400 MB smaller image without LibreOffice
# (Office->PDF then uses the simplified built-in renderer).
ARG WITH_OFFICE=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INERA_DATA_DIR=/data \
    INERA_HOST=0.0.0.0 \
    INERA_PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg espeak-ng fonts-dejavu-core \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-kan \
 && if [ "$WITH_OFFICE" = "true" ]; then \
        apt-get install -y --no-install-recommends libreoffice-writer-nogui libreoffice-impress-nogui libreoffice-calc-nogui; \
    fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 --create-home inera \
 && mkdir -p /data && chown -R inera:inera /data \
 && rm -f /app/.env

USER inera
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["python", "main.py"]
