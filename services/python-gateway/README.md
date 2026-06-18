# Python gateway for smol-brain

An asynchronous, production-grade FastAPI gateway that fronts a vLLM backend
with LangChain orchestration, Redis caching, rate limiting, resilience patterns
and first-class observability.

## Project layout

The `app/` package is organised by concern so responsibilities stay isolated
and testable:

```
app/
├── main.py                  # App factory, lifespan, middleware & exception wiring
├── core/                    # Cross-cutting foundations
│   ├── config.py            # Pydantic BaseSettings (env-driven config)
│   └── resilience.py        # Circuit breaker + tenacity retry policy
├── observability/           # Logging & metrics
│   ├── logging.py           # structlog JSON logging setup
│   └── metrics.py           # Prometheus registry + metric definitions
├── schemas/                 # Pydantic v2 request/response models
│   └── chat.py
├── services/                # External integrations (own their lifecycles)
│   ├── cache.py             # Redis pool + LangChain exact/semantic cache
│   ├── llm.py               # vLLM-backed ChatOpenAI client w/ resilience
│   └── rate_limit.py        # Redis token-bucket limiter (atomic Lua)
└── api/                     # HTTP layer
    ├── dependencies.py      # DI: auth, rate limiting, singleton accessors
    ├── middleware.py        # Request-id, access logs, metrics
    └── routes/
        ├── chat.py          # POST /v1/chat (buffered + SSE streaming)
        └── health.py        # /healthz, /readyz, /metrics
```

Supporting files:

```
.
├── Dockerfile               # Multi-stage build, runs as non-root user
├── gunicorn_conf.py         # Gunicorn + Uvicorn worker tuning
├── pyproject.toml           # Ruff, mypy, pytest & coverage config
├── requirements.txt         # Pinned runtime dependencies
├── requirements-dev.txt     # Test & lint dependencies
├── Makefile                 # install / dev / test / lint / build helpers
└── tests/                   # unit / integration / e2e suites
```

## Quickstart

```bash
make install        # install runtime + dev dependencies
make dev            # run locally with auto-reload on :8080
make lint           # ruff + mypy
make test           # run the test suite
make build          # build the Docker image
```

The ASGI entrypoint is `app.main:app` (used by both `uvicorn` and `gunicorn`).

## Configuration

All settings are environment-driven with the `GATEWAY_` prefix. See
[.env.example](./.env.example) for the full list. Key variables:

| Variable | Purpose | Default |
| --- | --- | --- |
| `GATEWAY_VLLM_BASE_URL` | Internal vLLM `/v1` URL | `http://smol-brain:8000/v1` |
| `GATEWAY_REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `GATEWAY_API_KEYS` | Comma-separated accepted API keys | _(empty → auth off)_ |
| `GATEWAY_RATE_LIMIT_CAPACITY` | Token-bucket burst size | `120` |
| `GATEWAY_SEMANTIC_CACHE_ENABLED` | Toggle vector similarity caching | `false` |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/v1/chat` | Chat completion (set `"stream": true` for SSE) |
| `GET` | `/healthz` | Liveness probe (process only) |
| `GET` | `/readyz` | Readiness probe (checks Redis + vLLM) |
| `GET` | `/metrics` | Prometheus metrics |

## Testing

The suite lives under `tests/` and is split by scope:

```
tests/
├── conftest.py        # shared fixtures (in-memory fakeredis client)
├── unit/              # fast, isolated, no external services
│   ├── test_config.py        # settings parsing & validation
│   ├── test_schemas.py       # request/response validation
│   ├── test_resilience.py    # circuit breaker state machine + retry
│   ├── test_observability.py # metrics helpers & registry
│   ├── test_llm.py           # message conversion, usage, stream/retry paths
│   └── test_dependencies.py  # API-key auth & rate-limit enforcement
├── integration/       # multiple components together (in-memory deps)
│   ├── test_rate_limit.py    # token-bucket Lua against fakeredis
│   ├── test_cache.py         # cache manager lifecycle/health
│   └── test_api.py           # full app via TestClient (stubbed services)
└── e2e/               # smoke tests against a live stack (opt-in)
    └── test_live_smoke.py
```

Run them:

```bash
make test                 # full suite
pytest tests/unit -v      # unit tests only
pytest --cov=app          # with coverage
```

End-to-end tests are skipped unless you point them at a running gateway:

```bash
GATEWAY_E2E_URL=http://localhost:8080 \
GATEWAY_E2E_API_KEY=your-key \
pytest tests/e2e -v
```

> **Note:** Use Python 3.12 (matching the Docker image). The pinned `redisvl`
> dependency does not yet support 3.13+. The `redisvl` package is only needed
> for the optional semantic cache, not for the test suite itself.
