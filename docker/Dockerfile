# Multi-arch image (linux/amd64, linux/arm64) for the DR SSD1306 demo.
# Build from the repository root: docker build -f docker/Dockerfile -t dr-ssd1306 .
# Dockerfile.dockerignore, next to this file, applies to that build.
#
# The `pi` extra (luma.oled, smbus2) is pure Python, so every image has it and
# `serve --hardware` drives the OLED when /dev/i2c-1 is passed in.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
# Dependencies first, so source changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra pi
COPY LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra pi

FROM python:${PYTHON_VERSION}-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
# The settings file lives in /data (a volume in docker-compose.yaml).
RUN useradd --system --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown app /data
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
ENTRYPOINT ["dr-ssd1306"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080", "--config", "/data/settings.json", "--simulate"]
