# Application and release structure

| Directory | Responsibility |
| --- | --- |
| `apps/api/` | FastAPI investigation, deterministic facts, retrieval, synthesis and session cache |
| `apps/web/` | Next.js workspace and authenticated server-to-server API proxy |
| `ingestion/` | FDA, PubMed and archived DailyMed loading, canonical storage and indexing |
| `evaluation/` | Frozen snapshot export, deterministic RAG gates and separate live judging |
| `migrations/` | Additive PostgreSQL schema migrations |
| `config/` | Versioned non-secret retrieval configuration |
| `infra/terraform/` | Persistent VM, private networking and scoped runtime identity |
| `infra/vm/`, `infra/edge/` | Immutable VM releases and Cloud Run HTTPS entry |
| `infra/` | Owner bootstrap, migration, ingestion and deployment commands |
| `.gitlab/ci/` | Blocking validation, tests, security, evaluation, packaging and deployment |
| `.gitlab/duo/` | One supervised release flow and its hosted execution setup |
| `ci/` | Executable helpers used by the pipeline |
| `scripts/` | Local setup, dependencies and shutdown |
| `tests/` | Unit and real-dependency integration checks |
| `docs/` | Setup, operations, evaluation, security boundaries and verification |
| `skills/` | Release evidence and human approval policy |

PostgreSQL owns facts, text and sessions. GCS preserves immutable source artifacts.
Qdrant returns canonical chunk IDs which are resolved and checked against PostgreSQL.
MedCPT provides retrieval; Gemini synthesizes cited text without calculating metrics.
Credentials and model settings are loaded from Secret Manager through service identities.

The successful release path runs validation, tests, security and frozen RAG checks before
packaging. Approved infrastructure changes precede staging deployment, then readiness and a
reviewed cited investigation produce release evidence. Duo inspects actual artifacts and
reports the outcome. Merge and production promotion remain human actions.
