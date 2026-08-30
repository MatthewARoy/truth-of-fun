FROM ghcr.io/astral-sh/uv:0.11.16 AS uv

FROM python:3.11-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# A built container is a production artifact. Local Compose opts back into
# development explicitly; an ad-hoc deployment must provide a real JWT key.
ENV APP_ENV=production
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md alembic.ini /app/
COPY alembic /app/alembic
COPY app /app/app

# Install exactly the dependency graph that CI audits; do not independently
# resolve floating pyproject ranges while building the production image.
RUN uv sync --frozen --no-dev \
    && addgroup --system app \
    && adduser --system --ingroup app --no-create-home app \
    && chown -R app:app /app

EXPOSE 8000

# Apply database migrations before serving so a compose-only deployment gets
# the full schema. SQLModel's create_all alone misses raw-SQL migrations
# (e.g. the full-text-search column /events?q= depends on).
#
# Proxy headers make request.client.host the real client behind a trusted load
# balancer, which the per-client rate limits key on. Never trust arbitrary
# callers by default: set FORWARDED_ALLOW_IPS to the actual proxy CIDR(s) when
# deploying behind one. Directly exposed containers ignore forged headers.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]

USER app

# Worker stage: same app plus the Playwright Chromium browser (and its system
# libraries) required by the FuncheapSF and Luma connectors.
FROM api AS worker

USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && chown -R app:app /ms-playwright

USER app

CMD ["python", "-m", "app.worker"]
