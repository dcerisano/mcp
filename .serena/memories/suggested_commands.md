# Suggested Commands — MCP Framework

## Build
- `./build.sh` — full build (the only build command). Runs Docker container which does: clean → generate → compile → unit tests → integration tests
- Never run `build-inner.sh` directly (deleted, merged into build.sh)

## Regenerate
- Just run `./build.sh` — it runs `langgraph_to_proto.py` inside the container, then compiles and tests

## Test blocks (inside build)
- McpProtoTest — proto message serialization (generated)
- McpUnitTest — in-process hermetic service logic (manual)
- McpHttpTransportTest — HTTP transport with gRPC fallback (manual)
- McpIntegrationTest — live server + Ollama sampling end-to-end via GraphRunner

## Manual test run
- `java -jar lib/junit-platform-console-standalone-6.1.0.jar execute --class-path <cp> --select-class <class>`

## Docker
- `docker run --rm -v "$(pwd)":/app mcp-build bash build.sh` — run build in container directly
- Container CMD (`[bash build.sh]`) handles Docker detection automatically
