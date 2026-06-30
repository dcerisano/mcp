#!/usr/bin/env bash
set -e

if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    ROOT="$(cd "$(dirname "$0")" && pwd)"
    if [ -z "$JAVA_HOME" ]; then
        export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
    fi
    export PATH=$JAVA_HOME/bin:$PATH
    if [ -d "$ROOT/venv" ]; then
        export PATH="$ROOT/venv/bin:$PATH"
    fi
    JUNIT="$ROOT/lib/junit-platform-console-standalone-6.1.0.jar"
    GRPC=1.82.1
    LIB="$ROOT/lib"
    PROTO_JAR="$LIB/protobuf-java-4.35.1.jar"
    GSON_JAR="$LIB/gson-2.14.0.jar"
    NETTY_JAR="$LIB/grpc-netty-shaded-1.82.1.jar"
    GRPC_CP="$LIB/grpc-api-${GRPC}.jar:$LIB/grpc-context-${GRPC}.jar:$LIB/grpc-core-${GRPC}.jar:$LIB/grpc-stub-${GRPC}.jar:$LIB/grpc-protobuf-${GRPC}.jar:$LIB/grpc-protobuf-lite-${GRPC}.jar:$LIB/grpc-inprocess-${GRPC}.jar:$LIB/javax.annotation-api-1.3.2.jar:$LIB/guava-33.6.0-jre.jar:$LIB/failureaccess-1.0.3.jar:$LIB/perfmark-api-0.27.0.jar:$LIB/error_prone_annotations-2.45.0.jar"
    CLASSES="$ROOT/gen/classes"
    TEST_CLASSES="$ROOT/gen/test-classes"
    MAIN_CLASSES="$ROOT/gen/main-classes"

    echo "############################################################"
    echo "# Cleaning generated files"
    echo "############################################################"
    rm -f "$ROOT/proto/research/v1/research_agent.proto"
    rm -rf "$ROOT/gen/java" "$ROOT/gen/python" "$ROOT/output"
    echo "Done."

    echo ""
    echo "############################################################"
    echo "# Generating proto + McpProtoTest from tools/multi_agent.py"
    echo "############################################################"
    python3 "$ROOT/tools/langgraph_to_proto.py" \
      "$ROOT/tools/multi_agent.py" \
      "$ROOT/proto/research/v1/research_agent.proto" \
      "$ROOT/src/test/java/research/v1/McpProtoTest.java" 2>/dev/null

    echo ""
    echo "############################################################"
    echo "# Formatting proto files"
    echo "############################################################"
    cd "$ROOT" && buf format -w

    if [ -n "$BUF_TOKEN" ]; then
        echo ""
        echo "############################################################"
        echo "# Pushing to buf"
        echo "############################################################"
        cd "$ROOT" && buf push
    else
        echo ""
        echo "############################################################"
        echo "# Skipping buf push (BUF_TOKEN not set)"
        echo "############################################################"
    fi

    echo ""
    echo "############################################################"
    echo "# Generating Java stubs (buf generate)"
    echo "############################################################"
    cd "$ROOT" && buf generate

    echo ""
    echo "############################################################"
    echo "# Generating Python stubs"
    echo "############################################################"
    mkdir -p "$ROOT/gen/python"
    python3 -m grpc_tools.protoc \
      -I "$ROOT/proto" \
      -I "$(python3 -c 'import grpc_tools, os; print(os.path.dirname(grpc_tools.__file__) + "/_proto")')" \
      --python_out="$ROOT/gen/python" \
      --grpc_python_out="$ROOT/gen/python" \
      "$ROOT/proto/research/v1/research_agent.proto" \
      "$ROOT/proto/test/v1/test.proto"

    echo ""
    echo "############################################################"
    echo "# Compiling generated stubs"
    echo "############################################################"
    rm -rf "$CLASSES" && mkdir -p "$CLASSES"
    javac -cp "$PROTO_JAR:$GRPC_CP" -d "$CLASSES" \
      "$ROOT"/gen/java/research/v1/Mcp.java \
      "$ROOT"/gen/java/research/v1/MCPServerServiceGrpc.java \
      "$ROOT"/gen/java/research/v1/MCPClientServiceGrpc.java \
      "$ROOT"/gen/java/test/v1/Test.java \
      "$ROOT"/gen/java/test/v1/UserServiceGrpc.java 1>/dev/null

    echo ""
    echo "############################################################"
    echo "# Compiling service implementations"
    echo "############################################################"
    rm -rf "$MAIN_CLASSES" && mkdir -p "$MAIN_CLASSES"
    javac -cp "$PROTO_JAR:$GSON_JAR:$NETTY_JAR:$GRPC_CP:$CLASSES" -d "$MAIN_CLASSES" \
      "$ROOT"/src/main/java/research/v1/*.java \
      "$ROOT"/src/main/java/research/v1/impl/*MCPServerImpl.java 1>/dev/null

    echo ""
    echo "############################################################"
    echo "# Compiling tests"
    echo "############################################################"
    rm -rf "$TEST_CLASSES" && mkdir -p "$TEST_CLASSES"
    javac -cp "$PROTO_JAR:$GSON_JAR:$NETTY_JAR:$GRPC_CP:$JUNIT:$CLASSES:$MAIN_CLASSES" -d "$TEST_CLASSES" \
      "$ROOT"/src/test/java/research/v1/*.java 1>/dev/null

    FULL_CP="$PROTO_JAR:$GSON_JAR:$NETTY_JAR:$GRPC_CP:$JUNIT:$CLASSES:$MAIN_CLASSES:$TEST_CLASSES"
    LOG_CFG="$ROOT/config/logging.properties"
    LOG_FLAG="-Djava.util.logging.config.file=$LOG_CFG"

    wait_for_port() {
        local port=$1 name=$2
        for i in $(seq 1 40); do
            if nc -z localhost "$port" 2>/dev/null; then
                echo "$name ready on port $port"
                return 0
            fi
            sleep 0.25
        done
        echo "ERROR: $name did not start on port $port"
        exit 1
    }

    mkdir -p "$ROOT/output"
    LLAMA_STARTED=false
    if curl -sf http://localhost:11435/health >/dev/null 2>&1; then
        echo "llama-server is running on port 11435."
        LLAMA_STARTED=true
    else
        echo "WARNING: llama-server not available on port 11435."
    fi

    kill_servers() {
        echo "Stopping MCP server processes..."
        kill "$WEB_PID" "$FS_PID" "$WEB_HTTP_PID" "$FS_HTTP_PID" 2>/dev/null || true
    }
    trap kill_servers EXIT

    if [ "$LLAMA_STARTED" = true ]; then
        java $LOG_FLAG -cp "$FULL_CP" research.v1.WebSearchServerMain > "$ROOT/output/web-search-server.log" 2>&1 & WEB_PID=$!
        java $LOG_FLAG -cp "$FULL_CP" research.v1.FilesystemServerMain > "$ROOT/output/filesystem-server.log" 2>&1 & FS_PID=$!
        java $LOG_FLAG -cp "$FULL_CP" research.v1.WebSearchHttpMain > "$ROOT/output/web-search-http-server.log" 2>&1 & WEB_HTTP_PID=$!
        java $LOG_FLAG -cp "$FULL_CP" research.v1.FilesystemHttpMain > "$ROOT/output/filesystem-http-server.log" 2>&1 & FS_HTTP_PID=$!
        wait_for_port 50051 "WebSearchServer"
        wait_for_port 50052 "FilesystemServer"
        wait_for_port 50061 "WebSearchHttpServer"
        wait_for_port 50062 "FilesystemHttpServer"
    fi

    run_tests() {
        local label="$1" test_class="$2"
        echo ""
        echo "############################################################"
        echo "# $label"
        echo "############################################################"
        if ! java $LOG_FLAG -jar "$JUNIT" execute --disable-banner --class-path "$FULL_CP" --select-class "$test_class" 2>&1; then
            exit 1
        fi
    }

    run_tests "Unit Tests — proto message serialization (generated)" research.v1.McpProtoTest
    run_tests "Unit Tests — In-Process Hermetic Service Logic (McpUnitTest)" research.v1.McpUnitTest
    run_tests "HTTP Transport Tests — HTTP endpoint with gRPC fallback" research.v1.McpHttpTransportTest

    if [ "$LLAMA_STARTED" = true ]; then
        echo ""
        echo "############################################################"
        echo "# Integration Tests — live server + Ollama sampling"
        echo "############################################################"
        : > "$ROOT/output/message.log"
        tail -f "$ROOT/output/message.log" &
        TAIL_PID=$!
        java $LOG_FLAG -jar "$JUNIT" execute --disable-banner --class-path "$FULL_CP" --select-class research.v1.McpIntegrationTest 2>&1; INTEGRATION_EXIT=$?
        kill "$TAIL_PID" 2>/dev/null
        wait "$TAIL_PID" 2>/dev/null || true
        mv "$ROOT/output/message.log" "$ROOT/output/integration-message.log" 2>/dev/null || true
        if [ "$INTEGRATION_EXIT" -ne 0 ]; then
            echo ""; echo "FAILURE!"; exit 1
        fi
        echo "OK (1 test)"
    else
        echo ""
        echo "############################################################"
        echo "# Integration Tests — SKIPPED (llama-server not available)"
        echo "############################################################"
    fi
    exit 0
fi

export PATH="/usr/bin:/usr/local/bin:$PATH"
GPU_FLAGS=""
MODEL_FILE=""

if docker info 2>/dev/null | grep -q "nvidia"; then
    echo "NVIDIA GPU detected — enabling Vulkan via direct device mapping"
    GPU_FLAGS=""
    for dev in /dev/nvidia*; do
        if [ -e "$dev" ]; then
            GPU_FLAGS="$GPU_FLAGS --device $dev"
        fi
    done
    if [ -d "/var/lib/snapd/lib/gl" ]; then
        GPU_FLAGS="$GPU_FLAGS -v /var/lib/snapd/lib/gl:/host-libs -v /var/lib/snapd/hostfs:/var/lib/snapd/hostfs:ro -e LD_LIBRARY_PATH=/host-libs"
    else
        GPU_FLAGS="$GPU_FLAGS -v /usr/lib/x86_64-linux-gnu:/host-libs -e LD_LIBRARY_PATH=/host-libs"
    fi
    GPU_FLAGS="$GPU_FLAGS -v /usr/share/vulkan/icd.d:/usr/share/vulkan/icd.d:ro"
    GPU_FLAGS="$GPU_FLAGS -v /etc/vulkan/icd.d:/etc/vulkan/icd.d:ro"
elif ls /dev/dri/renderD* >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi "amd\|radeon"; then
    echo "AMD GPU detected — enabling Vulkan"
    RENDER_GID=$(stat -c '%g' /dev/dri/renderD* 2>/dev/null | head -1)
    VIDEO_GID=$(stat -c '%g' /dev/kfd 2>/dev/null || stat -c '%g' /dev/dri/card* 2>/dev/null | head -1)
    GPU_FLAGS="--device /dev/kfd --device /dev/dri --group-add $VIDEO_GID --group-add $RENDER_GID -v /usr/share/vulkan/icd.d:/usr/share/vulkan/icd.d:ro -v /etc/vulkan/icd.d:/etc/vulkan/icd.d:ro -e LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs"
elif ls /dev/dri/renderD* >/dev/null 2>&1; then
    echo "Intel or other GPU detected — enabling Vulkan"
    RENDER_GID=$(stat -c '%g' /dev/dri/renderD* 2>/dev/null | head -1)
    GPU_FLAGS="--device /dev/dri --group-add $RENDER_GID -v /usr/share/vulkan/icd.d:/usr/share/vulkan/icd.d:ro -v /etc/vulkan/icd.d:/etc/vulkan/icd.d:ro -e LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs"
else
    echo "No GPU detected — running CPU only"
    GPU_FLAGS="-e LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs"
fi

select_model() {
    local mem_mb=0
    if docker info 2>/dev/null | grep -q "nvidia"; then
        mem_mb=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | sort -rn | head -1)
        mem_mb=${mem_mb:-0}
        echo "NVIDIA GPU free VRAM: ${mem_mb} MiB"
    fi
    if [ "$mem_mb" -eq 0 ]; then
        for card in /sys/class/drm/card*/device/mem_info_vram_total; do
            [ -f "$card" ] || continue
            local total vb used
            total=$(cat "$(dirname "$card")/mem_info_vram_total" 2>/dev/null)
            used=$(cat "$(dirname "$card")/mem_info_vram_used" 2>/dev/null)
            vb=$(( (total - used) / 1048576 ))
            [ "$vb" -gt "$mem_mb" ] && mem_mb=$vb
        done
        if [ "$mem_mb" -gt 0 ]; then echo "AMD GPU free VRAM: ${mem_mb} MiB"; fi
    fi
    if [ "$mem_mb" -eq 0 ]; then
        mem_mb=$(free -m | awk '/^Mem:/{print $7}')
        echo "System free RAM: ${mem_mb} MiB"
    fi
    local BIG="Qwen2.5-14B-Instruct-Q4_K_M.gguf"
    local SMALL="Qwen2.5-3B-Instruct-Q4_K_M.gguf"
    if [ "$mem_mb" -ge 12000 ]; then
        MODEL_FILE="$BIG"; echo "Selected model: $BIG (>= 12000 MiB available)"
    else
        MODEL_FILE="$SMALL"; echo "Selected model: $SMALL (< 12000 MiB available)"
    fi
}
select_model

if ! docker image inspect mcp-build >/dev/null 2>&1; then
    echo "Building mcp-build image (one-time, ~30+ min)..."
    docker build -t mcp-build -f Dockerfile .
fi

download_model() {
    local name="$1" url="$2"
    if ! docker run --rm -v llama-models:/models mcp-build ls "/models/$name" >/dev/null 2>&1; then
        echo "Downloading $name into volume (one-time)..."
        docker run --rm -v llama-models:/models mcp-build wget -q --show-progress -O "/models/$name" "$url"
        echo "$name ready."
    fi
}
download_model "Qwen2.5-3B-Instruct-Q4_K_M.gguf" \
    "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
download_model "Qwen2.5-14B-Instruct-Q4_K_M.gguf" \
    "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf"

if curl -sf http://localhost:11435/health | grep -q '"status":"ok"'; then
    echo "Persistent llama-server is already running and healthy."
else
    echo "Persistent llama-server is not running or not responding properly. Starting/restarting..."
    docker rm -f mcp-llama-server >/dev/null 2>&1 || true
    MG_FLAGS=""
    if command -v nvidia-smi &>/dev/null; then
        GPU_COUNT=$(nvidia-smi --query-gpu=count --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
        if [ "$GPU_COUNT" -gt 1 ] 2>/dev/null; then
            VRAM_LIST=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | tr '\n' ',' | sed 's/,$//')
            if [ -n "$VRAM_LIST" ]; then
                MG_FLAGS="--split-mode layer --tensor-split ${VRAM_LIST}"
            else
                SPLIT=""; for i in $(seq 1 "$GPU_COUNT"); do SPLIT="${SPLIT}${SPLIT:+,}1"; done
                MG_FLAGS="--split-mode layer --tensor-split ${SPLIT}"
            fi
            echo "Multi-GPU detected ($GPU_COUNT GPUs): $MG_FLAGS"
        fi
    fi
    docker run -d --name mcp-llama-server $GPU_FLAGS --net=host -v llama-models:/models mcp-build \
        llama-server -m "/models/$MODEL_FILE" --port 11435 --host 0.0.0.0 -ngl 99 -fa on -c 4096 $MG_FLAGS
    echo "Waiting for persistent llama-server to initialize and complete warmup..."
    LLAMA_READY=false
    for i in $(seq 1 120); do
        if curl -sf http://localhost:11435/health | grep -q '"status":"ok"'; then
            echo "Persistent llama-server is ready!"; LLAMA_READY=true; break
        fi
        sleep 1
    done
    if ! $LLAMA_READY; then
        echo "ERROR: llama-server failed to start or warm up in 120 seconds."; exit 1
    fi
fi

exec docker run --rm $GPU_FLAGS \
    --net=host \
    -e BUF_TOKEN="$BUF_TOKEN" \
    -e HOME=/tmp \
    -e MODEL_FILE="$MODEL_FILE" \
    -v llama-models:/models \
    -v "$(pwd)":/app \
    --user "$(id -u):$(id -g)" \
    mcp-build \
    bash build.sh
