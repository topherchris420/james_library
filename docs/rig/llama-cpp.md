# llama.cpp on the Rig

Rig uses the **existing** llama.cpp provider. There is no second
implementation:

| Setting | Value |
| --- | --- |
| Provider id | `llamacpp` (alias `llama.cpp`) |
| Default endpoint | `http://localhost:8080/v1` (`providers::locality::LLAMACPP_DEFAULT_BASE_URL`, shared by the factory and Rig) |
| Custom endpoint | `api_url` in `config.toml` when `default_provider = "llamacpp"` |
| Credential | `LLAMACPP_API_KEY`, or `api_key` in config, matching `llama-server --api-key` |

## Run it

```bash
llama-server -m ~/models/your-model.gguf --port 8080
rain rig models
```

```text
● llama.cpp  http://localhost:8080/v1  running
    your-model.gguf
```

Select it as the default provider with `rain rig setup --profile local`, which
proposes the switch when llama.cpp is running, or set it directly:

```toml
default_provider = "llamacpp"
default_model = "your-model.gguf"   # an id listed by `rain rig models`
# api_url = "http://127.0.0.1:8033/v1"   # only for a non-default port/host
```

## What discovery does

1. Classifies the endpoint. A remote endpoint is never probed.
2. `GET {root}/health`. llama-server answers `503` while the model is still
   loading.
3. `GET {base}/models` (the OpenAI-compatible list), parsed with the same
   parser the onboarding wizard uses.
4. Sends the credential only when one is configured. The value is never
   printed or serialized.
5. Checks `PATH` for `llama-server` to explain "installed but not running".

| Observation | State |
| --- | --- |
| `/v1/models` answers with a model list | `running` |
| `/health` returns 503 | `degraded` (model loading) |
| `/v1/models` returns 401/403 | `degraded` (set `LLAMACPP_API_KEY`) |
| Other HTTP error | `degraded` |
| Nothing listening, llama.cpp is the default provider | `configured` (doctor: `FAIL`) |
| Nothing listening, not selected | `unavailable` (doctor: `SKIP`) |

`rig doctor` also warns when `default_model` is not in the server's list.

## Locality

`localhost`, `127.0.0.0/8` and `::1` are `local`. RFC 1918, link-local and ULA
addresses are `lan`, which `local` privacy accepts, for example a llama.cpp box
on a home server. A hostname such as `gpu-box.local` is resolved and counts as
`lan` only when every address it resolves to is private; a public answer or a
failed lookup is `remote`. `local` privacy refuses `remote`, and `hybrid`
produces a doctor `WARN`.

Rig probes pin the address they verified, so a second DNS answer cannot
redirect a probe. The runtime's HTTP clients resolve again when they connect,
so enforcement checks the name at provider construction time.

## Testing without a GPU

The unit tests use `wiremock` to stand in for llama-server
(`src/rig/inference.rs`, `src/rig/status.rs`). No real model server is needed
in CI.
