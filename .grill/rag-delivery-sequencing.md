# Grill: RAG delivery sequencing
Date: 2026-07-19

## Intent
Deliver an implementation plan for a production RAG support chatbot that proves real user value and production integration risks early, while keeping the first coding tasks small and independently mergeable.

## Constraints
- Do not write application code during this planning task.
- Use the existing product brief and design references as the source of truth.
- The first usable slice must run against a real managed model provider in a non-production GCP project.
- Infrastructure must be reproducible rather than configured manually.

## Key decisions
- Decision: Start with a thin vertical slice: an authenticated admin uploads TXT/Markdown content and the widget streams a cited or abstained response on an approved test domain. Reason: validates the core customer value before broader formats and portal workflows. Alternative considered: build all admin and ingestion features first.
- Decision: Use real Vertex AI in the development GCP project. Reason: validates IAM, latency, cost, and streaming integration. Alternative considered: deterministic fake-only provider.
- Decision: First slice uses generation and embeddings only. Reason: build a golden-set baseline before paying the latency and cost of query rewriting and reranking. Alternative considered: ship the complete advanced retrieval pipeline immediately.
- Decision: Deploy the slice to Cloud Run with development Cloud SQL and Cloud Storage. Reason: validate GCP networking, CORS, and service identities before production. Alternative considered: local-only validation.
- Decision: Provision environments with Terraform from the first deployment. Reason: prevent configuration drift and make later production promotion repeatable. Alternative considered: manual GCP console setup.

## Surfaced assumptions
- The initial corpus is small enough for PostgreSQL with pgvector.
- Vertex AI credentials are available to the development GCP project.
- The widget can be hosted on a controlled test origin for CORS and allowed-domain testing.
- Supabase remains the chosen admin email/password authentication provider.

## Out of scope
- Multi-tenancy, billing, SSO, GraphRAG, agentic workflows, full-site crawling, live-data answers, and regulated-domain controls.
