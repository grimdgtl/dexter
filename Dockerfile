FROM python:3.12-slim

ARG EXTRAS=""

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/data/hf

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts
# CPU paket sprečava preuzimanje CUDA zavisnosti na serveru bez GPU-a.
RUN case "$EXTRAS" in \
      "") uv pip install --system . ;; \
      local) uv pip install --system --torch-backend=cpu ".[local]" \
        && python -c "import torch, sentence_transformers, faster_whisper; assert torch.version.cuda is None" ;; \
      *) echo "Nepodržan EXTRAS: koristi prazno ili local." >&2; exit 1 ;; \
    esac

RUN useradd --uid 10001 -m apu && mkdir -p /app/data && chown -R apu /app
USER apu

CMD ["apu"]
