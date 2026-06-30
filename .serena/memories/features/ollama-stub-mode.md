# OllamaClient Stub Mode

## Goal
Make LLM-dependent tests self-contained by allowing `OllamaClient.call()` to return a deterministic stub response instead of making a real HTTP request to llama-server.

## Implementation
- **Codegen change** in `tools/langgraph_to_proto.py:generate_ollama_client_java()`: added system property check at top of `call()`. When `System.getProperty("ollama.stub")` is set to a non-empty string, returns that string immediately.
- **Test change** in `src/test/java/research/v1/McpHttpTransportTest.java`: `setUp()` calls `System.setProperty("ollama.stub", ...)`, `tearDown()` calls `System.clearProperty("ollama.stub")`.
- All 25 `McpHttpTransportTest` tests now pass in ~1.6s without any LLM dependency.

## Framework-level
- The stub is generated into `OllamaClient.java` by the codegen template — any workflow's tests benefit automatically.
- Costs one if-statement per call; zero overhead when property not set.

## Files Changed
- `tools/langgraph_to_proto.py` — added stub check to OllamaClient template
- `src/test/java/research/v1/McpHttpTransportTest.java` — set/clear the property
