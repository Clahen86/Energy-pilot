ARG BUILD_FROM
FROM ${BUILD_FROM}
RUN pip install --no-cache-dir aiohttp pandas numpy "scikit-learn==1.9.1" joblib
COPY energy_pilot /app/energy_pilot
WORKDIR /app
ENV DATA_DIR=/config
CMD ["python", "-m", "energy_pilot.main"]
