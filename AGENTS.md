# Repository instructions for coding agents

These instructions apply to the entire repository. A more specific nested `AGENTS.md`, if introduced later, takes precedence for files in its directory.

## Source of truth

Read the current issue and the relevant repository documents before changing code:

- `docs/product-brief.md` defines product intent and v1 boundaries.
- `docs/architecture.md` defines system boundaries, data flow, and technology choices.
- `docs/milestones.md` defines delivery order and release gates.
- `docs/backlog.md` defines issue scope, dependencies, acceptance criteria, and verification.

When these sources conflict, stop and surface the conflict instead of silently choosing one.

## Change discipline

- Implement only the requested issue. Do not begin dependent or later-milestone work.
- Preserve unrelated user changes and keep each change independently mergeable.
- Respect documented dependencies; do not bypass an unfinished blocker.
- Do not add product behavior, infrastructure resources, migrations, or dependencies unless the issue requires them.
- Consult current official documentation before configuring a framework, SDK, API, CLI, or cloud service.

## Workspace boundaries

- `apps/api`: FastAPI public chat and authenticated admin APIs.
- `apps/worker`: ingestion and re-indexing jobs.
- `apps/admin`: Next.js/React admin portal.
- `packages/widget`: script-loaded React custom element and Shadow DOM styles.
- `packages/contracts`: shared API and SSE contracts.
- `infra/terraform`: Terraform-managed GCP infrastructure.

Keep provider SDK details behind adapters and prevent browser packages from accessing databases, model providers, or secrets directly.

## Tooling and required checks

Use only the versions pinned in `mise.toml` and the committed lockfiles.

```sh
mise trust
mise install
mise run bootstrap
mise run check
```

- Run `mise run format` only when formatting changes are intended.
- Run the focused test while developing, then `mise run check` before handoff.
- Do not bypass, weaken, or mark a failing quality gate as optional.
- Add automated tests for changed behavior. Keep tests deterministic and independent of production credentials.
- Record repeatable manual verification when behavior cannot be fully automated.

## Language conventions

- Python: use type annotations, Ruff formatting/linting, strict mypy, and pytest. Keep I/O boundaries async when application code is introduced.
- TypeScript: keep strict compiler settings, avoid unsafe `any`, use ESLint and Prettier, and test with Vitest.
- Terraform: run recursive formatting and validation. Provision shared resources only through reviewed Terraform changes.

## Security and operations

- Never commit credentials, copied production data, `.env` files, Terraform state, or provider keys.
- Never log authorization headers, secret values, or raw sensitive document content.
- Use least-privilege identities and Secret Manager when those capabilities are introduced.
- Do not create manual cloud resources as a shortcut around Terraform.

## External systems

Update Linear or other external systems only when the user explicitly requests it. When requested, include concise implementation and verification evidence and report any discovered follow-up without starting it automatically.
