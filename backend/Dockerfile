FROM python:3.12-slim

# tesseract enables the production OCR engine (HHRN_OCR_ENGINE=tesseract)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pytesseract pillow

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

RUN useradd --create-home appuser \
    && mkdir -p /data/storage \
    && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
