# Multi-stage build for AgentTrust Reference Registry
# Base: python:3.11-slim (~150MB)

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire application
COPY . .

# Create data directory for optional persistence
RUN mkdir -p /data

# Expose port 8090 (default registry port)
EXPOSE 8090

# Health check: registry should respond to /healthz within 10 seconds
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8090/healthz || exit 1

# Default command: start registry on 0.0.0.0:8090
# Environment variables REGISTRY_HOST and REGISTRY_PORT are used via shell expansion
CMD python -m registry.app \
    --host ${REGISTRY_HOST:-0.0.0.0} \
    --port ${REGISTRY_PORT:-8090}
