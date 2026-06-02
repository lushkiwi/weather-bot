# Deterministic build for Railway (both the cron runner and the dashboard use this image;
# Railway sets a different start command per service). Installs the package so
# `python -m kalshi_weather_bot.<module>` and the console scripts are available.
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# Default start = dashboard. Railway overrides this for the runner service.
CMD ["python", "-m", "kalshi_weather_bot.web_ui", "--host", "0.0.0.0"]
