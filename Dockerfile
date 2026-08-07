FROM python:3.11-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini /app/
COPY alembic /app/alembic
COPY app /app/app

RUN pip install --no-cache-dir .

EXPOSE 8000

# Apply database migrations before serving so a compose-only deployment gets
# the full schema. SQLModel's create_all alone misses raw-SQL migrations
# (e.g. the full-text-search column /events?q= depends on).
#
# --proxy-headers + forwarded-allow-ips="*" make request.client.host the real
# client behind a platform load balancer, which the per-client rate limits key
# on; without them every visitor shares one window. Trusting "*" is safe only
# while the container is reachable solely through the platform proxy — if you
# expose this port directly, scope FORWARDED_ALLOW_IPS to the proxy's address.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-*}\""]

# Worker stage: same app plus the Playwright Chromium browser (and its system
# libraries) required by the FuncheapSF and Luma connectors.
FROM api AS worker

RUN playwright install --with-deps chromium

CMD ["python", "-m", "app.worker"]
