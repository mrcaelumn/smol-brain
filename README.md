# 🧠 smol-brain

> **Big models. Smol headaches.**  
> A production-ready deployment stack for local LLMs using vLLM and multiple gateway implementations.

![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)
![vLLM](https://img.shields.io/badge/Powered_by-vLLM-blue?style=flat)

**smol-brain** is a modular, containerized inference ecosystem designed to deploy large language models on your own hardware in minutes. It provides:

* **🎯 vLLM backend**: State-of-the-art GPU inference via [vLLM](https://github.com/vllm-project/vllm) with PagedAttention and continuous batching
* **🚪 Multiple gateways**: Choose your preferred gateway implementation (Python, Go, Rust) with caching, rate limiting, and resilience
* **🐳 Docker-Native**: No CUDA conflicts or dependency hell — everything runs in containers
* **🔄 OpenAI Drop-In**: Fully compatible with OpenAI's API (`/v1/chat/completions`)

---

## 📋 Prerequisites

Before deploying `smol-brain`, ensure your host machine has:

* A Linux environment with an NVIDIA GPU (Compute Capability 7.5+ recommended).
* **Docker 24.0+** installed.
* **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)** installed and configured.
* A Hugging Face account and Access Token (for gated models like Llama 3).

Verify your GPU is visible to Docker:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

---

## 🏗️ Architecture

```
smol-brain/
├── docker-compose.yml           # Main orchestration (all services)
├── services/
│   ├── python-gateway/          # Async FastAPI gateway with LangChain + Redis caching
│   │   ├── app/                 # Production-grade Python application
│   │   ├── Dockerfile           # Multi-stage build, non-root user
│   │   └── requirements.txt     # Pinned dependencies
│   ├── go-gateway/              # (Planned) Go gateway with fiber/fasthttp
│   └── rust-gateway/            # (Planned) Rust gateway with axum/tokio
├── infra/
│   └── redis/                   # Redis configuration and persistence
├── docker-compose.vllm.yml      # vLLM-only composition (standalone)
└── .env.example                 # Environment configuration
```

**Core services:**
1. **vLLM**: The GPU inference engine (exposes OpenAI-compatible API on port 8000)
2. **Redis**: Shared cache for all gateways (rate limiting, exact/semantic caching)
3. **Gateway(s)**: HTTP frontends with auth, rate limiting, circuit breaking, observability

---

## 🚀 Quickstart

### Option 1: vLLM only (direct OpenAI-compatible API)

```bash
# Clone and enter the workspace
git clone https://github.com/mrcaelumn/smol-brain.git
cd smol-brain

# Set your Hugging Face token
export HF_TOKEN="your_hugging_face_token_here"

# Start vLLM (GPU required)
docker compose -f docker-compose.vllm.yml up -d
```

Test the direct vLLM API:
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dummy-key" \
  -d '{
    "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "messages": [
      {"role": "user", "content": "Explain Docker in two sentences."}
    ]
  }'
```

### Option 2: Complete stack with Python gateway

```bash
# Copy environment template
cp .env.example .env
# Edit .env to set HF_TOKEN and API keys

# Launch the full stack (vLLM + Redis + Python gateway)
docker compose up -d
```

The Python gateway exposes:
* **8080**: Gateway API (`/v1/chat`, `/healthz`, `/metrics`)
* **8000**: vLLM direct API (internal only)
* **6379**: Redis (internal only)

---

## 🔌 Gateway Features

All gateways implement:

* **🔐 API key authentication** with constant-time comparison
* **⏱️ Redis-backed rate limiting** (token bucket per key/IP)
* **💾 Caching layers**:
  - **Exact-match cache**: Identical prompts skip the GPU entirely
  - **Semantic cache**: Similar prompts reuse answers (optional)
* **⚡ Resilience**:
  - Exponential backoff retry for transient vLLM failures
  - Circuit breaker to fail fast when upstream is unhealthy
* **📊 Observability**:
  - Structured JSON logging (PII-free)
  - Prometheus metrics at `/metrics`
  - Liveness/readiness probes for Kubernetes
* **🌐 Production hardening**:
  - Async/await architecture (non-blocking)
  - Connection pooling (Redis + HTTP)
  - Graceful shutdown handlers
  - Strict CORS configuration

---

## 🛠️ Service Configuration

### vLLM (GPU service)
Edit `docker-compose.vllm.yml` or override via `.env`:
```yaml
environment:
  MODEL: Qwen/Qwen3.5-2B
  GPU_MEMORY_UTILIZATION: "0.75"
  MAX_MODEL_LEN: "4096"
  TENSOR_PARALLEL_SIZE: "1"
```

### Python gateway
Edit `services/python-gateway/.env.example` → `.env`:
```bash
# API keys (comma-separated)
GATEWAY_API_KEYS=your-production-key-here

# Redis connection
GATEWAY_REDIS_URL=redis://redis:6379/0

# vLLM upstream (internal network)
GATEWAY_VLLM_BASE_URL=http://smol-brain:8000/v1

# Rate limiting
GATEWAY_RATE_LIMIT_CAPACITY=120
GATEWAY_RATE_LIMIT_REFILL_PER_SECOND=2.0
```

### Health checks
- **vLLM**: `http://localhost:8000/health`
- **Python gateway**: `http://localhost:8080/healthz` (liveness), `http://localhost:8080/readyz` (readiness)
- **Prometheus metrics**: `http://localhost:8080/metrics`

---

## 📈 Scaling

### Horizontal scaling
1. **vLLM**: Run multiple replicas with GPU affinity, load balance via gateway
2. **Gateways**: Stateless, scale behind load balancer (NGINX, Traefik)
3. **Redis**: Single instance for cache/rate limiting (or Redis Cluster for high availability)

### Kubernetes (HPA)
Autoscale gateways based on CPU/memory or custom Prometheus metrics:
```yaml
metrics:
- type: Resource
  resource:
    name: cpu
    target:
      type: Utilization
      averageUtilization: 70
- type: Pods
  pods:
    metric:
      name: gateway_in_flight_requests
    target:
      type: AverageValue
      averageValue: "100"
```

---

## 🤝 Contributing

Want to add a Go or Rust gateway? Follow this structure:

```bash
services/
├── go-gateway/
│   ├── cmd/
│   ├── pkg/
│   ├── go.mod
│   └── Dockerfile
└── rust-gateway/
    ├── src/
    ├── Cargo.toml
    └── Dockerfile
```

PRs are welcome. Let's make `smol-brain` even bigger.

## 📄 License
MIT License. See `LICENSE` for more information.
