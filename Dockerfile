# Офлайн-сборка: все Python-зависимости из vendor/wheels (pip --no-index),
# фронт уже собран в src/jana_address/static, справочник лежит в reference/.
# Проверка: docker build --network=none -t jana-address .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_INDEX=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    JANA_REFERENCE_DB=/app/reference/reference.sqlite \
    JANA_EDITS_DB=/app/var/edits.sqlite

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY vendor/wheels /tmp/wheels
RUN pip install --no-index --find-links /tmp/wheels -r /app/requirements.txt \
    && rm -rf /tmp/wheels

COPY reference/reference.sqlite /app/reference/reference.sqlite
COPY src /app/src

RUN useradd --create-home --uid 10001 app && mkdir -p /app/var && chown app /app/var
USER app
VOLUME ["/app/var"]
EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=30 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "jana_address.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
