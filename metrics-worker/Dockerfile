FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY worker.py .

RUN pip install --no-cache-dir psycopg2-binary requests

CMD ["python", "worker.py"]
