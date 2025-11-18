FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn httpx

# Copy application
COPY main.py .

# Expose port
EXPOSE 8080

# Run the application
CMD ["python", "main.py"]
