# Actions Source Policy

This document records workflow action-source decisions for CI workflows.

## Approved third-party action sources

- `Swatinem/rust-cache@v2`
  - Used in GitHub-hosted Rust build/test workflows where `ubuntu-latest` runners need standard Cargo cache reuse.
  - Replaces `useblacksmith/rust-cache` in workflows that no longer run on Blacksmith-hosted runners.

## Rationale

- GitHub-hosted runners should use cache actions that are designed for GitHub-hosted infrastructure.
- Blacksmith-specific cache actions should remain limited to workflows that still run on Blacksmith runners.
