# Implementation Backlog

## Working agreement

Each item is intentionally small enough for one focused coding task and one reviewable pull request. Dependencies are explicit; a task may add fixtures, migrations, or documentation needed by its own behavior, but must not quietly implement a later milestone. “Manual verification” means a repeatable reviewer check in the development environment, not a substitute for automated coverage.

## M0 — Foundation

### BL-001 — Create workspace and quality tooling

- **Goal and user value:** Establish a predictable monorepo so contributors can change API, admin, worker, or widget code without breaking unrelated deliverables.
- **Scope / non-scope:** Add the target workspace layout, language/tool version pinning, formatter, linter, type-check, and test commands; do not add product features or cloud resources.
- **Dependencies:** None.
- **Acceptance criteria:** A fresh checkout has documented bootstrap steps; one command runs checks for every workspace; checks fail on a deliberate format/type violation.
- **Implementation notes:** Reserve `apps/api`, `apps/worker`, `apps/admin`, `packages/widget`, `packages/contracts`, and `infra/terraform`; use one root task runner.
- **Automated tests:** CI runs formatter check, lint, type check, and empty-test discovery for each workspace.
- **Manual verification:** Clone into a clean directory and follow the bootstrap instructions without hidden global dependencies.
- **Risks or open questions:** Final package-manager choice must suit both Python FastAPI and TypeScript workspaces; choose it in the task and document it.

### BL-002 — Define shared contracts and error envelope

- **Goal and user value:** Give widget, admin, API, and worker a stable vocabulary before feature code starts, reducing integration churn.
- **Scope / non-scope:** Define request/response schemas, SSE event names, shared identifiers, pagination, and safe error envelope; do not implement endpoints or database persistence.
- **Dependencies:** BL-001.
- **Acceptance criteria:** Contracts define chat request fields and `answer.delta`, `citation`, `abstention`, `complete`, and `error` events; generated/client validation rejects malformed examples.
- **Implementation notes:** Version public contracts and distinguish safe public errors from authenticated admin errors; include model-profile and source-version IDs in internal trace contracts.
- **Automated tests:** Schema validation tests cover valid payloads, missing fields, oversized history, and each SSE event shape.
- **Manual verification:** Review a rendered contract example with API and frontend contributors.
- **Risks or open questions:** Contract-generation tooling must not make Python and TypeScript deployments tightly coupled.

### BL-003 — Bootstrap Terraform development environment

- **Goal and user value:** Make the first shared environment reproducible rather than dependent on manual console changes.
- **Scope / non-scope:** Terraform development project resources for Cloud Run, Cloud SQL, Cloud Storage, Cloud Tasks, Secret Manager, service accounts, and logging permissions; do not deploy application images or create production resources.
- **Dependencies:** BL-001.
- **Acceptance criteria:** `plan` is stable; `apply` creates tagged development resources; destroy/cleanup policy is documented; least-privilege service accounts are separate for API and worker.
- **Implementation notes:** Use remote state, environment variables, private bucket defaults, Cloud SQL private connectivity where feasible, and output only non-secret identifiers.
- **Automated tests:** Run `terraform fmt -check` and `terraform validate` in CI; add policy assertions for bucket privacy and no secret outputs.
- **Manual verification:** Apply in the development project and inspect the created resources and IAM bindings.
- **Risks or open questions:** Cloud SQL networking and billing quotas must be available in the selected development project.

### BL-004 — Add database migration baseline

- **Goal and user value:** Ensure schema changes are reversible, reviewed, and runnable in each environment.
- **Scope / non-scope:** Configure migrations, enable pgvector, and create an application schema/version table; do not create business tables yet.
- **Dependencies:** BL-001, BL-003.
- **Acceptance criteria:** An empty Cloud SQL database migrates successfully; a second migration is a no-op; pgvector extension availability is verified.
- **Implementation notes:** Run migrations from an authenticated one-shot deployment job, never from API startup; document local test-database setup.
- **Automated tests:** Test upgrade from empty database and migration idempotency against PostgreSQL with pgvector.
- **Manual verification:** Run the migration command against the development database and inspect the schema version.
- **Risks or open questions:** Confirm the chosen Cloud SQL PostgreSQL version supports the required pgvector extension version.

### BL-005 — Add CI and development deployment pipeline

- **Goal and user value:** Give every merged change a repeatable verification path and a safe path to the shared environment.
- **Scope / non-scope:** Build/test pipeline, container image build, artifact tagging, and manual-approval development deployment; do not automate production release.
- **Dependencies:** BL-001, BL-003, BL-004.
- **Acceptance criteria:** Pull requests run checks; main builds immutable images; an approved run deploys a health-only API image to development Cloud Run.
- **Implementation notes:** Use workload identity rather than long-lived GCP keys; pin image digests and retain deployment metadata.
- **Automated tests:** Pipeline fixture verifies required jobs and Terraform validation run; smoke test calls deployed health endpoint.
- **Manual verification:** Trigger a development deployment and confirm the revision/image digest in Cloud Run.
- **Risks or open questions:** Select the CI provider and repository protections when the source repository is initialized.

## M1 — Grounded chat vertical slice

### BL-010 — Create core source, chunk, widget, and trace schema

- **Goal and user value:** Persist the minimum data needed to answer from a source and explain how the answer was produced.
- **Scope / non-scope:** Add migrations and repositories for widget, source document/version, chunk, conversation/message, and retrieval trace; do not add job retries, provider profiles, or admin UI.
- **Dependencies:** BL-004.
- **Acceptance criteria:** A chunk belongs to exactly one source version; source version status supports queued/processing/indexed/failed/superseded; trace links request, chunks, and profile placeholder.
- **Implementation notes:** Store page/heading, token count, metadata JSON, vector, and full-text columns from the outset; enforce foreign keys and indexes.
- **Automated tests:** Repository tests prove version/chunk ownership, invalid state rejection, and cascade/delete behavior.
- **Manual verification:** Inspect the migrated schema and insert one source/version/chunk/trace chain using a developer command.
- **Risks or open questions:** Retention duration for visitor conversations needs a product/privacy decision before public launch.

### BL-011 — Verify Supabase admin identity at the API boundary

- **Goal and user value:** Ensure source-changing operations are accessible only to authenticated administrators.
- **Scope / non-scope:** Add server-side Supabase JWT verification and an admin dependency/middleware; do not build portal pages or role management.
- **Dependencies:** BL-002, BL-010.
- **Acceptance criteria:** Valid Supabase access token reaches a protected stub endpoint; absent, expired, or forged token receives a safe 401/403 response.
- **Implementation notes:** Map Supabase subject to `admin_user` on first verified request; keep the one-admin-role rule explicit.
- **Automated tests:** JWT verification tests cover issuer, audience, signature, expiration, and subject mapping.
- **Manual verification:** Obtain a development Supabase session and call the protected endpoint, then retry without the bearer token.
- **Risks or open questions:** Supabase project URL/JWT keys must be supplied as Secret Manager-backed environment configuration.

### BL-012 — Define provider adapter interfaces and a deterministic test provider

- **Goal and user value:** Permit real Vertex integration while keeping tests fast, repeatable, and independent of model availability.
- **Scope / non-scope:** Define generation and embedding adapter protocols, capability metadata, request budgets, and deterministic fake implementations; do not call Vertex AI.
- **Dependencies:** BL-002.
- **Acceptance criteria:** Orchestration can call fake generation and embeddings through interfaces without importing provider SDKs; unsupported role use fails clearly.
- **Implementation notes:** Include model ID, provider ID, timeout, token count, and cost-estimate fields in results; keep rewrite/rerank interfaces declared but unused in M1.
- **Automated tests:** Contract tests run the same behavior suite against fake adapters and assert error mapping.
- **Manual verification:** Swap fake adapter configuration in a local example and confirm no orchestration code changes.
- **Risks or open questions:** Provider-specific token/cost estimates vary; treat them as estimates, not billing records.

### BL-013 — Implement Vertex AI generation adapter

- **Goal and user value:** Produce real, streamed grounded answers in the development environment.
- **Scope / non-scope:** Implement Vertex authentication via Cloud Run service identity, generation streaming, timeout handling, and normalized error mapping; do not implement query rewrite, fallback providers, or reranking.
- **Dependencies:** BL-003, BL-012.
- **Acceptance criteria:** Development Cloud Run service can stream a configured Vertex model response; SDK/provider failures map to retryable or safe terminal categories.
- **Implementation notes:** Read project, region, and model ID from configuration; never log prompts or credentials at debug level by default.
- **Automated tests:** Adapter contract tests use the fake provider; optional integration test runs only when explicit Vertex test credentials/environment are present.
- **Manual verification:** Invoke a restricted development endpoint or script and observe streamed output plus provider request metadata in logs.
- **Risks or open questions:** Vertex model availability and quotas are project/region-specific.

### BL-014 — Implement Vertex AI embedding adapter

- **Goal and user value:** Turn source text and questions into comparable vectors for semantic retrieval.
- **Scope / non-scope:** Implement batch embedding calls, dimension validation, retries, and normalized metadata; do not implement hybrid search or re-index UI.
- **Dependencies:** BL-003, BL-012, BL-010.
- **Acceptance criteria:** Identical configured model/dimension is used for document and query embeddings; invalid dimensions cannot persist to the chunk table.
- **Implementation notes:** Batch only within provider limits and record provider/model/dimension on source version metadata.
- **Automated tests:** Fake-adapter tests cover batching, retries, dimension mismatch, and empty text rejection.
- **Manual verification:** Embed a small fixture through Vertex in development and inspect the stored vector dimension.
- **Risks or open questions:** Changing this model later requires the re-index flow in BL-040.

### BL-015 — Add private TXT/Markdown upload initiation

- **Goal and user value:** Let an authenticated admin place initial knowledge content into the system securely.
- **Scope / non-scope:** Implement authenticated source creation, content-type/size validation, private Cloud Storage upload path, and queued source-version record; do not parse content or build portal UI.
- **Dependencies:** BL-003, BL-010, BL-011.
- **Acceptance criteria:** TXT and Markdown uploads create unique private object keys and queued versions; invalid type/size is rejected before storage; object access is not public.
- **Implementation notes:** Prefer signed upload URLs or proxied streaming upload based on the admin portal’s deployment constraints; compute content hash after upload.
- **Automated tests:** API tests cover authorization, supported types, size boundary, key uniqueness, and storage-client failure.
- **Manual verification:** Upload a Markdown fixture with an authenticated request and confirm it is private in Cloud Storage.
- **Risks or open questions:** Establish explicit file-size limits before accepting user-supplied PDFs in M2.

### BL-016 — Parse and chunk TXT/Markdown sources

- **Goal and user value:** Preserve meaningful document structure so answers cite coherent support content.
- **Scope / non-scope:** Extract normalized text and headings from TXT/Markdown; produce 300–600-token prose chunks with 10–15% overlap and parent references; do not parse PDF, HTML, or tables.
- **Dependencies:** BL-010, BL-015.
- **Acceptance criteria:** Heading metadata is retained; overlap is within configured bounds; a chunk never exceeds max tokens except an explicitly preserved indivisible block.
- **Implementation notes:** Tokenizer must be model-profile configurable but deterministic for tests; store parser/chunker version in source-version metadata.
- **Automated tests:** Fixtures cover headings, lists, code blocks, short documents, boundary overlap, and deterministic chunk IDs.
- **Manual verification:** Inspect chunks from a representative Markdown guide and verify citations can name its heading.
- **Risks or open questions:** Exact tokenization differs by provider; use one baseline tokenizer and document its approximation.

### BL-017 — Index chunks and perform vector retrieval

- **Goal and user value:** Retrieve the most relevant source passages for a visitor question.
- **Scope / non-scope:** Embed parsed chunks, persist them, create pgvector index/query repository, and return top candidates scoped to active source versions; do not add lexical search, RRF, or reranking.
- **Dependencies:** BL-014, BL-016.
- **Acceptance criteria:** Only indexed active-version chunks are returned; query result includes score and citation metadata; an indexed replacement can be filtered by active state.
- **Implementation notes:** Use a configurable top-K and database-side filtering; retain ordered candidate IDs in trace-ready result objects.
- **Automated tests:** Integration tests seed vectors and prove ordering, inactive-version exclusion, metadata filtering, and empty result behavior.
- **Manual verification:** Ask two representative queries against fixture content and inspect returned headings/pages.
- **Risks or open questions:** pgvector index tuning should wait for corpus-size measurements rather than guessed production parameters.

### BL-018 — Implement cited/abstained SSE chat endpoint

- **Goal and user value:** Deliver the first public, grounded chatbot interaction.
- **Scope / non-scope:** Validate widget key/origin stub, call embedding/retrieval/generation, enforce context budget, stream named SSE events, persist trace/message; do not add rate limiting, rewriting, reranking, or feedback.
- **Dependencies:** BL-002, BL-013, BL-014, BL-017.
- **Acceptance criteria:** A supported question streams deltas then citations/completion; no candidates produce abstention/handoff; provider error produces one safe terminal error event.
- **Implementation notes:** Limit history and context to configured bounds; construct generation prompt with explicit grounded-only instruction; do not leak internal chunk IDs to the widget.
- **Automated tests:** Endpoint tests assert event order, citation fields, abstention, invalid input, provider timeout, and trace persistence using fake adapters.
- **Manual verification:** Use `curl`/SSE client against development Cloud Run with one supported and one unsupported question.
- **Risks or open questions:** Initial confidence threshold needs calibration from early golden-set cases rather than a hard-coded universal score.

### BL-019 — Build the minimal embeddable chat widget

- **Goal and user value:** Let a website visitor use the chat service without integrating a full application.
- **Scope / non-scope:** Build a script-loaded React custom element with Shadow DOM, launcher, conversation state, streamed output, citations, abstention card, and keyboard basics; do not build widget branding editor or analytics.
- **Dependencies:** BL-002, BL-018.
- **Acceptance criteria:** Widget installs through one script and `<support-chat>` tag; host CSS does not alter widget layout; SSE text renders incrementally; citations are keyboard accessible.
- **Implementation notes:** Follow the supplied widget design: indigo header/actions, white/slate body, focus-visible launcher, mobile-friendly width, and support handoff card.
- **Automated tests:** Component tests cover launcher/open/close, SSE reducer, citation rendering, error/abstention, and Shadow DOM isolation where supported.
- **Manual verification:** Embed the bundle in a plain test page and a hostile-CSS page at desktop and mobile widths.
- **Risks or open questions:** Select CDN/versioning strategy before distributing beyond the development test origin.

### BL-020 — Deploy and verify the M1 vertical slice

- **Goal and user value:** Prove the real end-to-end flow works in the same cloud shape that later releases will use.
- **Scope / non-scope:** Deploy API/widget test assets, configure development widget/origin, seed a test model configuration, and add an E2E smoke run; do not expose a production public service.
- **Dependencies:** BL-005, BL-011 through BL-019.
- **Acceptance criteria:** An authenticated admin uploads Markdown; development worker/index path makes it searchable; a browser on approved origin gets streamed cited answer and unsupported-question abstention.
- **Implementation notes:** Record deployment revision, active model configuration, and fixture source version in the smoke report.
- **Automated tests:** Browser E2E test runs against development environment on demand/approved CI environment.
- **Manual verification:** Demonstrate the two-question flow from the supplied widget design on the approved test origin.
- **Risks or open questions:** Development environment billing needs an owner and budget alert before continuous use.

## M2 — Admin content operations

### BL-021 — Create the authenticated admin portal shell

- **Goal and user value:** Give administrators a usable, consistent control-plane entry point.
- **Scope / non-scope:** Implement Supabase sign-in/sign-out, authenticated route guard, app shell, navigation, and design tokens; do not implement source or job data screens.
- **Dependencies:** BL-011, BL-019.
- **Acceptance criteria:** Unauthenticated visitors are redirected to sign-in; authenticated users see navigation for Sources, Jobs, Widget, Providers, Conversations, and Evaluation; sign-out clears access.
- **Implementation notes:** Match the supplied admin design’s white/slate layout, indigo active state, responsive sidebar behavior, and visible focus states.
- **Automated tests:** Route guard and navigation component tests cover signed-in/out states and keyboard focus order.
- **Manual verification:** Sign in with development account, navigate by keyboard, and inspect desktop/narrow layouts.
- **Risks or open questions:** Supabase redirect URLs must be environment-specific and Terraform/secret configuration aligned.

### BL-022 — Build source list and upload workflow

- **Goal and user value:** Let admins upload and understand the status of knowledge sources without using API tools.
- **Scope / non-scope:** Implement source list, upload form, file validation feedback, and source-version status polling; do not add PDF/URL input or retry actions.
- **Dependencies:** BL-015, BL-021.
- **Acceptance criteria:** Admin can upload TXT/Markdown, sees queued/processing/indexed/failed state and heading/type/timestamp; API errors display actionable safe feedback.
- **Implementation notes:** Use server-issued upload flow from BL-015 and do not put cloud credentials in browser code.
- **Automated tests:** UI tests cover valid/invalid selection, upload progress, status states, and failure message rendering.
- **Manual verification:** Upload one valid and one invalid file through the portal and verify Cloud Storage/API records.
- **Risks or open questions:** Large-file progress semantics depend on chosen signed/proxied upload design.

### BL-023 — Introduce asynchronous ingestion jobs and status API

- **Goal and user value:** Keep uploads responsive and let administrators see reliable background processing state.
- **Scope / non-scope:** Add Cloud Tasks enqueueing, worker authentication, idempotency keys, job status endpoint, attempt records, and bounded retry classification; do not add PDF/URL extractors.
- **Dependencies:** BL-003, BL-010, BL-015, BL-016, BL-017.
- **Acceptance criteria:** Duplicate task delivery does not duplicate chunks; transient worker error retries; terminal failure is visible with an administrator-safe error reason.
- **Implementation notes:** Task payload contains source-version ID only; worker loads state from database and locks/claims jobs safely.
- **Automated tests:** Worker tests cover duplicate delivery, retryable/non-retryable failure, state transitions, and stale task handling.
- **Manual verification:** Induce one transient and one invalid-source failure in development and inspect Cloud Tasks/job records.
- **Risks or open questions:** Cloud Tasks retry configuration must align with provider quotas and ingestion cost controls.

### BL-024 — Implement safe source replacement and retry controls

- **Goal and user value:** Let admins update documentation without stale answers or downtime after a failed replacement.
- **Scope / non-scope:** Create re-ingest endpoint/UI action, activation transaction, prior-version preservation, old-chunk removal, and retry action; do not add embedding-model-wide re-indexing.
- **Dependencies:** BL-022, BL-023.
- **Acceptance criteria:** Successful replacement removes all old active chunks; failed replacement leaves prior version answerable; retry creates a traceable new attempt without duplicate active chunks.
- **Implementation notes:** Never append replacement chunks to the active version; use source document stable ID and version-scoped chunk filters.
- **Automated tests:** Integration tests prove successful replacement, failed replacement rollback behavior, and duplicate retry safety.
- **Manual verification:** Replace a document whose answer changes; confirm old wording disappears only after new version indexes.
- **Risks or open questions:** Transaction approach must handle database state and external vector embedding calls without falsely declaring activation.

### BL-025 — Add PDF extraction and structure-aware table handling

- **Goal and user value:** Support the common documentation format while preserving page and table meaning for citations.
- **Scope / non-scope:** Add a selected PDF extractor, page/heading metadata, table row-to-chunk strategy, and clear extraction errors; do not support scanned-image OCR unless the selected extractor provides it explicitly.
- **Dependencies:** BL-016, BL-023, BL-024.
- **Acceptance criteria:** Text PDF chunks cite page number; table rows include column headers; malformed or unsupported PDF fails safely without replacing active content.
- **Implementation notes:** Benchmark extractor on fixture PDFs before locking it in; store extractor version and extraction warnings.
- **Automated tests:** Fixtures cover multi-page prose, tables, repeated headers, malformed PDF, and empty extraction.
- **Manual verification:** Upload a representative product PDF and inspect page-aware chunks and answer citation.
- **Risks or open questions:** Scanned PDFs may require Document AI/OCR, which is a separate cost and scope decision.

### BL-026 — Add exact seed-URL ingestion

- **Goal and user value:** Let admins index a public documentation page without copying its text manually.
- **Scope / non-scope:** Fetch one explicitly submitted public URL, enforce URL safety, extract readable HTML, persist canonical URL/metadata, and queue ingestion; do not follow links, crawl domains, or read sitemaps.
- **Dependencies:** BL-023, BL-024.
- **Acceptance criteria:** Allowed public HTML page indexes as one source; redirects/canonical URL are recorded; private network, unsupported protocol, and oversized response are rejected.
- **Implementation notes:** Implement SSRF defenses, response size/time limits, content-type allowlist, and an explicit user-agent; preserve source URL for citations.
- **Automated tests:** URL-client tests cover allowed page, redirects, timeout, non-HTML, private IP, DNS rebinding guard, and HTML extraction fixture.
- **Manual verification:** Add one public test page and confirm only that URL is fetched and cited.
- **Risks or open questions:** Website terms/robots policy and recrawl cadence are deferred; v1 is admin-triggered only.

## M3 — Retrieval quality and observability

### BL-030 — Persist structured retrieval and provider traces

- **Goal and user value:** Let support owners diagnose bad answers with evidence rather than guesswork.
- **Scope / non-scope:** Persist request stages, candidates/scores, selected chunks, provider/model, tokens, estimated cost, errors, and latency; do not add portal analytics charts.
- **Dependencies:** BL-010, BL-018.
- **Acceptance criteria:** Every chat terminal state has one trace with stage timings and profile/version fields; sensitive credentials and raw headers are absent.
- **Implementation notes:** Use correlated request/job IDs and a redaction layer shared by API and worker logs.
- **Automated tests:** Trace tests assert required fields, ordering, redaction, and error-path persistence.
- **Manual verification:** Inspect trace for supported, abstained, and provider-error chat requests in development.
- **Risks or open questions:** Decide conversation/trace retention policy before opening public traffic.

### BL-031 — Create golden-set schema and evaluation runner

- **Goal and user value:** Make quality changes measurable before they reach visitors.
- **Scope / non-scope:** Add versioned evaluation cases, supporting chunk annotations, runner orchestration, per-case output, and aggregate metric calculation; do not build admin editing UI yet.
- **Dependencies:** BL-010, BL-017, BL-030.
- **Acceptance criteria:** A fixture dataset runs against a configured profile and reports Recall@10, citation coverage, latency, error rate, and case artifacts.
- **Implementation notes:** Keep LLM-as-judge faithfulness/relevance behind a pluggable evaluator so deterministic retrieval metrics still run offline.
- **Automated tests:** Fixture tests verify metric calculations, missing annotation handling, repeatable seeded execution, and failed case isolation.
- **Manual verification:** Run a five-case fixture dataset and inspect saved per-case retrieval evidence.
- **Risks or open questions:** Human-approved answer/faithfulness rubric must be defined before treating judge results as release gates.

### BL-032 — Add PostgreSQL lexical retrieval and RRF fusion

- **Goal and user value:** Improve recall for exact product names, codes, and terms that vector search can miss.
- **Scope / non-scope:** Populate full-text vectors, run dense and lexical searches in parallel, and fuse ranked lists with RRF; do not add reranking or query rewriting.
- **Dependencies:** BL-017, BL-031.
- **Acceptance criteria:** Hybrid candidate list contains exact-term matches missed by dense-only fixtures; RRF scoring is deterministic and traceable.
- **Implementation notes:** Keep top-K and RRF constant configurable; capture per-channel rank/score in trace.
- **Automated tests:** Database integration tests cover exact code, paraphrase, tie, duplicate result, inactive version, and no lexical match.
- **Manual verification:** Compare vector-only and hybrid results for curated product-code and paraphrase questions.
- **Risks or open questions:** PostgreSQL full-text ranking may not equal BM25 exactly; document this implementation choice and benchmark before replacing it.

### BL-033 — Add cross-encoder reranking adapter and stage

- **Goal and user value:** Improve precision by selecting the most relevant chunks from the hybrid candidate set.
- **Scope / non-scope:** Define reranker adapter, rerank top 30 candidates, select top 3–5, and trace scores; do not ship a provider-management UI.
- **Dependencies:** BL-012, BL-032, BL-031.
- **Acceptance criteria:** Reranking receives no more than 30 candidates, changes selection deterministically with fake adapter, and is bypassable by profile configuration.
- **Implementation notes:** Apply strict timeout/circuit-breaker behavior; if profile permits, fall back to fused ranking and record the fallback.
- **Automated tests:** Contract tests cover candidate cap, ordering, timeout fallback, unsupported adapter, and trace fields.
- **Manual verification:** Run golden set with reranking enabled/disabled and inspect quality/latency comparison.
- **Risks or open questions:** Choose managed versus self-hosted reranker after real latency/cost measurements.

### BL-034 — Add query rewriting and context-budget selection

- **Goal and user value:** Improve recall for typos and ambiguous phrasing without bloating prompts or latency unpredictably.
- **Scope / non-scope:** Generate up to three query variants, merge deduplicated candidates, enforce 2,000-token context and 3–5 selected chunks; do not add context-compression model calls.
- **Dependencies:** BL-013, BL-032, BL-033, BL-031.
- **Acceptance criteria:** Rewrite is feature/profile controlled; variants are bounded; selected context never exceeds budget; original query remains in trace.
- **Implementation notes:** Use a low-cost configured generation role; do not rewrite prompts containing only identifiers when a rule can preserve them.
- **Automated tests:** Tests cover typo variant, duplicate variants, disabled rewrite, context over-budget, one large parent chunk, and trace output.
- **Manual verification:** Compare representative ambiguous and code-heavy questions with rewriting on/off.
- **Risks or open questions:** Query rewrite adds latency/cost; retain a configuration switch until evaluation proves net benefit.

### BL-035 — Add citation, abstention, and feedback diagnostics UI

- **Goal and user value:** Build visitor trust and give support owners a direct signal about answer quality.
- **Scope / non-scope:** Improve source citation presentation, configurable handoff, thumbs feedback, and admin trace/conversation detail view; do not add human-agent live chat.
- **Dependencies:** BL-019, BL-021, BL-030.
- **Acceptance criteria:** Visitor can open each citation; abstention uses configured handoff; feedback attaches to message/trace; admin can inspect candidates and timing without secrets.
- **Implementation notes:** Keep citation labels human-readable—document title plus page/heading—and sanitize external source links.
- **Automated tests:** Widget/admin tests cover citations, keyboard use, feedback submission, safe link handling, and trace redaction.
- **Manual verification:** Complete a supported, unsupported, and negative-feedback flow in browser.
- **Risks or open questions:** Determine whether visitor feedback requires consent/privacy notice in the deployment region.

## M4 — Provider and model experimentation

### BL-036 — Add provider connection domain model and Secret Manager integration

- **Goal and user value:** Let admins use approved providers without exposing credentials or editing deployments.
- **Scope / non-scope:** Add provider connection metadata, Secret Manager create/reference flow, and Vertex service-identity connection type; do not build provider-specific model selection UI.
- **Dependencies:** BL-003, BL-010, BL-011.
- **Acceptance criteria:** Connection stores only a secret reference; secret cannot be read back through API; Vertex connection needs no copied API key; audit event records changes.
- **Implementation notes:** Support provider types Vertex AI, OpenAI, and Anthropic through approved adapters only; restrict external endpoint overrides.
- **Automated tests:** API/repository tests prove secret redaction, authorization, validation, and audit persistence using mocked Secret Manager.
- **Manual verification:** Create one development external-provider connection and verify the returned payload contains no credential value.
- **Risks or open questions:** External-provider data residency and commercial terms require review before production use.

### BL-037 — Implement versioned model profiles and role validation

- **Goal and user value:** Make model selection explicit, reproducible, and safe to compare.
- **Scope / non-scope:** Persist draft/approved/active profiles with four roles, limits, fallback order, and change notes; validate capability/secret availability; do not promote profiles or run evaluation.
- **Dependencies:** BL-012, BL-036.
- **Acceptance criteria:** A profile cannot assign a generation-only model to embeddings or reference unhealthy connection; exactly one active profile invariant is enforceable at database level.
- **Implementation notes:** Initial profile enables generation and embeddings; rewrite/rerank roles are nullable until M3 capabilities are configured.
- **Automated tests:** Tests cover invalid role assignment, unavailable secret, default profile resolution, version cloning, and one-active constraint.
- **Manual verification:** Create/clone a draft profile through authenticated API and inspect resolved role configuration.
- **Risks or open questions:** Model capability catalog refresh strategy needs a provider-adapter convention.

### BL-038 — Build provider and model-profile admin screens

- **Goal and user value:** Let an admin configure and review models in the portal rather than through internal tooling.
- **Scope / non-scope:** Implement provider cards/status, secret-entry form, model-profile editor, role assignments, limits, change notes, and draft status; do not implement evaluation comparison or promotion action.
- **Dependencies:** BL-021, BL-036, BL-037.
- **Acceptance criteria:** UI never displays stored secret; invalid capability selection shows a clear error; admin can create a draft profile matching the design system.
- **Implementation notes:** Use the supplied portal visual direction: visible status badges, readable role grouping, and destructive action confirmation.
- **Automated tests:** UI tests cover form validation, hidden secret value after save, capability filtering, and keyboard navigation.
- **Manual verification:** Create a draft that changes generation model and verify it is not active for a new chat.
- **Risks or open questions:** Provider connection creation should be audited and may need a second confirmation before production access.

### BL-039 — Run profile evaluations and compare results

- **Goal and user value:** Allow evidence-based provider/model choices instead of subjective chat testing.
- **Scope / non-scope:** Connect model profile to golden-set runner, save comparison against active profile, and render metrics/case drill-down; do not promote or re-index embeddings.
- **Dependencies:** BL-031, BL-037, BL-038.
- **Acceptance criteria:** Draft evaluation records profile/dataset versions and metrics; UI compares quality, latency, error rate, and cost; failed runs are visible and retryable.
- **Implementation notes:** Ensure test prompts/document content are redacted from external model logs according to configured privacy policy.
- **Automated tests:** Service/UI tests cover run lifecycle, comparison math, error state, stale result handling, and profile immutability during run.
- **Manual verification:** Evaluate a draft generation profile and inspect a per-case difference from active profile.
- **Risks or open questions:** LLM-judge metrics add their own model cost and variance; report confidence/limitations beside them.

### BL-040 — Implement embedding-change re-index plan and execution

- **Goal and user value:** Prevent an embedding experiment from silently mixing incompatible vectors and degrading retrieval.
- **Scope / non-scope:** Detect embedding role change, estimate affected sources, create re-index plan/jobs, isolate new vectors, and require completed evaluation before promotion; do not optimize bulk throughput beyond safe batching.
- **Dependencies:** BL-023, BL-024, BL-037, BL-039.
- **Acceptance criteria:** Embedding-changing profile cannot promote without completed re-index/evaluation; old active profile continues serving during work; failure leaves current profile/index intact.
- **Implementation notes:** Re-index by source version/profile generation and maintain explicit vector model metadata; use Cloud Tasks with resumable chunks.
- **Automated tests:** Integration tests cover change detection, promotion block, successful cutover, partial failure, retry, and no mixed-vector retrieval.
- **Manual verification:** Change embedding model in development, observe plan/estimate, force one failure, then complete a successful re-index and promotion.
- **Risks or open questions:** Large corpus re-index cost and duration need quota/budget controls before broad usage.

### BL-041 — Add atomic profile promotion and rollback

- **Goal and user value:** Let administrators safely put a proven experiment into production and recover quickly.
- **Scope / non-scope:** Add promotion policy enforcement, one-active-profile transaction, rollback to approved profile, audit events, and portal actions; do not add multi-step approval roles.
- **Dependencies:** BL-037, BL-039, BL-040.
- **Acceptance criteria:** Promotion rejects missing/failed/regressed evaluation and incomplete embedding re-index; new requests resolve the new active profile; in-flight request retains its resolved profile; rollback is auditable.
- **Implementation notes:** Apply 5% regression rule to configured core metrics; provide confirmation containing profile version, model assignments, and evaluation summary.
- **Automated tests:** Transaction tests cover concurrent promotion, active-profile invariant, rejection cases, in-flight resolution snapshot, and rollback audit record.
- **Manual verification:** Promote a non-embedding draft, send a chat, roll back, and confirm profile IDs in traces.
- **Risks or open questions:** A one-role admin model permits self-approval; introduce separation of duties only if organizational policy requires it.

## M5 — Production readiness

### BL-050 — Enforce widget origin, API rate, and input protections

- **Goal and user value:** Protect the public chatbot from unauthorized embedding, abuse, and avoidable cost spikes.
- **Scope / non-scope:** Implement allowed-origin enforcement, widget-key validation, request/history/input limits, and per-widget/IP rate limiting; do not add bot-management vendor integration.
- **Dependencies:** BL-018, BL-019, BL-030.
- **Acceptance criteria:** Unapproved origin/key is rejected; configured limits return safe rate/validation errors; allowed test origin remains functional.
- **Implementation notes:** Treat `Origin` as a browser control, not sole authorization; log hashed/rate-safe identity data only.
- **Automated tests:** Tests cover absent/spoofed origin, key mismatch, rate window boundary, payload limit, and allowed origin.
- **Manual verification:** Embed widget on approved and unapproved development pages and exercise rate threshold.
- **Risks or open questions:** Proxy/CDN IP forwarding must be configured correctly for reliable per-IP limiting.

### BL-051 — Add provider resilience controls

- **Goal and user value:** Avoid a failing model provider making the public widget hang or repeatedly amplify errors.
- **Scope / non-scope:** Implement timeout budgets, retry policy, circuit breaker, configured fallback, and user-safe terminal responses; do not promise zero downtime across all providers.
- **Dependencies:** BL-013, BL-033, BL-037.
- **Acceptance criteria:** Timeout/error follows retry classification; open circuit avoids new failing requests; permitted fallback is traceable; widget receives a finite friendly terminal state.
- **Implementation notes:** Set separate budgets for embeddings, rewrite, rerank, and generation; do not retry non-idempotent streaming after output begins.
- **Automated tests:** Fake-provider tests cover timeout, rate limit, circuit open/half-open, fallback success, and streaming partial failure.
- **Manual verification:** Disable development provider access temporarily and observe response, trace, alert signal, and recovery.
- **Risks or open questions:** Fallback model output may differ in quality; profile evaluation must include fallback behavior where enabled.

### BL-052 — Build operational dashboards and alerts

- **Goal and user value:** Let operators detect degraded answers, ingestion failures, and unexpected cost before users report them.
- **Scope / non-scope:** Define metrics/log-based dashboards and alerts for latency, error, abstention, retrieval quality, ingestion, provider health, cost estimate, and queue depth; do not build a custom analytics warehouse.
- **Dependencies:** BL-030, BL-031, BL-051.
- **Acceptance criteria:** Dashboard shows API/worker p50/p95, error, queue, provider, and evaluation signals; alert routes trigger from controlled fault fixtures.
- **Implementation notes:** Use Cloud Monitoring labels keyed by environment, service, provider, and profile version; avoid high-cardinality visitor identifiers.
- **Automated tests:** Infrastructure/config tests validate dashboard/alert resource syntax; synthetic metric fixture validates alert query logic where supported.
- **Manual verification:** Trigger a development ingestion failure and provider timeout, then confirm the expected dashboards/alerts update.
- **Risks or open questions:** Choose alert channel ownership and on-call expectations before production launch.

### BL-053 — Define retention, backup, and restore operations

- **Goal and user value:** Protect knowledge and operational evidence while avoiding indefinite retention of visitor content.
- **Scope / non-scope:** Document/configure source, conversation, trace, and audit retention; configure Cloud SQL backups and Cloud Storage lifecycle; perform non-production restore drill; do not implement legal hold system.
- **Dependencies:** BL-003, BL-010, BL-030.
- **Acceptance criteria:** Retention periods are explicit; backups are enabled; a restore into isolated non-production environment verifies sources, chunks, and active profile consistency.
- **Implementation notes:** Separate raw document storage lifecycle from metadata/trace retention and document deletion paths.
- **Automated tests:** Terraform/policy tests assert backup/lifecycle configuration; post-restore integrity script checks key row counts and foreign-key consistency.
- **Manual verification:** Execute and document a restore drill with timestamp, duration, and result.
- **Risks or open questions:** Final retention and privacy notice require product/legal review for actual deployment jurisdictions.

### BL-054 — Complete widget accessibility and compatibility audit

- **Goal and user value:** Ensure visitors can use the support experience with keyboards, screen readers, zoom, and narrow screens.
- **Scope / non-scope:** Audit/fix focus order, labels, live announcements, contrast, reduced motion, 200% zoom, and current evergreen browser behavior; do not support obsolete browsers without a documented requirement.
- **Dependencies:** BL-019, BL-035, BL-050.
- **Acceptance criteria:** No critical automated accessibility violations; launcher/chat/citations/handoff work by keyboard and screen reader; mobile layout remains usable.
- **Implementation notes:** Maintain focus when opening/closing, announce streaming completion sensibly, and avoid reading each token as a separate live-region event.
- **Automated tests:** Run component accessibility tests plus browser checks for focus and responsive viewport snapshots.
- **Manual verification:** Perform keyboard-only and screen-reader smoke tests at desktop and mobile widths on hostile host CSS page.
- **Risks or open questions:** Screen-reader coverage needs named browser/OS combinations in the launch test matrix.

### BL-055 — Run load, resilience, and release-gate suite

- **Goal and user value:** Establish confidence that launch traffic and common failures do not compromise responsiveness or groundedness.
- **Scope / non-scope:** Create reproducible load scenarios, failure-injection scripts, golden-set release gate, and release checklist; do not claim capacity beyond measured results.
- **Dependencies:** BL-020, BL-031 through BL-035, BL-050 through BL-054.
- **Acceptance criteria:** Documented concurrent-stream workload meets agreed p50/p95/error targets; provider/worker/database failure scenarios behave safely; release fails on >5% quality regression.
- **Implementation notes:** Run load tests only in development/staging with capped provider spend; include a no-live-model fixture mode for CI speed.
- **Automated tests:** Scheduled/per-release suite executes golden set, contract/integration tests, selected load smoke, and failure fixtures; stores report artifact.
- **Manual verification:** Review a release candidate report, execute go/no-go checklist, and demonstrate one controlled rollback.
- **Risks or open questions:** Final traffic target, latency SLO, and monthly model budget must be set before declaring production capacity.
