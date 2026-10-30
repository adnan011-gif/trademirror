# Stage 1: Build React frontend
FROM node:20.18.0-alpine3.20 AS frontend-builder
WORKDIR /frontend

# Install dependencies
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy source and build static distribution
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend and static server
FROM python:3.11.10-slim-bookworm AS runner
WORKDIR /app

# Python runtime configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    SAMPLES_DIR=/app/data/datasets \
    FRONTEND_DIST=/app/frontend/dist \
    LLM_PROVIDER=none \
    TRUST_PROXY=true \
    TRUSTED_PROXY_HOPS=1

# Extract and install runtime dependencies from pyproject.toml (no dev extras, no package discovery)
COPY pyproject.toml ./
RUN python3 -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; open('/tmp/requirements.txt', 'w').write('\n'.join(deps) + '\n')" \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy application source
COPY backend/app /app/app

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

# Copy ONLY committed sample datasets (no ground_truth, generator, or tests)
COPY data/datasets/*.csv /app/data/datasets/

# Run as non-root user with no write permissions to /app
RUN useradd -m -u 1000 appuser
USER appuser

# Healthcheck against /api/health using standard python library
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health')"

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
