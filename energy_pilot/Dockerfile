FROM docker.io/library/python:3.13-slim-bookworm
RUN pip install --no-cache-dir aiohttp pandas numpy "scikit-learn==1.9.1" joblib holidays
COPY energy_pilot /app/energy_pilot
COPY integration /app/integration
WORKDIR /app
ARG BUILD_VERSION=dev
ENV DATA_DIR=/config PYTHONUNBUFFERED=1 BUILD_VERSION=${BUILD_VERSION}
CMD ["python", "-m", "energy_pilot.main"]
