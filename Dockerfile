FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/data/hf

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src ./src
# Za lokalne modele: uv pip install --system ".[local]"
RUN uv pip install --system .

RUN useradd -m apu && mkdir -p /app/data && chown -R apu /app
USER apu

CMD ["apu"]
