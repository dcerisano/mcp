# Technology Stack

## Languages
- **Python 3** — code generation only (tools/); langgraph, langchain-core, grpcio/grpcio-tools
- **Java 21** (Amazon Corretto) — all server implementations, agent nodes, tests
- **Bash** — build orchestration (build.sh)
- **TypeScript** — only for .opencode/ node_modules (buf CLI dependency)

## gRPC & Protobuf
- gRPC Java 1.82.1 (api, core, stub, protobuf, protobuf-lite, inprocess, netty-shaded)
- Protobuf Java 4.35.1
- Buf CLI 1.71.0 — proto registry at buf.build/perlin/private; pushed via `buf push`
- Codegen: `buf.gen.yaml` uses remote plugins (protocolbuffers/java:v35.1, grpc/java:v1.82.1)
- Python stubs generated separately via `grpc_tools.protoc`

## LLM Inference
- llama.cpp (binary version b9837, Vulkan backend)
- Models: Qwen2.5-14B-Instruct-Q4_K_M.gguf (>=12GB VRAM) or Qwen2.5-3B-Instruct-Q4_K_M.gguf (fallback)
- llama-server on port 11435, OpenAI-compatible HTTP API

## Libraries (Java, all in lib/)
- Gson 2.14.0 — JSON parsing
- Guava 33.6.0-jre
- javax.annotation-api 1.3.2
- JUnit Platform Console Standalone 6.1.0 (JUnit 6 / Jupiter)

## Build
- `build.sh` — 9-step pipeline: clean → generate proto+Java → format → buf push → buf generate → compile stubs → compile main → compile tests → run tests
- Docker image `mcp-build`: Ubuntu 24.04 with Corretto 21, Node 26, Python deps, llama.cpp Vulkan binary

## Python Dependencies (in Docker / venv)
grpcio==1.81.1, grpcio-tools==1.81.1, langgraph==1.2.6, langchain-core==1.4.8, pydantic==2.13.4, typing-extensions==4.15.0
