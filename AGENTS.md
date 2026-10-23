# PharmaGuard AI

Read `docs/setup.md`, `docs/deployment.md`, and `docs/evaluation.md` before changing behavior.
Keep the user's rigorous, evidence-based review approach: challenge unsupported assumptions.

- Facts come from PostgreSQL; language synthesis never computes metrics.
- GCS preserves raw artifacts. Qdrant is rebuildable and returns canonical chunk IDs.
- Never commit secrets, raw corpora, model weights, or the original GCP transcript.
- Do not create `.env` files. Credentials and model configuration come from Secret Manager.
- Keep the API private to the web service; the web UI is intentionally anonymous with a shared usage cap.
- Live LLM judging supplements reviewed ground truth and deterministic gates; never let it rewrite labels.
- Run `uv run ruff check .`, `uv run pytest`, and frontend lint/typecheck/build.
- Run real dependency integration tests with `RUN_INTEGRATION=1` and Compose services.
- CI gates are authoritative. Never lower thresholds, edit labels, remove tests, or skip gates
  to repair a product regression.
- One bounded release repair may change retrieval/product code only. Stop after one failed repair.
- Production approval belongs to a human. No automatic merges or production promotion.
- The release flow first verifies the successful staging path. Product repair requires a separately requested issue or regression task.
- Benchmark labels must be reviewed against source text; generated candidates are not approved.
- Do not mark cloud, GitLab, or live-provider checks passed without their actual results.
