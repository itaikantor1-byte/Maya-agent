FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium
RUN useradd -m worker && mkdir /var/data && chown worker:worker /var/data
COPY main.py .
USER worker
CMD ["python", "main.py"]
