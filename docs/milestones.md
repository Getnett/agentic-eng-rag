# Milestones: Production RAG Support Chatbot

## Delivery sequence

The milestones prioritize a real, deployable vertical slice before adding retrieval sophistication or administrative breadth. Every milestone ends with a demonstrable outcome and builds on a Terraform-managed GCP development environment.

| Milestone | Outcome | Exit criteria |
| --- | --- | --- |
| M0 — Foundation | Repeatable repository, contracts, and development cloud environment | Terraform creates the required development resources; CI validates formatting, types, tests, and migrations. |
| M1 — Grounded chat vertical slice | A visitor receives a streamed, cited or abstained answer from one uploaded TXT/Markdown source | Real Vertex AI generation and embeddings work on Cloud Run; widget works from an approved test origin. |
| M2 — Admin content operations | Admins manage sources and safe replacement ingestion | Authentication, upload, jobs, TXT/Markdown/PDF/seed URL ingestion, and stale-chunk replacement are operational. |
| M3 — Retrieval quality and observability | Answers are measurable and improved through advanced retrieval | Golden set, lexical+dense RRF, reranking, query rewriting, citations, traces, and quality dashboards are operational. |
| M4 — Model experimentation | Admins safely compare and promote provider/model profiles | Secrets stay protected; profile evaluation, promotion, rollback, and embedding re-index protection work. |
| M5 — Production readiness | Reliable public deployment with documented operations | Security, load, failure, backup/restore, accessibility, release gates, and runbooks are accepted. |

## M0 — Foundation

**Purpose:** establish a repeatable technical base before feature work.

Deliver repository/workspace conventions, shared API contracts, local developer setup, database migration support, CI, and Terraform for a non-production GCP environment. Terraform must provision the Cloud Run services, Cloud SQL, Cloud Storage, Cloud Tasks, Secret Manager, observability hooks, and least-privilege service accounts needed by the first slice.

**Exit demonstration:** a clean environment can be provisioned from Terraform, a health endpoint deploys to Cloud Run, and CI runs contract/unit checks without depending on production credentials.

## M1 — Grounded chat vertical slice

**Purpose:** prove the end-to-end support-answer value and real cloud integration before broadening scope.

Deliver Supabase-backed admin identity verification, TXT/Markdown source upload, private object storage, structure-preserving basic chunking, Vertex AI embedding and generation adapters, pgvector similarity retrieval, a FastAPI SSE chat endpoint, and the React Shadow DOM widget. Use a single active model profile that supports generation and embeddings only. The endpoint must cite selected chunks or abstain with the configured handoff.

**Exit demonstration:** an authenticated admin uploads a small Markdown guide; a visitor on the approved test origin asks a grounded question and sees streamed answer text plus a source citation. An unsupported question receives an abstention. The trace identifies the selected chunks, model profile, latency, and cost estimate.

## M2 — Admin content operations

**Purpose:** let non-engineering users maintain the knowledge base safely.

Add the portal shell and source views, upload/re-ingest workflows, Cloud Tasks worker, source/version/job state, retry/error visibility, PDF extraction, and exact seed-URL retrieval. Replacing a source must never leave its previous chunks active. Keep sitemap and domain crawling deferred.

**Exit demonstration:** an admin replaces an indexed PDF and the old answer is no longer retrievable; failed ingestion retains the last indexed version and exposes a useful error/retry control.

## M3 — Retrieval quality and observability

**Purpose:** replace intuition with measurable retrieval and answer quality.

Introduce golden-set management and evaluation runner, structured traces, PostgreSQL full-text lexical retrieval, RRF fusion, cross-encoder reranking, query rewriting, context-budget enforcement, and citation/abstention diagnostics. Enable these progressively behind configuration so they can be compared against the M1 baseline.

**Exit demonstration:** an evaluation run compares vector-only and advanced retrieval profiles, reports all core metrics, and blocks a quality regression larger than 5%.

## M4 — Model experimentation

**Purpose:** enable safe provider/model experimentation without giving secrets or production stability to a browser form.

Add provider connection adapters and Secret Manager storage, versioned model profiles, provider health/capability validation, profile evaluation and comparison, atomic promotion/rollback, and the embedding-model re-index workflow. Vertex AI remains the initial configured provider; OpenAI and Anthropic are supported through adapters.

**Exit demonstration:** an admin tests a draft generation model against the golden set, promotes it, verifies newly started chats use it, and rolls back. An embedding change cannot be promoted until re-index and evaluation succeed.

## M5 — Production readiness

**Purpose:** make the public service safe to operate under expected traffic and failure modes.

Complete rate limiting, provider fallback/circuit breakers, operational dashboards and alerts, access review, data-retention decisions, backup/restore verification, load and resilience testing, widget accessibility audit, CI/CD release gates, and maintenance runbooks.

**Exit demonstration:** a staged release passes load, failure, accessibility, security, and golden-set checks; the team restores a non-production backup and follows the incident/runbook path successfully.

## Release gates

| Gate | Required before |
| --- | --- |
| Terraform plan/apply review and migration test | Any shared-environment deployment |
| Contract, unit, and focused integration tests | Merge to main |
| Manual cross-origin widget check | Widget release |
| Golden-set quality run with no >5% regression | Production release or model promotion |
| Accessibility and load checks | Public production launch |
| Backup/restore drill and operational runbook review | M5 completion |
