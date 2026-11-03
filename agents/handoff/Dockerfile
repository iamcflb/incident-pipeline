# Dockerfile for Agent Handoff
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Set work directory
WORKDIR /app

# Copy shared library (entire directory to preserve structure)
COPY shared ./shared/
RUN pip install --no-cache-dir -e ./shared

# Copy agent code
COPY agents/handoff ./agents/handoff/
RUN pip install --no-cache-dir -e ./agents/handoff

# Copy watcher
COPY agents/handoff/watcher.py ./agents/handoff/

# Create data directories
RUN mkdir -p /data/in /data/out && chown -R appuser:appuser /data /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Entry point - run watcher
ENTRYPOINT ["python", "agents/handoff/watcher.py"]