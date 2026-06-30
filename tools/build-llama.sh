#!/usr/bin/env bash
set -e
BACKEND=$1

git clone --depth 1 --branch b9837 https://github.com/ggml-org/llama.cpp /tmp/llama
cd /tmp/llama

if [ "$BACKEND" = "cuda" ]; then
    echo "Building llama.cpp with CUDA backend..."
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CUDA=ON
else
    echo "Building llama.cpp with Vulkan backend..."
    cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_VULKAN=ON
fi

cmake --build build -j"$(nproc)"
cp build/bin/llama-server /usr/local/bin/
cp build/src/libllama.so /usr/local/lib/ 2>/dev/null || true
ldconfig
rm -rf /tmp/llama
