// AUTO-GENERATED — DO NOT EDIT.  Modify tools/langgraph_to_proto.py instead.
// Re-run ./build.sh (or ./build-inner.sh inside Docker) to regenerate.

package research.v1;

import io.grpc.ManagedChannelBuilder;
import io.grpc.stub.StreamObserver;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;

public class WebSearchMCPServerImpl extends MCPServerServiceGrpc.MCPServerServiceImplBase {

    private final MCPLogger log = new MCPLogger("web-search-mcp-server");
    private String agent() { return AgentIdInterceptor.AGENT_ID.get(); }
    private volatile MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient;

    public void setSamplingClient(MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient) {
        this.samplingClient = samplingClient;
    }

    public static final java.util.Set<String> NOISE_WORDS = java.util.Set.of("summary", "report", "article", "paper", "write", "research", "find", "search", "details", "info", "information", "a", "an", "the", "for", "on", "of", "and", "about", "to", "in", "with", "writeup", "document");

    private WebSearchTool searchTool;

    public WebSearchMCPServerImpl() {
        this.searchTool = new WebSearchTool();
    }

    public WebSearchMCPServerImpl(String apiBaseUrl, String htmlBaseUrl) {
        this.searchTool = new WebSearchTool(apiBaseUrl, htmlBaseUrl);
    }

private String web_search(String query) throws Exception {
    return searchTool.webSearch(query);
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
                .setServerInfo(Mcp.ServerInfo.newBuilder().setName("web-search-mcp-server").setVersion("1.0.0"))
                .setCapabilities(Mcp.ServerCapabilities.newBuilder()
                        .setTools(Mcp.ToolsCapability.newBuilder().build())
                        .setLogging(Mcp.LoggingCapability.newBuilder().build()))
                .setInstructions("Use the web_search tool to look up current information.")
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
                        .setName("web_search")
                        .setDescription("Search the web for current information. Returns a summary and related topics."))
                .build());
        out.onCompleted();
    }

    @Override
    public void callTool(Mcp.CallToolRequest req, StreamObserver<Mcp.CallToolResponse> out) {
        log.agentToTool(agent(), "CallTool", "tool=" + req.getName());
        try {
            String result = switch (req.getName()) {
                case "web_search" -> {
                    String _raw = web_search(req.getArguments().getFieldsOrThrow("query").getStringValue());
                    if (samplingClient != null) {
                        Mcp.CreateMessageResponse _sample = samplingClient
                                .withInterceptors(io.grpc.stub.MetadataUtils.newAttachHeadersInterceptor(serverNameHeader("web-search-mcp-server")))
                                .createMessage(Mcp.CreateMessageRequest.newBuilder()
                                        .setSystemPrompt("You are a research analyst. List 3-5 key facts from these search results, one short sentence each. Be concise.")
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
    @Override public void listResourceTemplates(Mcp.ListResourceTemplatesRequest r, StreamObserver<Mcp.ListResourceTemplatesResponse> o) {{ o.onNext(Mcp.ListResourceTemplatesResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void readResource(Mcp.ReadResourceRequest r, StreamObserver<Mcp.ReadResourceResponse> o) { o.onNext(Mcp.ReadResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void subscribeResource(Mcp.SubscribeResourceRequest r, StreamObserver<Mcp.SubscribeResourceResponse> o) { o.onNext(Mcp.SubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void unsubscribeResource(Mcp.UnsubscribeResourceRequest r, StreamObserver<Mcp.UnsubscribeResourceResponse> o) { o.onNext(Mcp.UnsubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void watchResources(Mcp.WatchResourcesRequest r, StreamObserver<Mcp.WatchResourcesResponse> o) { o.onCompleted(); }
    @Override public void listPrompts(Mcp.ListPromptsRequest r, StreamObserver<Mcp.ListPromptsResponse> o) { o.onNext(Mcp.ListPromptsResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void getPrompt(Mcp.GetPromptRequest r, StreamObserver<Mcp.GetPromptResponse> o) { o.onNext(Mcp.GetPromptResponse.newBuilder().build()); o.onCompleted(); }
    @Override public void streamLogs(Mcp.LoggingRequest r, StreamObserver<Mcp.LogEntry> o) { o.onCompleted(); }
    @Override public void complete(Mcp.CompleteRequest r, StreamObserver<Mcp.CompleteResponse> o) { o.onNext(Mcp.CompleteResponse.newBuilder().build()); o.onCompleted(); }
}
