FROM python:3.12-slim

ARG VERSION=""

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend

# dialout: Zugriff auf USB-/Serielle Geräte
RUN useradd -M -G dialout app && mkdir /data && chown app /data
USER app

ENV PORT=8080 \
    BIND=0.0.0.0 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    MESHBOARD_VERSION=$VERSION

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz',timeout=2)" || exit 1

# Argumente von „docker run IMAGE …“ gehen an den Server (z. B. --version, --days 90)
ENTRYPOINT ["python", "-m", "backend"]
