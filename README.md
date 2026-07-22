# Production RAG Support Chatbot

This repository is a polyglot monorepo for the production RAG support chatbot described in [the product brief](docs/product-brief.md) and [architecture](docs/architecture.md).

## Prerequisites

A fresh checkout requires:

- Git.
- [mise](https://mise.jdx.dev/getting-started.html), which installs the pinned Node.js, pnpm, Python, uv, and Terraform versions.

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

| Command                 | Purpose                                                |
| ----------------------- | ------------------------------------------------------ |
| `mise run bootstrap`    | Install all locked JavaScript and Python dependencies. |
| `mise run format`       | Format TypeScript, Python, and Terraform workspaces.   |
| `mise run format:check` | Verify formatting without changing files.              |
| `mise run lint`         | Run ESLint and Ruff.                                   |
| `mise run typecheck`    | Run TypeScript and Python type checkers.               |
| `mise run test`         | Run workspace tests and Terraform validation.          |
| `mise run check`        | Run every non-mutating quality gate used by CI.        |

## Workspace layout

| Path                 | Responsibility                                 |
| -------------------- | ---------------------------------------------- |
| `apps/api`           | FastAPI public and admin API service.          |
| `apps/worker`        | Asynchronous ingestion worker.                 |
| `apps/admin`         | Next.js administration portal.                 |
| `packages/widget`    | Embeddable support-chat web component.         |
| `packages/contracts` | Shared request, response, and event contracts. |
| `infra/terraform`    | GCP infrastructure definitions.                |

The current placeholders reserve these boundaries; product behavior is added by later issues.

## Verify quality gates reject bad changes

To verify the formatter gate, add trailing or inconsistent formatting to a tracked TypeScript file and run `mise run format:check`. To verify type checking, temporarily add `const invalid: string = 1;` to a TypeScript source file and run `mise run typecheck`. Both commands must fail; restore the file and rerun `mise run check` before committing.
