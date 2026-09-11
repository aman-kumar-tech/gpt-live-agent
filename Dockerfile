# Runtime image for the agent worker, token server, and web demo -- see
# docker-compose.yml for the three services built from this one image (they
# differ only by `command:`). An editable install + docker-compose's bind
# mount of the repo means code edits on the host apply without rebuilding.

FROM python:3.11-slim

WORKDIR /app

# Dependencies in their own layer so `docker compose build` only reinstalls
# when pyproject.toml actually changes, not on every source edit.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

COPY . .

ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src

CMD ["python", "-m", "receptionist.worker", "dev"]
