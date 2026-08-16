FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy operator code
COPY controllers/ ./controllers/
COPY utils/ ./utils/

# Set Python path
ENV PYTHONPATH=/app

# Run the operator
CMD ["kopf", "run", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "controllers/provisioning_request_controller.py"]
