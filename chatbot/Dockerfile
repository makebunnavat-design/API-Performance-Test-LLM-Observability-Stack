FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY app.py .

RUN pip install --no-cache-dir fastapi uvicorn psycopg2-binary requests

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
