FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System packages
RUN apt-get update && apt-get install -y \
    curl wget ca-certificates gnupg \
    python3 python3-pip \
    netcat-openbsd \
    zstd \
    pciutils \
    mesa-vulkan-drivers vulkan-tools libvulkan-dev \
    && rm -rf /var/lib/apt/lists/*

# Java 21 (Amazon Corretto)
RUN curl -fsSL https://apt.corretto.aws/corretto.key | gpg --dearmor -o /usr/share/keyrings/corretto.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/corretto.gpg] https://apt.corretto.aws stable main" \
    > /etc/apt/sources.list.d/corretto.list \
 && apt-get update && apt-get install -y java-21-amazon-corretto-jdk \
 && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-21-amazon-corretto

# Node 26
RUN curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*

# buf CLI
RUN npm install -g @bufbuild/buf@1.71.0

# Python deps
RUN pip3 install --break-system-packages \
    grpcio==1.81.1 \
    grpcio-tools==1.81.1 \
    langgraph==1.2.6 \
    langchain-core==1.4.8 \
    pydantic==2.13.4 \
    typing-extensions==4.15.0

# Download prebuilt llama.cpp Vulkan binary (works on NVIDIA, AMD, Intel)
ARG LLAMA_VERSION=b9837
RUN curl -sL "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_VERSION}/llama-${LLAMA_VERSION}-bin-ubuntu-vulkan-x64.tar.gz" \
    -o /tmp/llama.tar.gz \
 && tar -xzf /tmp/llama.tar.gz -C /tmp \
 && cp -a /tmp/llama-${LLAMA_VERSION}/* /usr/local/lib/ \
 && find /usr/local/lib -maxdepth 1 -type f -executable -exec cp -t /usr/local/bin {} + \
 && ldconfig \
 && rm -rf /tmp/llama*

WORKDIR /app
COPY . .

RUN mkdir -p /models && chmod 755 /models
VOLUME ["/models"]

RUN groupadd -r mcp && useradd -r -g mcp -m -d /home/mcp mcp && chown -R mcp:mcp /app /models
USER mcp
CMD ["bash", "build.sh"]
