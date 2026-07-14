FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends passwd tar \
    && groupadd --gid 10001 erp \
    && useradd --uid 10001 --gid erp --no-create-home --no-log-init --shell /usr/sbin/nologin erp \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/media /app/staticfiles \
    && chmod +x /app/entrypoint.sh \
    && chown -R erp:erp /app

USER erp

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/api/health/', headers={'X-Forwarded-Proto':'https'}); urllib.request.urlopen(r, timeout=3)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
