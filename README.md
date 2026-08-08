# Production RAG Support Chatbot

This repository is a polyglot monorepo for the production RAG support chatbot described in [the product brief](docs/product-brief.md) and [architecture](docs/architecture.md).

## Prerequisites

A fresh checkout requires:

- Git.
- [mise](https://mise.jdx.dev/getting-started.html), which installs the pinned Node.js, pnpm, Python, uv, and Terraform versions.
- Docker Desktop or another Docker-compatible daemon. Migration integration tests
  use a pinned PostgreSQL 16 image with pgvector.

No globally installed language runtimes or package managers are used by repository commands.

## Bootstrap a fresh checkout

```sh
git clone <repository-url>
cd <repository-directory>
mise trust
mise install
mise run bootstrap
mise run check
```

Both dependency managers use committed lockfiles. `bootstrap` fails rather than silently changing them.

## Common commands

| Command                           | Purpose                                                    |
| --------------------------------- | ---------------------------------------------------------- |
| `mise run bootstrap`              | Install all locked JavaScript and Python dependencies.     |
| `mise run format`                 | Format TypeScript, Python, and Terraform workspaces.       |
| `mise run format:check`           | Verify formatting without changing files.                  |
| `mise run lint`                   | Run ESLint and Ruff.                                       |
| `mise run typecheck`              | Run TypeScript and Python type checkers.                   |
| `mise run test`                   | Run workspace tests and Terraform validation.              |
| `mise run check`                  | Run every non-mutating quality gate used by CI.            |
| `mise run test:api-image`         | Build and smoke-test the API container health endpoint.    |
| `mise run db:migrate`             | Upgrade the configured database to the migration head.     |
| `mise run db:downgrade`           | Downgrade the configured database to the base.             |
| `mise run db:schema-probe`        | Migrate and probe the core schema in disposable Postgres.  |
| `mise run test:admin-auth`        | Test JWT verification and administrator subject mapping.   |
| `mise run test:providers`         | Test provider adapter contracts and deterministic fakes.   |
| `mise run providers:example`      | Swap fake adapters through provider-neutral orchestration. |
| `mise run test:vertex`            | Test Vertex generation and its restricted smoke boundary.  |
| `mise run vertex:smoke`           | Run the explicit, billed live Vertex streaming smoke.      |
| `mise run test:vertex-embedding`  | Test batching, retries, tasks, and vector validation.      |
| `mise run vertex:embedding-smoke` | Run billed embeddings and a rolled-back pgvector probe.    |

## Database migrations

Migrations are owned by the API workspace but run only as an explicit one-shot
command. API startup must never invoke them.

For local development, start any PostgreSQL 16 database with pgvector and provide
a SQLAlchemy URL:

```sh
export DATABASE_URL='postgresql+pg8000://postgres:password@127.0.0.1:5432/support_rag'
mise run db:migrate
mise run db:migrate
```

The second command is intentionally a no-op. To verify the complete lifecycle
against the repository's pinned, disposable Docker image:

```sh
mise run test:migrations
```

The test starts and removes its own container. The migration runner never logs
`DATABASE_URL`; it reports only the applied revision, installed vector version,
and a harmless vector-cast probe.

To inspect the POR-35 core schema through its async repositories, run:

```sh
mise run db:schema-probe
```

This command starts the pinned pgvector PostgreSQL image, migrates it to the
current head, inserts one widget/source/version/chunk/conversation/message/trace
chain, prints only table row counts, rolls the fixture transaction back, verifies
every count returned to zero, and removes the container.

Cloud execution uses `INSTANCE_CONNECTION_NAME`, `DB_NAME`, and `DB_USER`.
Terraform supplies these to a passwordless IAM-authenticated Cloud Run job. See
[`infra/terraform/README.md`](infra/terraform/README.md) for the two-phase image
and job deployment.

## Development delivery

Pull requests run the complete locked quality gate. After a merge, GitHub Actions
builds the API and migration images, tags them with the full commit SHA in an
immutable Artifact Registry repository, and retains a digest manifest.

Development deployment is a separate, manually triggered workflow protected by
the GitHub `development` environment. It accepts a full commit SHA from `main`,
resolves both immutable digests, runs the migration job, deploys the API
revision, calls `/health`, and retains the resulting revision, image, and
smoke-test metadata for 90 days.

GitHub authenticates to GCP through short-lived Workload Identity Federation
credentials. No service-account key or cloud credential belongs in GitHub
secrets. See [`infra/terraform/README.md`](infra/terraform/README.md) for the
one-time repository variables, approval gate, and operator procedure.

## Verify Supabase administrator identity

POR-36 verifies hosted Supabase access tokens locally against the project's
asymmetric JWKS endpoint. The API checks signature, issuer, audience, expiration,
authenticated role, non-anonymous status, and UUID subject before it creates the
single `admin` mapping in `rag_app.admin_user`. It never accepts a browser-supplied
role, a Supabase service-role key, or a legacy shared JWT secret.

The API reads one JSON object from `SUPABASE_AUTH_CONFIG`:

```json
{
  "project_url": "https://PROJECT_REF.supabase.co",
  "audience": "authenticated",
  "jwks_cache_ttl_seconds": 600
}
```

For local verification, migrate a disposable database, use an asyncpg
`DATABASE_URL`, start the API, and supply the config above through the
environment. Obtain a short-lived access token from a development email/password
session, then run:

```sh
export SUPABASE_ACCESS_TOKEN='short-lived development access token'
curl --fail-with-body \
  --header "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  http://127.0.0.1:8000/admin/auth-check
curl --include http://127.0.0.1:8000/admin/auth-check
unset SUPABASE_ACCESS_TOKEN
```

The authenticated call returns the local admin ID, Supabase subject, and the
literal role `admin`. The second call returns a safe `401` envelope. Never commit
the config, database URL, access token, publishable key, email, or password.
Development Cloud Run configuration and Secret Manager delivery are documented
in [`infra/terraform/README.md`](infra/terraform/README.md).

## Verify Vertex generation

The development API uses the Google Gen AI SDK in Vertex mode and authenticates
with its attached Cloud Run service identity. Terraform supplies only non-secret
project, location, model, and per-million-token input/output price values; no
provider API key is needed. Requiring explicit prices prevents unknown pricing
from being reported as free usage. Run deterministic tests with
`mise run test:vertex`.

After applying the reviewed Terraform change and deploying the merged API image,
an authenticated administrator can invoke the development-only streaming probe:

```sh
curl --no-buffer --fail-with-body \
  --request POST \
  --header "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}" \
  "${API_URL}/admin/ai/vertex-generation-smoke"
```

The probe has a fixed support prompt, is absent outside development, and logs
only safe provider/model/location, token, cost-estimate, and normalized status
metadata. It is not the public chat endpoint.

## Verify Vertex embeddings

One immutable configuration supplies `text-embedding-005` and dimension `768`
to both API query embeddings and worker document embeddings. The adapter sends
the corresponding `RETRIEVAL_QUERY` or `RETRIEVAL_DOCUMENT` task type, batches at
the configured online-request limit, disables silent truncation, retries only
recognized transient idempotent batch failures, and rejects over-budget input
before any billed batch. Source versions record the provider, model, and
dimension in their metadata; chunk insertion requires that profile before
accepting embeddings and enforces its recorded dimension before vectors are
indexed.

Run the credential-free suite with `mise run test:vertex-embedding`. For the
explicit billed proof, authenticate Application Default Credentials and set the
non-secret values shown below. The command starts disposable pgvector Postgres,
migrates it, calls Vertex once for a document and once for a query, stores the
document vector, verifies its stored dimension, rolls the fixture back, and
removes the database container.

```sh
export RUN_VERTEX_EMBEDDING_INTEGRATION=1
export GOOGLE_CLOUD_PROJECT='development-project-id'
export GOOGLE_CLOUD_LOCATION='europe-west1'
export VERTEX_EMBEDDING_MODEL='text-embedding-005'
export VERTEX_EMBEDDING_DIMENSION='768'
export VERTEX_EMBEDDING_BATCH_SIZE='5'
export VERTEX_EMBEDDING_MAX_ATTEMPTS='3'
export VERTEX_EMBEDDING_INITIAL_RETRY_DELAY_SECONDS='0.25'
export VERTEX_EMBEDDING_MAX_RETRY_DELAY_SECONDS='2'
export VERTEX_EMBEDDING_INPUT_COST_PER_MILLION_CHARACTERS_USD='0.025'
mise run vertex:embedding-smoke
unset RUN_VERTEX_EMBEDDING_INTEGRATION
```

The reported cost is an estimate based on input characters, matching Vertex’s
text-embedding billing unit; normalized token counts come from the provider
response. Neither source text nor query text is logged.

## Workspace layout

| Path                 | Responsibility                                                   |
| -------------------- | ---------------------------------------------------------------- |
| `apps/api`           | FastAPI public and admin API service.                            |
| `apps/worker`        | Asynchronous ingestion worker.                                   |
| `apps/admin`         | Next.js administration portal.                                   |
| `packages/widget`    | Embeddable support-chat web component.                           |
| `packages/contracts` | Shared request, response, and event contracts.                   |
| `packages/providers` | Provider-neutral contracts, fakes, and isolated Vertex adapters. |
| `infra/terraform`    | GCP infrastructure definitions.                                  |

The current placeholders reserve these boundaries; product behavior is added by later issues.

## Verify quality gates reject bad changes

To verify the formatter gate, add trailing or inconsistent formatting to a tracked TypeScript file and run `mise run format:check`. To verify type checking, temporarily add `const invalid: string = 1;` to a TypeScript source file and run `mise run typecheck`. Both commands must fail; restore the file and rerun `mise run check` before committing.
