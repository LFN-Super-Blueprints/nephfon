FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy controller and input parser
COPY focom_controller.py .
COPY input_parser.py .

CMD ["kopf", "run", "--standalone", "--liveness=http://0.0.0.0:8080/healthz", "focom_controller.py"]
