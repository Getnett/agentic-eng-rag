# Provider adapter contracts

`rag-provider-adapters` is the provider-neutral Python boundary shared by model
orchestration. It contains no provider SDK and makes no network calls.

The package declares generation, embedding, rewrite, and rerank roles. M1 executes
generation and embedding only; rewrite and rerank remain interface declarations
until their later milestone issues. Every request carries a timeout and token
budget. Every result reports the provider/model identity, applied timeout, token
usage, and a USD cost estimate. Cost values are diagnostic estimates, not billing
records.

Run the deterministic contract suite and configuration-swap example with:

```sh
mise run test:providers
mise run providers:example
```

The example injects two different fake configurations into the same orchestration
function. No credential, provider SDK, or live model is required.

## Vertex generation

`VertexGenerationAdapter` uses the Google Gen AI SDK in Vertex mode. It reads the
non-secret project, location, and model identifiers from `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION`, and `VERTEX_GENERATION_MODEL`. Authentication uses
Application Default Credentials locally and the attached Cloud Run service
identity in development; no API key or service-account key is accepted.

The deterministic adapter and API smoke-boundary tests make no network calls:

```sh
mise run test:vertex
```

The real smoke script is deliberately opt-in because it is billed and depends on
regional model availability:

```sh
export RUN_VERTEX_INTEGRATION=1
export GOOGLE_CLOUD_PROJECT='development-project-id'
export GOOGLE_CLOUD_LOCATION='europe-west1'
export VERTEX_GENERATION_MODEL='configured-model-id'
mise run vertex:smoke
unset RUN_VERTEX_INTEGRATION
```

The script uses a fixed, non-sensitive support prompt. Logs contain provider,
model, location, token counts, estimated cost, and normalized error category, but
never prompt text, credentials, authorization data, or raw SDK error details.
