FROM python:3.12-slim
WORKDIR /app
COPY . /app
# Offline wheels are used when present (restricted networks); otherwise install from PyPI.
RUN if ls /app/wheels/*.whl >/dev/null 2>&1; then pip install --no-cache-dir --no-index --find-links /app/wheels -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi && rm -rf /app/wheels
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
