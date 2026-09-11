FROM python:3.14.4-slim-bookworm@sha256:fc74d22ffd0d5ac395a4b7bdda75a4539758862c49ebf3005647084631e63789 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install editables==0.6 hatchling==1.32.0 \
    && python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheelhouse .

FROM python:3.14.4-slim-bookworm@sha256:fc74d22ffd0d5ac395a4b7bdda75a4539758862c49ebf3005647084631e63789

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 kalki \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin kalki
WORKDIR /app
COPY requirements-runtime.lock ./
COPY --from=builder /wheelhouse /wheelhouse
RUN python -m pip install --requirement requirements-runtime.lock \
    && python -m pip install --no-deps /wheelhouse/kalki_market_intelligence-*.whl \
    && rm -rf /wheelhouse
USER 10001:10001
ENTRYPOINT []
CMD ["kalki-serve-public"]
