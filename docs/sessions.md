# Anonymous conversation memory and cache

Each browser holds a signed, one-hour JWT in an HttpOnly, SameSite=Strict cookie. HTTPS
deployments set Secure. The token contains an opaque session UUID and issuer/audience/expiry;
it contains no question, answer, API key, or account identity. The web proxy forwards it to
the private API using a separate header; Cloud Run service authentication remains separate.
The browser never receives the token in a JSON response or localStorage.

`POST /session` creates or renews an unexpired session. The web client renews before requests
and every 55 minutes while open. Expired tokens cannot be refreshed; the proxy clears them
and the client starts a new conversation. A session has a 24-hour absolute lifetime. Session
rows are pruned on session creation/renewal, and admission is capped at 1,000 retained rows.
Anonymous sessions are conversation isolation, not user authentication or protection against
a determined public client. The existing shared daily investigation budget still applies,
including cache requests. There is no claim of unlimited anonymous availability.

PostgreSQL stores the newest **five complete user/assistant exchanges** in chronological order.
Oldest exchanges are evicted (FIFO eviction, as clarified by the user). A reload displays them
as conversation context, with a warning to resubmit for current validated facts and sources.
Only explicit follow-ups such as “Does it …” inherit the previous pair/cutoff. Independent
questions receive no inherited filters. Follow-up synthesis gets at most five matching
exchanges, with each historical question limited to 500 characters and answer to 1,000.
History is untrusted context, never evidence; current citations still require current sources.
Ambiguous/new questions should include explicit drug/event filters.

The session has at most five successful answer-cache entries, each valid for up to one hour.
Only exact requests match. Cache keys include question, effective filters/cutoff, relevant
conversation context, active immutable dataset, retrieval configuration, encoder/reranker
revisions, synthesis model/provider configuration, and application Git SHA. Different sessions
cannot read each other's entries. A row lock rejects concurrent work in the same session with
`SESSION_BUSY`, preventing duplicate synthesis across replicas. Another session may proceed.

A cache hit resolves every evidence chunk back to PostgreSQL and checks its text, metadata,
dataset membership and temporal eligibility, then validates citations again. The new response
has a fresh request ID and `cache_status=hit`. No retrieval/model invocation occurs. Canonical
changes invalidate reuse; errors and insufficient-evidence responses are never cached.
Facts remain the deterministic result for the immutable published dataset. Publishing a new
dataset invalidates the key. Deterministic evaluation calls the service directly, bypassing
session memory/cache so it cannot conceal retrieval regressions.

Migration `0003` owns the session table and grants only session-table writes to the existing
restricted runtime database role. Model/fact tables remain read-only to that role.
`infra.prepare_sessions` generates a signing key in memory, stores it in Secret Manager,
and creates pinned runtime/local configuration versions. It never writes key values to disk.
`sessions_enabled` stays false until a reviewed configuration enables it. Rotate the signing
key by publishing a new version and configuration; old anonymous tokens will be invalidated.
