FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kalshi_common.py kalshi_btc_bot.py btc_tracker.py btc_dashboard.py ./

# Provide secrets at runtime with -e or --env-file .env
CMD ["python", "kalshi_btc_bot.py"]