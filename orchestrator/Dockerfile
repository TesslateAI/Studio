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
    curl \
    ca-certificates \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app

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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]