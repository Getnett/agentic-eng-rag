# Shared contracts

`@rag-support/contracts` is the versioned vocabulary shared by the widget, admin portal, API, and worker. Zod schemas provide TypeScript types and runtime client validation. Committed JSON Schema artifacts under `generated/v1` let Python and other consumers validate the same wire contracts without importing or deploying the TypeScript package.

## Public chat request

The v1 request requires a public widget key, a visitor session ID, bounded short history, and the current question. Browser origin remains an HTTP header and is not duplicated in the body.

```json
{
  "contract_version": "v1",
  "widget_key": "public_widget_key_123456",
  "visitor_session_id": "visitor_session_123",
  "history": [],
  "question": "How do I reset model A?"
}
```

## Normalized SSE events

Client code validates a normalized `{ event, id, data }` object. `event` maps to the SSE `event:` field, `id` maps to the SSE `id:` field, and `data` is the decoded JSON from the SSE `data:` field.

```text
event: answer.delta
id: 00000000-0000-4000-8000-000000000002
data: {"contract_version":"v1","request_id":"00000000-0000-4000-8000-000000000001","text":"Press and hold the reset button."}
```

The supported event names are `answer.delta`, `citation`, `abstention`, `complete`, and `error`. `error` carries only the public-safe error shape. Authenticated admin responses use a separate envelope that may contain bounded field-level details.

## Generate portable schemas

```sh
pnpm --filter @rag-support/contracts generate
pnpm --filter @rag-support/contracts generate:check
```

Generation targets JSON Schema Draft 2020-12. CI runs `generate:check`, so schema changes must include refreshed artifacts. Python services can copy or load the generated JSON during their own build and test process; they do not depend on Node.js or the TypeScript package at runtime.
