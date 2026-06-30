package research.v1;

import com.google.gson.JsonObject;
import com.google.protobuf.Struct;
import com.google.protobuf.Value;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import io.grpc.ManagedChannel;
import io.grpc.Metadata;
import io.grpc.Server;
import io.grpc.inprocess.InProcessChannelBuilder;
import io.grpc.inprocess.InProcessServerBuilder;
import io.grpc.stub.MetadataUtils;
import io.grpc.stub.StreamObserver;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

public class McpUnitTest {

    private String serverName;
    private Server inProcessServer;
    private ManagedChannel inProcessChannel;
    private Path tempDir;
    private HttpServer mockHttpServer;
    private int mockHttpPort;

    // Ephemeral gRPC components for callback sampling
    private Server mockClientServer;
    private ManagedChannel mockClientChannel;
    private MockClientService mockClientService;
    private String mockClientServerName;

    private static Metadata agentHeaders(String agentId) {
        Metadata m = new Metadata();
        m.put(AgentIdInterceptor.AGENT_ID_META, agentId);
        return m;
    }

    private MCPServerServiceGrpc.MCPServerServiceBlockingStub getStub(ManagedChannel channel) {
        return MCPServerServiceGrpc.newBlockingStub(channel)
                .withInterceptors(MetadataUtils.newAttachHeadersInterceptor(agentHeaders("test-client")));
    }

    @BeforeEach
    public void setUp() throws Exception {
        serverName = InProcessServerBuilder.generateName();
        mockClientServerName = InProcessServerBuilder.generateName();
        tempDir = Files.createTempDirectory("mcp-test-");

        // 1. Setup mock client callback service for sampling
        mockClientService = new MockClientService();
        mockClientServer = InProcessServerBuilder.forName(mockClientServerName)
                .directExecutor()
                .addService(mockClientService)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        mockClientChannel = InProcessChannelBuilder.forName(mockClientServerName)
                .directExecutor()
                .build();

        // 2. Setup mock HTTP server for WebSearchMCPServerImpl
        mockHttpServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        mockHttpServer.createContext("/api", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                String path = exchange.getRequestURI().getPath();
                byte[] response;
                if (path != null && path.contains("trigger_empty_json")) {
                    response = "{\"AbstractText\": \"\", \"RelatedTopics\": []}".getBytes(StandardCharsets.UTF_8);
                } else if (path != null && path.contains("trigger_error")) {
                    exchange.sendResponseHeaders(500, 0);
                    exchange.close();
                    return;
                } else {
                    response = ("{\n" +
                            "  \"AbstractText\": \"Mock Abstract Text on Java\",\n" +
                            "  \"RelatedTopics\": [\n" +
                            "    { \"Text\": \"Java is a class-based, object-oriented language.\" },\n" +
                            "    { \"Text\": \"Java programming reference manual.\" }\n" +
                            "  ]\n" +
                            "}").getBytes(StandardCharsets.UTF_8);
                }
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, response.length);
                exchange.getResponseBody().write(response);
                exchange.close();
            }
        });

        mockHttpServer.createContext("/html", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                String html = "<html><body>" +
                        "<a class=\"result__snippet\">Snippet 1: Python is dynamically typed.</a>" +
                        "<a class=\"result__snippet\">Snippet 2: Python supports OOP.</a>" +
                        "</body></html>";
                byte[] response = html.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "text/html");
                exchange.sendResponseHeaders(200, response.length);
                exchange.getResponseBody().write(response);
                exchange.close();
            }
        });

        mockHttpServer.start();
        mockHttpPort = mockHttpServer.getAddress().getPort();
    }

    @AfterEach
    public void tearDown() throws Exception {
        if (inProcessChannel != null) {
            inProcessChannel.shutdownNow();
            inProcessChannel.awaitTermination(2, TimeUnit.SECONDS);
        }
        if (inProcessServer != null) {
            inProcessServer.shutdownNow();
            inProcessServer.awaitTermination(2, TimeUnit.SECONDS);
        }
        if (mockClientChannel != null) {
            mockClientChannel.shutdownNow();
            mockClientChannel.awaitTermination(2, TimeUnit.SECONDS);
        }
        if (mockClientServer != null) {
            mockClientServer.shutdownNow();
            mockClientServer.awaitTermination(2, TimeUnit.SECONDS);
        }
        if (mockHttpServer != null) {
            mockHttpServer.stop(0);
        }
        if (tempDir != null && Files.exists(tempDir)) {
            Files.walk(tempDir)
                    .map(Path::toFile)
                    .sorted((f1, f2) -> -f1.compareTo(f2)) // Delete files first, then directories
                    .forEach(java.io.File::delete);
        }
    }

    // -----------------------------------------------------------------------
    // FilesystemMCPServerImpl Tests
    // -----------------------------------------------------------------------

    @Test
    public void testFilesystemServerInitializationAndTools() throws Exception {
        FilesystemMCPServerImpl serverImpl = new FilesystemMCPServerImpl(tempDir);
        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        // Test Initialize
        Mcp.InitializeResponse initResp = stub.initialize(Mcp.InitializeRequest.newBuilder()
                .setProtocolVersion("2025-11-25")
                .setClientInfo(Mcp.ClientInfo.newBuilder()
                        .setName("test-client")
                        .setVersion("1.0.0")
                        .build())
                .build());
        assertEquals("filesystem-mcp-server", initResp.getServerInfo().getName());
        assertTrue(initResp.getCapabilities().hasTools());

        // Test Ping
        Mcp.PingResponse pingResp = stub.ping(Mcp.PingRequest.newBuilder().build());
        assertNotNull(pingResp);

        // Test ListTools
        Mcp.ListToolsResponse toolsResp = stub.listTools(Mcp.ListToolsRequest.newBuilder().build());
        assertEquals(3, toolsResp.getToolsCount());
        List<String> toolNames = toolsResp.getToolsList().stream().map(Mcp.Tool::getName).toList();
        assertTrue(toolNames.contains("write_file"));
        assertTrue(toolNames.contains("read_file"));
        assertTrue(toolNames.contains("list_files"));
    }

    @Test
    public void testFilesystemServerFileOperations() throws Exception {
        FilesystemMCPServerImpl serverImpl = new FilesystemMCPServerImpl(tempDir);
        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        // 1. Initial list_files should be empty
        Mcp.CallToolResponse listResp1 = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("list_files")
                .build());
        assertFalse(listResp1.getIsError());
        assertEquals("", listResp1.getContent(0).getText().getText());

        // 2. Write a file
        Mcp.CallToolResponse writeResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("write_file")
                .setArguments(Struct.newBuilder()
                        .putFields("name", Value.newBuilder().setStringValue("report.txt").build())
                        .putFields("content", Value.newBuilder().setStringValue("Java analysis results").build())
                        .build())
                .build());
        assertFalse(writeResp.getIsError());
        assertTrue(writeResp.getContent(0).getText().getText().contains("Wrote"));

        // 3. Read the file
        Mcp.CallToolResponse readResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("read_file")
                .setArguments(Struct.newBuilder()
                        .putFields("name", Value.newBuilder().setStringValue("report.txt").build())
                        .build())
                .build());
        assertFalse(readResp.getIsError());
        assertEquals("Java analysis results", readResp.getContent(0).getText().getText());

        // 4. Non-existent file read
        Mcp.CallToolResponse readNonExistent = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("read_file")
                .setArguments(Struct.newBuilder()
                        .putFields("name", Value.newBuilder().setStringValue("missing.txt").build())
                        .build())
                .build());
        assertFalse(readNonExistent.getIsError());
        assertTrue(readNonExistent.getContent(0).getText().getText().contains("File not found"));

        // 5. List files should show report.txt
        Mcp.CallToolResponse listResp2 = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("list_files")
                .build());
        assertEquals("report.txt", listResp2.getContent(0).getText().getText());
    }

    @Test
    public void testFilesystemServerWithSampling() throws Exception {
        FilesystemMCPServerImpl serverImpl = new FilesystemMCPServerImpl(tempDir);
        
        // Inject our mock gRPC stub
        MCPClientServiceGrpc.MCPClientServiceBlockingStub mockClientStub =
                MCPClientServiceGrpc.newBlockingStub(mockClientChannel)
                        .withInterceptors(MetadataUtils.newAttachHeadersInterceptor(agentHeaders("test-client")));
        serverImpl.setSamplingClient(mockClientStub);

        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        mockClientService.setResponseText("Mocked Structured Technical Report");

        // Write a file, which triggers sampling when client is present
        Mcp.CallToolResponse writeResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("write_file")
                .setArguments(Struct.newBuilder()
                        .putFields("name", Value.newBuilder().setStringValue("draft.txt").build())
                        .putFields("content", Value.newBuilder().setStringValue("Draft report content").build())
                        .build())
                .build());

        assertFalse(writeResp.getIsError());
        assertEquals("Mocked Structured Technical Report", writeResp.getContent(0).getText().getText());
        assertEquals(1, mockClientService.getReceivedRequests().size());
        assertTrue(mockClientService.getReceivedRequests().get(0).getSystemPrompt().contains("bullet points"));
    }

    // -----------------------------------------------------------------------
    // WebSearchMCPServerImpl Tests
    // -----------------------------------------------------------------------

    @Test
    public void testWebSearchServerPrimaryPath() throws Exception {
        String apiBase = "http://127.0.0.1:" + mockHttpPort + "/api";
        String htmlBase = "http://127.0.0.1:" + mockHttpPort + "/html";
        WebSearchMCPServerImpl serverImpl = new WebSearchMCPServerImpl(apiBase, htmlBase);

        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        // Test Initialize and listTools
        Mcp.InitializeResponse initResp = stub.initialize(Mcp.InitializeRequest.newBuilder()
                .setProtocolVersion("2025-11-25")
                .setClientInfo(Mcp.ClientInfo.newBuilder().setName("test-client").build())
                .build());
        assertEquals("web-search-mcp-server", initResp.getServerInfo().getName());

        Mcp.ListToolsResponse toolsResp = stub.listTools(Mcp.ListToolsRequest.newBuilder().build());
        assertEquals(1, toolsResp.getToolsCount());
        assertEquals("web_search", toolsResp.getTools(0).getName());

        // Test CallTool web_search (primary JSON path)
        Mcp.CallToolResponse searchResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("web_search")
                .setArguments(Struct.newBuilder()
                        .putFields("query", Value.newBuilder().setStringValue("Java programming").build())
                        .build())
                .build());

        assertFalse(searchResp.getIsError());
        String results = searchResp.getContent(0).getText().getText();
        assertTrue(results.contains("Mock Abstract Text on Java"));
        assertTrue(results.contains("class-based, object-oriented"));
    }

    @Test
    public void testWebSearchServerFallbackPath() throws Exception {
        String apiBase = "http://127.0.0.1:" + mockHttpPort + "/api/trigger_empty_json";
        String htmlBase = "http://127.0.0.1:" + mockHttpPort + "/html";
        WebSearchMCPServerImpl serverImpl = new WebSearchMCPServerImpl(apiBase, htmlBase);

        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        // Test CallTool web_search (triggers JSON empty, which falls back to HTML parsing)
        Mcp.CallToolResponse searchResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("web_search")
                .setArguments(Struct.newBuilder()
                        .putFields("query", Value.newBuilder().setStringValue("Python features").build())
                        .build())
                .build());

        assertFalse(searchResp.getIsError());
        String results = searchResp.getContent(0).getText().getText();
        assertTrue(results.contains("Snippet 1: Python is dynamically typed."));
        assertTrue(results.contains("Snippet 2: Python supports OOP."));
    }

    @Test
    public void testWebSearchServerWithSampling() throws Exception {
        String apiBase = "http://127.0.0.1:" + mockHttpPort + "/api";
        String htmlBase = "http://127.0.0.1:" + mockHttpPort + "/html";
        WebSearchMCPServerImpl serverImpl = new WebSearchMCPServerImpl(apiBase, htmlBase);

        // Inject our mock gRPC stub
        MCPClientServiceGrpc.MCPClientServiceBlockingStub mockClientStub =
                MCPClientServiceGrpc.newBlockingStub(mockClientChannel)
                        .withInterceptors(MetadataUtils.newAttachHeadersInterceptor(agentHeaders("test-client")));
        serverImpl.setSamplingClient(mockClientStub);

        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        mockClientService.setResponseText("Mocked Technical Analyst Summary");

        Mcp.CallToolResponse searchResp = stub.callTool(Mcp.CallToolRequest.newBuilder()
                .setName("web_search")
                .setArguments(Struct.newBuilder()
                        .putFields("query", Value.newBuilder().setStringValue("Java programming").build())
                        .build())
                .build());

        assertFalse(searchResp.getIsError());
        assertEquals("Mocked Technical Analyst Summary", searchResp.getContent(0).getText().getText());
        assertEquals(1, mockClientService.getReceivedRequests().size());
        assertTrue(mockClientService.getReceivedRequests().get(0).getSystemPrompt().contains("research analyst"));
    }

    // -----------------------------------------------------------------------
    // Extended Spec Coverage Tests (Autocomplete, Logging, Resources)
    // -----------------------------------------------------------------------

    @Test
    public void testFilesystemServerExtendedAPIs() throws Exception {
        FilesystemMCPServerImpl serverImpl = new FilesystemMCPServerImpl(tempDir);
        inProcessServer = InProcessServerBuilder.forName(serverName)
                .directExecutor()
                .addService(serverImpl)
                .intercept(new AgentIdInterceptor())
                .build()
                .start();

        inProcessChannel = InProcessChannelBuilder.forName(serverName)
                .directExecutor()
                .build();

        MCPServerServiceGrpc.MCPServerServiceBlockingStub stub = getStub(inProcessChannel);

        // 1. Resources should return empty / safe responses
        Mcp.ListResourcesResponse listRes = stub.listResources(Mcp.ListResourcesRequest.newBuilder().build());
        assertEquals(0, listRes.getResourcesCount());

        // 1b. Resource templates — filesystem server advertises file:///{path}
        Mcp.ListResourceTemplatesResponse templatesRes = stub.listResourceTemplates(
                Mcp.ListResourceTemplatesRequest.newBuilder().build());
        assertEquals(1, templatesRes.getResourceTemplatesCount(),
                "Filesystem server should advertise one resource template");
        Mcp.ResourceTemplate tmpl = templatesRes.getResourceTemplates(0);
        assertEquals("file:///{path}", tmpl.getUriTemplate());
        assertEquals("File System Resource", tmpl.getName());
        assertFalse(tmpl.getDescription().isEmpty());
        assertEquals("text/plain", tmpl.getMimeType());

        Mcp.ReadResourceResponse readRes = stub.readResource(Mcp.ReadResourceRequest.newBuilder().setUri("test").build());
        assertEquals(0, readRes.getContentsCount());

        Mcp.SubscribeResourceResponse subRes = stub.subscribeResource(Mcp.SubscribeResourceRequest.newBuilder().setUri("test").build());
        assertNotNull(subRes);

        Mcp.UnsubscribeResourceResponse unsubRes = stub.unsubscribeResource(Mcp.UnsubscribeResourceRequest.newBuilder().setUri("test").build());
        assertNotNull(unsubRes);

        // 2. Complete Request (Autocomplete) should return safe response
        Mcp.CompleteResponse compRes = stub.complete(Mcp.CompleteRequest.newBuilder()
                .setPromptName("prompt")
                .setArgumentName("arg")
                .setCurrentValue("curr")
                .build());
        assertEquals(0, compRes.getCompletionsCount());

        // 3. Prompts API should return safe response
        Mcp.ListPromptsResponse listProm = stub.listPrompts(Mcp.ListPromptsRequest.newBuilder().build());
        assertEquals(0, listProm.getPromptsCount());

        Mcp.GetPromptResponse getProm = stub.getPrompt(Mcp.GetPromptRequest.newBuilder().setName("test").build());
        assertEquals("", getProm.getDescription());
    }

    // -----------------------------------------------------------------------
    // Mock classes for gRPC Sampling callbacks
    // -----------------------------------------------------------------------

    static class MockClientService extends MCPClientServiceGrpc.MCPClientServiceImplBase {
        private String responseText = "Mock response";
        private final List<Mcp.CreateMessageRequest> receivedRequests = new ArrayList<>();

        public void setResponseText(String text) {
            this.responseText = text;
        }

        public List<Mcp.CreateMessageRequest> getReceivedRequests() {
            return receivedRequests;
        }

        @Override
        public void createMessage(Mcp.CreateMessageRequest req, StreamObserver<Mcp.CreateMessageResponse> responseObserver) {
            receivedRequests.add(req);
            responseObserver.onNext(Mcp.CreateMessageResponse.newBuilder()
                    .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_ASSISTANT)
                    .setContent(Mcp.Content.newBuilder()
                            .setText(Mcp.TextContent.newBuilder().setText(responseText)))
                    .setModel("qwen2.5:14b")
                    .setStopReason(Mcp.StopReason.STOP_REASON_END_TURN)
                    .build());
            responseObserver.onCompleted();
        }

        @Override
        public void listRoots(Mcp.ListRootsRequest req, StreamObserver<Mcp.ListRootsResponse> responseObserver) {
            responseObserver.onNext(Mcp.ListRootsResponse.newBuilder()
                    .addRoots(Mcp.Root.newBuilder().setUri("file:///mock/root").setName("mock-root").build())
                    .build());
            responseObserver.onCompleted();
        }
    }
}
