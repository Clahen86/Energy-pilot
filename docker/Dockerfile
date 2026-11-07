FROM docker.io/library/python:3.13-slim-bookworm
RUN pip install --no-cache-dir aiohttp pandas numpy "scikit-learn==1.9.1" joblib holidays
COPY energy_pilot/energy_pilot /app/energy_pilot
COPY energy_pilot/integration /app/integration
WORKDIR /app
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8099
CMD ["python", "-m", "energy_pilot.main"]
