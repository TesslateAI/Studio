# Stage 1: Build Alpine-compatible node_modules
FROM node:20-alpine AS template-builder

WORKDIR /template-build
COPY template/package.json template/package-lock.json ./
RUN npm ci --production=false

# Stage 2: Main application
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system -e .

# Copy rest of application (template/ already excluded in .dockerignore)
COPY . .

# Copy Alpine-built node_modules from builder stage
RUN mkdir -p /app/template
COPY --from=template-builder /template-build/node_modules /app/template/node_modules

# Copy rest of template files
COPY template/ /app/template/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]