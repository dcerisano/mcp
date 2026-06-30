// AUTO-GENERATED — DO NOT EDIT.  Modify tools/langgraph_to_proto.py instead.
// Re-run ./build.sh (or ./build-inner.sh inside Docker) to regenerate.

package research.v1;

import io.grpc.ManagedChannelBuilder;
import io.grpc.stub.StreamObserver;
import java.nio.file.Path;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Collectors;

public class FilesystemMCPServerImpl extends MCPServerServiceGrpc.MCPServerServiceImplBase {

    private final MCPLogger log = new MCPLogger("filesystem-mcp-server");
    private String agent() { return AgentIdInterceptor.AGENT_ID.get(); }
    private volatile MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient;

    public void setSamplingClient(MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient) {
        this.samplingClient = samplingClient;
    }


private final FilesystemTool fileTool;

public FilesystemMCPServerImpl(Path baseDir) {
    this.fileTool = new FilesystemTool(baseDir);
}

private String write_file(String name, String content) throws Exception {
    return fileTool.writeFile(name, content);
}

private String read_file(String name) throws Exception {
    return fileTool.readFile(name);
}

private String list_files() throws Exception {
    return fileTool.listFiles();
}

    @Override
    public void initialize(Mcp.InitializeRequest req, StreamObserver<Mcp.InitializeResponse> out) {
        String callbackAddr = req.getClientInfo().getCallbackAddress();
        if (!callbackAddr.isEmpty()) {
            samplingClient = MCPClientServiceGrpc.newBlockingStub(
                    ManagedChannelBuilder.forTarget(callbackAddr).usePlaintext().build());
            log.agentToTool(agent(), "Initialize", "client=" + req.getClientInfo().getName() + " callback=" + callbackAddr);
        } else {
            log.agentToTool(agent(), "Initialize", "client=" + req.getClientInfo().getName() + " (no callback)");
        }
        out.onNext(Mcp.InitializeResponse.newBuilder()
                .setProtocolVersion(req.getProtocolVersion())
                .setServerInfo(Mcp.ServerInfo.newBuilder().setName("filesystem-mcp-server").setVersion("1.0.0"))
                .setCapabilities(Mcp.ServerCapabilities.newBuilder()
                        .setTools(Mcp.ToolsCapability.newBuilder().build())
                        .setLogging(Mcp.LoggingCapability.newBuilder().build()))
                .setInstructions("Use write_file, read_file, and list_files to manage stored research.")
                .build());
        out.onCompleted();
    }

    @Override
    public void ping(Mcp.PingRequest req, StreamObserver<Mcp.PingResponse> out) {
        log.agentToTool(agent(), "Ping", "");
        out.onNext(Mcp.PingResponse.newBuilder().build());
        out.onCompleted();
    }

    @Override
    public void listTools(Mcp.ListToolsRequest req, StreamObserver<Mcp.ListToolsResponse> out) {
        log.agentToTool(agent(), "ListTools", "");
        out.onNext(Mcp.ListToolsResponse.newBuilder()
                .addTools(Mcp.Tool.newBuilder()
                        .setName("write_file")
                        .setDescription("Write text content to a named file in the research store."))
                .addTools(Mcp.Tool.newBuilder()
                        .setName("read_file")
                        .setDescription("Read the content of a previously stored file by name."))
                .addTools(Mcp.Tool.newBuilder()
                        .setName("list_files")
                        .setDescription("List all files currently in the research store."))
                .build());
        out.onCompleted();
    }

    @Override
    public void callTool(Mcp.CallToolRequest req, StreamObserver<Mcp.CallToolResponse> out) {
        log.agentToTool(agent(), "CallTool", "tool=" + req.getName());
        try {
            String result = switch (req.getName()) {
                case "write_file" -> {
                    String _raw = write_file(req.getArguments().getFieldsOrThrow("name").getStringValue(), req.getArguments().getFieldsOrThrow("content").getStringValue());
                    if (samplingClient != null) {
                        Mcp.CreateMessageResponse _sample = samplingClient
                                .withInterceptors(io.grpc.stub.MetadataUtils.newAttachHeadersInterceptor(serverNameHeader("filesystem-mcp-server")))
                                .createMessage(Mcp.CreateMessageRequest.newBuilder()
                                        .setSystemPrompt("Format the following as 2-3 bullet points. Be concise.")
                                        .addMessages(Mcp.SamplingMessage.newBuilder()
                                                .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER)
                                                .setContent(Mcp.Content.newBuilder()
                                                        .setText(Mcp.TextContent.newBuilder().setText(_raw))))
                                        .setMaxTokens(1024)
                                        .build());
                        String _sampleText = _sample.getContent().getText().getText();
                        yield _sampleText;
                    }
                    yield _raw;
                }
                case "read_file" -> read_file(req.getArguments().getFieldsOrThrow("name").getStringValue());
                case "list_files" -> list_files();
                default -> "Unknown tool: " + req.getName();
            };
            log.toolToAgent(agent(), "CallTool",
                    "\"" + result.replace("\n", " ").substring(0, Math.min(120, result.length())) + "\"");
            out.onNext(Mcp.CallToolResponse.newBuilder()
                    .addContent(Mcp.Content.newBuilder().setText(Mcp.TextContent.newBuilder().setText(result)))
                    .setIsError(false).build());
            out.onCompleted();
        } catch (Exception e) {
            out.onError(io.grpc.Status.INTERNAL.withDescription(e.getMessage()).asRuntimeException());
        }
    }

    private io.grpc.Metadata serverNameHeader(String name) {
        io.grpc.Metadata m = new io.grpc.Metadata();
        m.put(io.grpc.Metadata.Key.of("server-name", io.grpc.Metadata.ASCII_STRING_MARSHALLER), name);
        m.put(AgentIdInterceptor.AGENT_ID_META, agent());
        return m;
    }

    @Override
    public void notify(Mcp.NotifyRequest req, StreamObserver<Mcp.NotifyResponse> out) {
        if (req.hasInitialized()) {
            log.agentToTool(agent(), "Notify", "initialized");
        }
        if (req.hasCancelled()) {
            log.agentToTool(agent(), "Notify", "cancelled");
        }
        if (req.hasRootsListChanged()) {
            log.agentToTool(agent(), "Notify", "roots_list_changed");
        }
        if (req.hasResourceListChanged()) {
            log.agentToTool(agent(), "Notify", "resource_list_changed");
        }
        if (req.hasToolListChanged()) {
            log.agentToTool(agent(), "Notify", "tool_list_changed");
        }
        if (req.hasPromptListChanged()) {
            log.agentToTool(agent(), "Notify", "prompt_list_changed");
        }
        out.onNext(Mcp.NotifyResponse.newBuilder().build());
        out.onCompleted();
    }

    @Override public void listResources(Mcp.ListResourcesRequest r, StreamObserver<Mcp.ListResourcesResponse> o) { o.onNext(Mcp.ListResourcesResponse.newBuilder().build()); o.onCompleted(); }
    @Override
    public void listResourceTemplates(Mcp.ListResourceTemplatesRequest req, StreamObserver<Mcp.ListResourceTemplatesResponse> out) {{
        Mcp.ResourceTemplate template = Mcp.ResourceTemplate.newBuilder()
                .setUriTemplate("file:///{path}")
                .setName("File System Resource")
                .setDescription("Read any file on the server's filesystem using the file:///{path} URI template")
                .setMimeType("text/plain")
                .build();
        log.agentToTool(agent(), "ListResourceTemplates", "");
        out.onNext(Mcp.ListResourceTemplatesResponse.newBuilder()
                .addResourceTemplates(template)
                .build());
        out.onCompleted();
    }}
    @Override public void readResource(Mcp.ReadResourceRequest r, StreamObserver<Mcp.ReadResourceResponse> o) { o.onNext(Mcp.ReadResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void subscribeResource(Mcp.SubscribeResourceRequest r, StreamObserver<Mcp.SubscribeResourceResponse> o) { o.onNext(Mcp.SubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void unsubscribeResource(Mcp.UnsubscribeResourceRequest r, StreamObserver<Mcp.UnsubscribeResourceResponse> o) { o.onNext(Mcp.UnsubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void watchResources(Mcp.WatchResourcesRequest r, StreamObserver<Mcp.WatchResourcesResponse> o) { o.onCompleted(); }
    @Override public void listPrompts(Mcp.ListPromptsRequest r, StreamObserver<Mcp.ListPromptsResponse> o) { o.onNext(Mcp.ListPromptsResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void getPrompt(Mcp.GetPromptRequest r, StreamObserver<Mcp.GetPromptResponse> o) { o.onNext(Mcp.GetPromptResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void streamLogs(Mcp.LoggingRequest r, StreamObserver<Mcp.LogEntry> o) { o.onCompleted(); }
    @Override public void complete(Mcp.CompleteRequest r, StreamObserver<Mcp.CompleteResponse> o) { o.onNext(Mcp.CompleteResponse.newBuilder().build()); o.onCompleted(); }
}
