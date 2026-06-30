# MCP Multi-Agent Framework

## Priming Summary

**Goal:** Framework for building multi-agent systems on Model Context Protocol (MCP) over gRPC. Agent node logic is modeled in Python (LangGraph) and auto-translated to Java wrappers via AST-based code generation. MCP server implementations are written manually in Java — Java's static typing, predictable garbage collection, and thread-safe concurrency primitives make it better suited for deterministic server-side workflows than Python. Primary design goals: deterministic execution, reproducible orchestration, and verifiable tool interactions. Ships with a research-agent demo workflow.

**Constraints:**
- Agent node wrappers, proto schemas, and tests are auto-generated from `tools/multi_agent.py` — manual edits to generated files are overwritten on rebuild. MCP server business logic (`impl/*_impl.java`) is written manually in Java
- Each agent node runs as an independent gRPC server (one port per node), all MCP servers on their own ports
- LLM inference via HTTP to llama-server (`OllamaClient.java`, 3 retries with linear backoff)
- Project configuration loaded via `opencode.json`; this README loaded at session start
- git-crypt encrypts all files except `.gitattributes` and `.gitignore`

**Progress:**
- AST-based Python→Java code generation pipeline (`tools/langgraph_to_proto.py`) — supports state access, LLM sampling, tool calls, f-strings, generator expressions, type coercion
- Proto schema with two MCP services (`MCPServerService`, `MCPClientService`) + `Content` oneof model, published via Buf (`buf.build/perlin/private`)
- Bidirectional gRPC sampling — MCP servers callback to agent nodes for LLM inference during `CallTool`
- Abstract base classes: `BaseAgentNode` (agent lifecycle + sampling callback), `GraphRunner` (switch-dispatch loop, configurable max steps)
- Demo workflow: 3 agents (supervisor, research, writer) using 2 MCP servers (web search, filesystem)
- Full build pipeline (`build.sh`): clean → generate → buf push → buf generate → compile → test
- 19 tests across 3 tiers (proto serialization, in-process hermetic, integration with live LLM)
- Docker build with GPU auto-detection (NVIDIA CUDA, AMD Vulkan, Intel)

**Key Decisions:**
- AST-based Java translation from Python LangGraph — agent node wrappers, proto, and tests generated from the same Python model; MCP server business logic written manually in Java
- Java for MCP server implementations — Java's static typing, deterministic garbage collection, and thread-safe concurrency primitives eliminate entire classes of runtime errors that Python's dynamic typing and GIL introduce in long-running server processes; Java is better suited for deterministic server-side workflows than Python
- Deterministic supervisor routing (state-based if/else, not LLM) — avoids LLM failure modes in graph traversal
- Bidirectional gRPC sampling — MCP servers callback to agents for LLM inference, no polling or webhook infrastructure
- Distributed agent nodes — each agent independent on its own port, individually deployable/testable
- Content model uses protobuf oneof (`TextContent`, `ImageContent`, `ResourceContent` wrapped in `Content`)

**Next Steps:**
- Build and test: `BUF_TOKEN=$BUF_TOKEN ./docker-run.sh`
- OpenCode commands: `/build` (full pipeline), `/test` (19 tests), `/fix` (loop until green), `/status`

**Critical Context:**
- Source of truth: `tools/multi_agent.py` — define agents, graph topology, tools, proto schema, and tests in one Python model
- Code generator: `tools/langgraph_to_proto.py` — walks Python AST, emits Java + proto + tests
- Key infrastructure files: `BaseAgentNode.java` (agent base class with sampling), `OllamaClient.java` (LLM HTTP client), `GraphRunner.java` (dispatch loop)
- Port convention: example workflow uses 11435 (LLM), 50051-50052 (MCP servers), 50053-50056 (agent nodes)
- Tests generated automatically per workflow; add custom unit tests in `src/test/java/research/v1/`

## Build

```bash
./build.sh          # Full pipeline — GPU detection, Docker orchestration, proto gen, compile, test
```

`./build.sh` handles everything in one script: outside Docker it manages GPU detection, model downloads, and container orchestration; inside Docker it runs proto generation, compilation, and testing.

## Demo Workflow: Multi-Agent Research

The repo ships with a concrete example: a research agent that performs web searches and writes summary files.

### Agent Graph

```
supervisor ──[research]──> research_agent ──(always)──> supervisor
supervisor ──[writer]────> writer_agent   ──(always)──> supervisor
supervisor ──[FINISH]────> __end__
```

Routing is deterministic: supervisor checks `researchResults` (empty → research), then `writtenFiles` (empty → writer), else FINISH. LLM generates only reasoning text, not routing decisions.

### Demo Port Map

| Port | Component | Protocol |
|------|-----------|----------|
| 11435 | llama-server | HTTP (OpenAI-compatible) |
| 50051 | WebSearch MCP Server | gRPC `MCPServerService` |
| 50052 | Filesystem MCP Server | gRPC `MCPServerService` |
| 50053 | Supervisor Node | gRPC `MCPClientService` |
| 50055 | ResearchAgent Node | gRPC `MCPClientService` |
| 50056 | WriterAgent Node | gRPC `MCPClientService` |

### Demo MCP Servers

| File(s) | Tools | Backend |
|---------|-------|---------|
| `impl/web_search_impl.java` (manual) + generated wrapper | `web_search` | DuckDuckGo Instant Answer API + HTML fallback |
| `impl/filesystem_impl.java` (manual) + generated wrapper | `write_file`, `read_file`, `list_files` | File I/O with path traversal protection |

### Demo Agent Nodes

| File | Role |
|------|------|
| `SupervisorNode.java` | Deterministic router: research → writer → FINISH. LLM generates reasoning text. |
| `ResearchAgentNode.java` | LLM generates search query, calls `web_search`, stores results. |
| `WriterAgentNode.java` | LLM drafts content, calls `write_file`, records filename. |

---

## Orchestration Log (`output/message.log`)

Every integration test suite produces a structured trace at `output/integration-message.log` (or `output/mcp-message.log` for the HTTP transport test) with entries in this format:

```
[#001] 2026-06-18T14:30:00Z    AGENT:orchestrator    TOOL:web_search        web_searchRequest
[#002] 2026-06-18T14:30:01Z    TOOL:web_search      AGENT:orchestrator     web_searchResponse
[#003] 2026-06-18T14:30:02Z    AGENT:orchestrator    LLM                   Prompt
[#004] 2026-06-18T14:30:05Z    LLM                   AGENT:orchestrator     Result
```

The six columns: `[sequence]  timestamp  source  target  action  [detail]`. Sources and targets use normalized names (`AGENT:orchestrator`, `TOOL:web_search`, `LLM`).

This log is sufficient to render a **complete swim lane diagram** of any orchestration run — every agent-to-agent handoff, tool invocation, and LLM sampling round-trip is recorded in order. Workflow and tool designers use it to verify that a given orchestration is deterministic and reproducible across runs.

## Technology Stack

| Technology | Version | Role |
|-----------|---------|------|
| Amazon Corretto JDK | 21 | Java runtime |
| gRPC Java | 1.82.1 | RPC framework |
| Protobuf | 4.35.1 | Serialization |
| llama.cpp | b9837 | LLM inference |
| Qwen2.5-14B | Q4_K_M GGUF | Language model |
| Buf CLI | 1.71.0 | Proto registry + codegen |
| JUnit 5 | 6.1.0 | Testing |
| Python 3 | — | Code generation |

## Key Design Patterns

- **Single source of truth**: One Python model generates agent node wrappers, proto schemas, and tests per workflow; MCP server business logic is written manually in Java
- **AST-based translation**: Python function AST → semantically equivalent Java wrappers, no templates or string generation
- **Bidirectional gRPC**: MCP servers callback to agents for LLM sampling — push model, no polling
- **Deterministic routing**: Graph traversal uses state-based routing, not LLM decisions — reliable and testable
- **Distributed agent nodes**: Each agent is an independent gRPC server, individually deployable and scalable
- **Context propagation**: gRPC interceptor carries agent identity across service boundaries
