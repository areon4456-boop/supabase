FROM python:3.12-slim

# The database lives in /data: mount persistent storage there (Amvera does it by default).
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib DB_PATH=/data/salon.db
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY salon_bot ./salon_bot

VOLUME ["/data"]
CMD ["python", "-m", "salon_bot"]
