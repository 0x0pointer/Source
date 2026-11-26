# Sandbox image for Fabro runs on source: Python 3.12, git, gh and what the
# unit tests need (numpy, pytest), plus the two light runtime dependencies
# (mcp, pypdf). fastembed and onnxruntime are left out on purpose: the tests
# use a fake embedder, as in CI, and no model can be downloaded in the sandbox.
# Build from the repo root:
#   docker build -f .fabro/docker/Dockerfile -t source-fabro:latest .
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates jq make gh \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_ROOT_USER_ACTION=ignore PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir numpy "pytest>=8" pypdf "mcp>=1.2,<2"
