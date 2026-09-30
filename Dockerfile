FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server

RUN mkdir -p /app/output/multiclip /app/data
EXPOSE 10000
CMD ["sh", "-c", "uvicorn server.multiclip_api:app --host 0.0.0.0 --port ${PORT:-10000}"]
