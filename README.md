# 🧠 smol-brain

> **Big models. Smol headaches.**  
> A ridiculously easy, production-ready deployment stack for local LLMs using vLLM and Docker.

![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=flat&logo=docker&logoColor=white)
![vLLM](https://img.shields.io/badge/Powered_by-vLLM-blue?style=flat)

**smol-brain** is a containerized inference server designed to get large language models running on your own hardware in minutes. By wrapping [vLLM](https://github.com/vllm-project/vllm), it provides massive throughput via PagedAttention and continuous batching without the usual deployment headaches.

It exposes an **OpenAI-compatible API** right out of the box. If your application already talks to ChatGPT, you can point it at `smol-brain` by simply swapping out the base URL—no client rewrites needed.

---

## ✨ Features

* **🐳 Docker-Native:** No more polluting your host machine. Say goodbye to CUDA version conflicts and dependency hell.
* **⚡️ Blazing Fast:** Powered by vLLM for state-of-the-art inference speed and GPU utilization.
* **🔄 OpenAI Drop-In:** Fully mirrors the OpenAI API (`/v1/chat/completions`). 
* **💾 Persistent Caching:** Automatically mounts your Hugging Face cache so models only download once.
* **🛠️ Production Ready:** Configured for concurrency handling and high GPU memory utilization out of the box.

---

## 📋 Prerequisites

Before deploying `smol-brain`, ensure your host machine has:

* A Linux environment with an NVIDIA GPU (Compute Capability 7.5+ recommended).
* **Docker 24.0+** installed.
* **[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)** installed and configured.
* A Hugging Face account and Access Token (for gated models like Llama 3).

Verify your GPU is visible to Docker:
`docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`

---

## 🚀 Quickstart

The easiest way to launch your local AI is using the provided Docker Compose stack. 

**1. Clone the repository**
`git clone https://github.com/mrcaelumn/smol-brain.git`
`cd smol-brain`

**2. Set your Hugging Face token**
`export HF_TOKEN="your_hugging_face_token_here"`

**3. Fire it up**
`docker compose up -d`
*Note: The first run will take a few minutes as it downloads the model weights to your local volume. Subsequent boots will take seconds.*

---

## 🔌 Usage

Once the container is running and the model is loaded, `smol-brain` will expose a server on port `8000`. 

Because it mimics the OpenAI API, you can test it immediately using `curl` or hook it up to any standard OpenAI SDK (Python, Rust, Go, etc.) by setting your client's base URL to `http://localhost:8000/v1` and passing in a dummy API key.

`curl http://localhost:8000/v1/chat/completions \`
  `-H "Content-Type: application/json" \`
  `-H "Authorization: Bearer dummy-key" \`
  `-d '{`
    `"model": "meta-llama/Meta-Llama-3.1-8B-Instruct",`
    `"messages": [`
      `{"role": "user", "content": "Explain Docker in two sentences."}`
    `]`
  `}'`

---

## ⚙️ Configuration

The default `docker-compose.yml` is configured for **Llama-3.1-8B-Instruct** on a single GPU. You can easily tweak the command arguments in the compose file to fit your hardware:

* `--model`: Change this to any model on the Hugging Face Hub (e.g., `Qwen/Qwen2.5-7B-Instruct`).
* `--gpu-memory-utilization`: Set to `0.90` (90%) by default. Lower this if you are running other GPU workloads on the same machine.
* `--max-model-len`: Limits the context window to save VRAM. Default is `4096`.
* `--tensor-parallel-size`: If you have multiple GPUs, set this to the number of GPUs you want to split the model across (e.g., `2`).

---

## 🤝 Contributing
Found a bug? Want to add support for a new hardware accelerator? PRs are always welcome. Let's make `smol-brain` even bigger.

## 📄 License
MIT License. See `LICENSE` for more information.