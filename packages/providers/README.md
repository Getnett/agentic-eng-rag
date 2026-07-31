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
