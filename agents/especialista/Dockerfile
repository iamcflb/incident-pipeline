# Dockerfile for Agent Especialista
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Set work directory
WORKDIR /app

# Copy shared library first (for caching)
COPY shared/pyproject.toml shared/src ./shared/
RUN pip install --no-cache-dir -e ./shared

# Copy agent code
COPY agents/especialista/pyproject.toml agents/especialista/src ./agents/especialista/
RUN pip install --no-cache-dir -e ./agents/especialista

# Create data directories
RUN mkdir -p /data/in /data/out && chown -R appuser:appuser /data /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health')" || exit 1

# Entry point
ENTRYPOINT ["python", "-m", "especialista"]
CMD ["--help"]