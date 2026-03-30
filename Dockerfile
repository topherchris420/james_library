# syntax=docker/dockerfile:1.7

# ── Stage 1: Build ────────────────────────────────────────────
FROM rust:1.94-slim@sha256:f7bf1c266d9e48c8d724733fd97ba60464c44b743eb4f46f935577d3242d81d0 AS builder

WORKDIR /app

# Install build dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 1. Copy manifests to cache dependencies
COPY Cargo.toml Cargo.lock ./
COPY crates/robot-kit/Cargo.toml crates/robot-kit/Cargo.toml
# Create dummy targets declared in Cargo.toml so manifest parsing succeeds.
RUN mkdir -p src benches crates/robot-kit/src \
    && echo "fn main() {}" > src/main.rs \
    && echo "fn main() {}" > benches/agent_benchmarks.rs \
    && echo "pub fn placeholder() {}" > crates/robot-kit/src/lib.rs
RUN --mount=type=cache,id=R.A.I.N.-cargo-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=R.A.I.N.-cargo-git,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,id=R.A.I.N.-target,target=/app/target,sharing=locked \
    cargo build --release --locked
RUN rm -rf src benches crates/robot-kit/src

# 2. Copy only build-relevant source paths (avoid cache-busting on docs/tests/scripts)
COPY src/ src/
COPY benches/ benches/
COPY crates/ crates/
COPY firmware/ firmware/
COPY web/ web/
# Keep release builds resilient when frontend dist assets are not prebuilt in Git.
RUN mkdir -p web/dist && \
    if [ ! -f web/dist/index.html ]; then \
      printf '%s\n' \
        '<!doctype html>' \
        '<html lang="en">' \
        '  <head>' \
        '    <meta charset="utf-8" />' \
        '    <meta name="viewport" content="width=device-width,initial-scale=1" />' \
        '    <title>R.A.I.N. Dashboard</title>' \
        '  </head>' \
        '  <body>' \
        '    <h1>R.A.I.N. Dashboard Unavailable</h1>' \
        '    <p>Frontend assets are not bundled in this build. Build the web UI to populate <code>web/dist</code>.</p>' \
        '  </body>' \
        '</html>' > web/dist/index.html; \
    fi
RUN --mount=type=cache,id=R.A.I.N.-cargo-registry,target=/usr/local/cargo/registry,sharing=locked \
    --mount=type=cache,id=R.A.I.N.-cargo-git,target=/usr/local/cargo/git,sharing=locked \
    --mount=type=cache,id=R.A.I.N.-target,target=/app/target,sharing=locked \
    cargo build --release --locked && \
    cp target/release/R.A.I.N. /app/R.A.I.N. && \
    strip /app/R.A.I.N.

# Prepare runtime directory structure and default config inline (no extra stage)
RUN mkdir -p /R.A.I.N.-data/.R.A.I.N. /R.A.I.N.-data/workspace && \
    cat > /R.A.I.N.-data/.R.A.I.N./config.toml <<EOF && \
    chown -R 65534:65534 /R.A.I.N.-data
workspace_dir = "/R.A.I.N.-data/workspace"
config_path = "/R.A.I.N.-data/.R.A.I.N./config.toml"
api_key = ""
default_provider = "openrouter"
default_model = "anthropic/claude-sonnet-4-20250514"
default_temperature = 0.7

[gateway]
port = 42617
host = "[::]"
allow_public_bind = true
EOF

# ── Stage 2: Development Runtime (Debian) ────────────────────
FROM debian:trixie-slim@sha256:f6e2cfac5cf956ea044b4bd75e6397b4372ad88fe00908045e9a0d21712ae3ba AS dev

# Install essential runtime dependencies only (use docker-compose.override.yml for dev tools)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /R.A.I.N.-data /R.A.I.N.-data
COPY --from=builder /app/R.A.I.N. /usr/local/bin/R.A.I.N.

# Overwrite minimal config with DEV template (Ollama defaults)
COPY dev/config.template.toml /R.A.I.N.-data/.R.A.I.N./config.toml
RUN chown 65534:65534 /R.A.I.N.-data/.R.A.I.N./config.toml

# Environment setup
# Use consistent workspace path
ENV R.A.I.N._WORKSPACE=/R.A.I.N.-data/workspace
ENV HOME=/R.A.I.N.-data
# Defaults for local dev (Ollama) - matches config.template.toml
ENV PROVIDER="ollama"
ENV R.A.I.N._MODEL="minimax-m2.7:cloud"
ENV R.A.I.N._GATEWAY_PORT=42617

# Note: API_KEY is intentionally NOT set here to avoid confusion.
# It is set in config.toml as the Ollama URL.

WORKDIR /R.A.I.N.-data
USER 65534:65534
EXPOSE 42617
ENTRYPOINT ["R.A.I.N."]
CMD ["gateway"]

# ── Stage 3: Production Runtime (Distroless) ─────────────────
FROM gcr.io/distroless/cc-debian13:nonroot@sha256:9c4fe2381c2e6d53c4cfdefeff6edbd2a67ec7713e2c3ca6653806cbdbf27a1e AS release

COPY --from=builder /app/R.A.I.N. /usr/local/bin/R.A.I.N.
COPY --from=builder /R.A.I.N.-data /R.A.I.N.-data

# Environment setup
ENV R.A.I.N._WORKSPACE=/R.A.I.N.-data/workspace
ENV HOME=/R.A.I.N.-data
# Default provider and model are set in config.toml, not here,
# so config file edits are not silently overridden
#ENV PROVIDER=
ENV R.A.I.N._GATEWAY_PORT=42617

# API_KEY must be provided at runtime!

WORKDIR /R.A.I.N.-data
USER 65534:65534
EXPOSE 42617
ENTRYPOINT ["R.A.I.N."]
CMD ["gateway"]
