# Impact360 SAV Runner — one container: FastAPI backend + static frontend.  No outbound network at runtime.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data STATIC_DIR=/app/static SEED_DIR=/app/library

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY svr ./svr
COPY app ./app
COPY static ./static
COPY library ./library

ARG BUILD_TIME=unknown
ENV BUILD_TIME=${BUILD_TIME}

RUN useradd --system --uid 10001 --create-home i360 \
    && mkdir -p /data && chown -R i360:i360 /data /app
USER i360
VOLUME ["/data"]
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/api/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-access-log"]
