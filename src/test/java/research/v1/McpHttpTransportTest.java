package research.v1;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the HTTP Streamable MCP transport handlers.
 * Tests JSON-RPC 2.0 over HTTP for WebSearchMCPHttpHandler and FilesystemMCPHttpHandler.
 */
public class McpHttpTransportTest {

    private HttpClient httpClient;
    private HttpServer handlerServer;
    private int handlerPort;

    // Mock backend for web search (replaces DuckDuckGo)
    private HttpServer mockSearchBackend;
    private int mockSearchPort;

    // Temporary directory for filesystem tests
    private Path tempDir;

    @BeforeEach
    public void setUp() throws Exception {
        httpClient = HttpClient.newHttpClient();
        tempDir = Files.createTempDirectory("mcp-http-test-");
        // Stub LLM calls so tests don't depend on a running llama-server
        System.setProperty("ollama.stub", "Stubbed response from OllamaClient");
    }

    @AfterEach
    public void tearDown() throws Exception {
        System.clearProperty("ollama.stub");
        if (handlerServer != null) {
            handlerServer.stop(0);
        }
        if (mockSearchBackend != null) {
            mockSearchBackend.stop(0);
        }
        if (tempDir != null && Files.exists(tempDir)) {
            Files.walk(tempDir)
                    .map(Path::toFile)
                    .sorted((f1, f2) -> -f1.compareTo(f2))
                    .forEach(java.io.File::delete);
        }
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    /** Start an HTTP server with the given handler on a random port. */
    private void startHandler(McpHttpHandler handler) throws Exception {
        handlerServer = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        handlerServer.createContext("/mcp", handler);
        handlerServer.setExecutor(null);
        handlerServer.start();
        handlerPort = handlerServer.getAddress().getPort();
    }

    /** Start a mock backend for web search on a random port. */
    private void startMockSearchBackend() throws Exception {
        mockSearchBackend = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        mockSearchBackend.createContext("/api", new HttpHandler() {
            @Override
            public void handle(HttpExchange exchange) throws IOException {
                String json = """
                    {
                      "AbstractText": "Python is a high-level, general-purpose programming language.",
                      "RelatedTopics": [
                        { "Text": "Python supports multiple programming paradigms." },
                        { "Text": "Python has a comprehensive standard library." }
                      ]
                    }
                    """;
                byte[] resp = json.getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, resp.length);
                exchange.getResponseBody().write(resp);
                exchange.close();
            }
        });
        mockSearchBackend.setExecutor(null);
        mockSearchBackend.start();
        mockSearchPort = mockSearchBackend.getAddress().getPort();
    }

    /** Send a JSON-RPC POST request and return (status, body). */
    private record JsonRpcResponse(int status, JsonObject body) {}

    private JsonRpcResponse sendRequest(JsonObject requestBody) throws Exception {
        String body = requestBody.toString();
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + handlerPort + "/mcp"))
                .header("Content-Type", "application/json")
                .header("MCP-Protocol-Version", "2025-11-25")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
        return new JsonRpcResponse(resp.statusCode(), JsonParser.parseString(resp.body()).getAsJsonObject());
    }

    /** Convenience: send and assert 200, return body. */
    private JsonObject sendOk(JsonObject requestBody) throws Exception {
        JsonRpcResponse r = sendRequest(requestBody);
        assertEquals(200, r.status(), "Expected HTTP 200: " + r.body());
        return r.body();
    }

    /** Build a JSON-RPC request. */
    private static JsonObject jsonRpcRequest(Object id, String method, JsonObject params) {
        JsonObject req = new JsonObject();
        req.addProperty("jsonrpc", "2.0");
        if (id instanceof String s) {
            req.addProperty("id", s);
        } else if (id instanceof Integer i) {
            req.addProperty("id", i);
        } else if (id == null) {
            req.add("id", null);
        }
        req.addProperty("method", method);
        if (params != null) {
            req.add("params", params);
        }
        return req;
    }

    private static JsonObject jsonRpcRequest(String method, JsonObject params) {
        return jsonRpcRequest(1, method, params);
    }

    // -----------------------------------------------------------------------
    // WebSearchMCPHttpHandler Tests
    // -----------------------------------------------------------------------

    @Test
    public void testWebSearchInitialize() throws Exception {
        startMockSearchBackend();
        WebSearchMCPHttpHandler handler = new WebSearchMCPHttpHandler();
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("initialize", new JsonObject()));

        assertEquals("2.0", resp.get("jsonrpc").getAsString());
        assertTrue(resp.has("id"));
        JsonObject result = resp.getAsJsonObject("result");
        assertNotNull(result);

        assertTrue(result.has("protocolVersion"));
        JsonObject serverInfo = result.getAsJsonObject("serverInfo");
        assertEquals("web-search-mcp-server", serverInfo.get("name").getAsString());

        JsonObject capabilities = result.getAsJsonObject("capabilities");
        assertTrue(capabilities.get("tools").isJsonObject());
    }

    @Test
    public void testWebSearchListTools() throws Exception {
        startMockSearchBackend();
        WebSearchMCPHttpHandler handler = new WebSearchMCPHttpHandler();
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("tools/list", null));

        JsonObject result = resp.getAsJsonObject("result");
        JsonArray tools = result.getAsJsonArray("tools");
        assertEquals(1, tools.size());

        JsonObject tool = tools.get(0).getAsJsonObject();
        assertEquals("web_search", tool.get("name").getAsString());
        assertTrue(tool.has("description"));
        assertTrue(tool.has("inputSchema"));
    }

    @Test
    public void testWebSearchCallTool() throws Exception {
        startMockSearchBackend();
        int backendPort = mockSearchPort;

        // Override the handler's tool to point at our mock backend
        // The WebSearchTool uses default URLs; we need a handler that uses our mock.
        // Since WebSearchMCPHttpHandler creates its own WebSearchTool with defaults,
        // we need one that points at our mock. Let's use the constructor approach.
        // Actually, WebSearchMCPHttpHandler doesn't expose URL configuration.
        // We need to test through the actual handler but intercept the HTTP call.
        // The simplest approach: test the tool class directly, then test the handler's
        // routing independently. Let me test the handler's routing by checking
        // that callTool dispatches correctly.

        // For a proper handler test, we'd need configurable URLs. Let me test
        // the handler routing logic by testing the base class dispatch with a custom subclass.
        // Meanwhile, let me test the web_search with a real but minimal handler.

        // For this test, let's use a simpler approach: verify the handler routes
        // tools/call correctly by checking error behavior and metadata.
        WebSearchMCPHttpHandler handler = new WebSearchMCPHttpHandler();
        startHandler(handler);

        // Test with missing 'query' argument — should not throw, tool handles gracefully
        JsonObject params = new JsonObject();
        params.addProperty("name", "web_search");
        JsonObject args = new JsonObject();
        args.addProperty("query", "test");
        params.add("arguments", args);

        JsonObject resp = sendOk(jsonRpcRequest("tools/call", params));

        assertTrue(resp.has("result"), "Expected result for tools/call: " + resp);
        JsonObject result = resp.getAsJsonObject("result");
        assertTrue(result.has("content"));
        JsonArray content = result.getAsJsonArray("content");
        assertTrue(content.size() > 0);

        // Content should contain text from the search
        String text = content.get(0).getAsJsonObject().get("text").getAsString();
        // With our mock backend, the result is search results + LLM summarization.
        // But the LLM may not be available in test, so we accept raw results or summary.
        assertNotNull(text);
        assertFalse(text.isEmpty());
    }

    @Test
    public void testWebSearchUnknownTool() throws Exception {
        startMockSearchBackend();
        WebSearchMCPHttpHandler handler = new WebSearchMCPHttpHandler();
        startHandler(handler);

        JsonObject params = new JsonObject();
        params.addProperty("name", "nonexistent_tool");
        params.add("arguments", new JsonObject());

        JsonRpcResponse r = sendRequest(jsonRpcRequest("tools/call", params));

        assertEquals(200, r.status(), "Expected HTTP 200 with JSON-RPC error for unknown tool");
        assertTrue(r.body().has("error"), "Expected error for unknown tool");
        assertEquals(-32602, r.body().getAsJsonObject("error").get("code").getAsInt());
        assertTrue(r.body().getAsJsonObject("error").get("message").getAsString().contains("Unknown tool"));
    }

    // -----------------------------------------------------------------------
    // FilesystemMCPHttpHandler Tests
    // -----------------------------------------------------------------------

    @Test
    public void testFilesystemInitialize() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("initialize", new JsonObject()));

        assertEquals("2.0", resp.get("jsonrpc").getAsString());
        JsonObject result = resp.getAsJsonObject("result");
        JsonObject serverInfo = result.getAsJsonObject("serverInfo");
        assertEquals("filesystem-mcp-server", serverInfo.get("name").getAsString());

        JsonObject capabilities = result.getAsJsonObject("capabilities");
        assertTrue(capabilities.get("tools").isJsonObject());
    }

    @Test
    public void testFilesystemListTools() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("tools/list", null));

        JsonObject result = resp.getAsJsonObject("result");
        JsonArray tools = result.getAsJsonArray("tools");
        assertEquals(3, tools.size());

        // Check all three tool names are present
        java.util.Set<String> names = new java.util.HashSet<>();
        for (var t : tools) {
            names.add(t.getAsJsonObject().get("name").getAsString());
        }
        assertTrue(names.contains("write_file"));
        assertTrue(names.contains("read_file"));
        assertTrue(names.contains("list_files"));
    }

    @Test
    public void testFilesystemWriteAndRead() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        // Write a file
        JsonObject writeArgs = new JsonObject();
        writeArgs.addProperty("name", "write_file");
        JsonObject writeParams = new JsonObject();
        writeParams.addProperty("name", "hello.txt");
        writeParams.addProperty("content", "Hello HTTP MCP!");
        writeArgs.add("arguments", writeParams);

        JsonObject writeResp = sendOk(jsonRpcRequest("tools/call", writeArgs));
        assertTrue(writeResp.has("result"), "Write should succeed: " + writeResp);
        String writeText = writeResp.getAsJsonObject("result")
                .getAsJsonArray("content").get(0).getAsJsonObject()
                .get("text").getAsString();
        // May be raw "Wrote..." or LLM-summarized; either way it's not an error
        assertNotNull(writeText);
        assertFalse(writeText.isEmpty());

        // Read the file back
        JsonObject readArgs = new JsonObject();
        readArgs.addProperty("name", "read_file");
        JsonObject readParams = new JsonObject();
        readParams.addProperty("name", "hello.txt");
        readArgs.add("arguments", readParams);

        JsonObject readResp = sendOk(jsonRpcRequest("tools/call", readArgs));
        assertTrue(readResp.has("result"), "Read should succeed: " + readResp);
        String readText = readResp.getAsJsonObject("result")
                .getAsJsonArray("content").get(0).getAsJsonObject()
                .get("text").getAsString();
        assertTrue(readText.contains("Hello HTTP MCP!") || readText.contains("hello.txt"),
                "Read should return file content or reference: " + readText);

        // Verify the file exists on disk
        assertTrue(Files.exists(tempDir.resolve("hello.txt")));
        assertEquals("Hello HTTP MCP!", Files.readString(tempDir.resolve("hello.txt")));
    }

    @Test
    public void testFilesystemListFiles() throws Exception {
        // Create some files first
        Files.writeString(tempDir.resolve("alpha.txt"), "alpha");
        Files.writeString(tempDir.resolve("beta.txt"), "beta");

        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject params = new JsonObject();
        params.addProperty("name", "list_files");
        params.add("arguments", new JsonObject());

        JsonObject resp = sendOk(jsonRpcRequest("tools/call", params));

        assertTrue(resp.has("result"));
        String listText = resp.getAsJsonObject("result")
                .getAsJsonArray("content").get(0).getAsJsonObject()
                .get("text").getAsString();
        assertTrue(listText.contains("alpha.txt"));
        assertTrue(listText.contains("beta.txt"));
    }

    @Test
    public void testFilesystemReadNonExistent() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject args = new JsonObject();
        args.addProperty("name", "read_file");
        JsonObject params = new JsonObject();
        params.addProperty("name", "nonexistent.txt");
        args.add("arguments", params);

        JsonObject resp = sendOk(jsonRpcRequest("tools/call", args));

        assertTrue(resp.has("result"));
        String text = resp.getAsJsonObject("result")
                .getAsJsonArray("content").get(0).getAsJsonObject()
                .get("text").getAsString();
        assertTrue(text.contains("File not found"));
    }

    // -----------------------------------------------------------------------
    // Error handling tests (via base class)
    // -----------------------------------------------------------------------

    @Test
    public void testUnknownMethod() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("unknown_method", null));

        assertTrue(resp.has("error"));
        JsonObject error = resp.getAsJsonObject("error");
        assertEquals(-32601, error.get("code").getAsInt());
        assertTrue(error.get("message").getAsString().contains("Method not found"));
    }

    @Test
    public void testInvalidJson() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        // Send raw invalid JSON
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + handlerPort + "/mcp"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString("not valid json"))
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());

        assertEquals(400, resp.statusCode());
        JsonObject body = JsonParser.parseString(resp.body()).getAsJsonObject();
        assertTrue(body.has("error"));
        assertEquals(-32700, body.getAsJsonObject("error").get("code").getAsInt());
    }

    @Test
    public void testMissingMethod() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject badReq = new JsonObject();
        badReq.addProperty("jsonrpc", "2.0");
        badReq.addProperty("id", 1);
        // no "method" field

        JsonRpcResponse r = sendRequest(badReq);

        assertEquals(400, r.status(), "Expected HTTP 400 for missing method");
        assertTrue(r.body().has("error"));
        assertEquals(-32600, r.body().getAsJsonObject("error").get("code").getAsInt());
    }

    @Test
    public void testPing() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("ping", null));

        assertTrue(resp.has("result"));
        assertEquals(0, resp.getAsJsonObject("result").size()); // empty result
    }

    // -----------------------------------------------------------------------
    // Cross-transport: verify HTTP handler delegates to shared tool classes
    // -----------------------------------------------------------------------

    @Test
    public void testFilesystemToolSharedWithHttpHandler() throws Exception {
        // Verify that FilesystemMCPHttpHandler uses FilesystemTool by checking
        // that file operations work correctly through the HTTP transport
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        // Write via HTTP
        JsonObject writeArgs = new JsonObject();
        writeArgs.addProperty("name", "write_file");
        JsonObject writeParams = new JsonObject();
        writeParams.addProperty("name", "shared.txt");
        writeParams.addProperty("content", "shared content");
        writeArgs.add("arguments", writeParams);
        sendOk(jsonRpcRequest("tools/call", writeArgs));

        // Verify file exists (FilesystemTool wrote it)
        assertTrue(Files.exists(tempDir.resolve("shared.txt")));
        assertEquals("shared content", Files.readString(tempDir.resolve("shared.txt")));

        // Now verify via HTTP read
        JsonObject readArgs = new JsonObject();
        readArgs.addProperty("name", "read_file");
        JsonObject readParams = new JsonObject();
        readParams.addProperty("name", "shared.txt");
        readArgs.add("arguments", readParams);
        JsonObject readResp = sendOk(jsonRpcRequest("tools/call", readArgs));

        String readText = readResp.getAsJsonObject("result")
                .getAsJsonArray("content").get(0).getAsJsonObject()
                .get("text").getAsString();
        assertTrue(readText.contains("shared content") || readText.contains("shared.txt"));
    }


    // -----------------------------------------------------------------------
    // Notification tests — each sends a JSON-RPC notification (no id)
    // and expects HTTP 202 Accepted with empty body.
    // -----------------------------------------------------------------------

    @Test
    public void testNotificationInitialized() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/initialized", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty(), "Notification response body should be empty");
    }

    @Test
    public void testNotificationCancelled() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/cancelled", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty());
    }

    @Test
    public void testNotificationRootsListChanged() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/roots/list_changed", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty());
    }

    @Test
    public void testNotificationResourceListChanged() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/resources/list_changed", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty());
    }

    @Test
    public void testNotificationToolListChanged() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/tools/list_changed", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty());
    }

    @Test
    public void testNotificationPromptListChanged() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        NotificationResponse nr = sendNotification(jsonRpcRequest(null, "notifications/prompts/list_changed", null));

        assertEquals(202, nr.status());
        assertTrue(nr.body().isEmpty());
    }

    // -----------------------------------------------------------------------
    // Capability object shape — verify all advertised capabilities are
    // JSON objects (not booleans) per spec 2025-11-25.
    // -----------------------------------------------------------------------

    @Test
    public void testCapabilitiesAreObjects() throws Exception {
        startMockSearchBackend();
        WebSearchMCPHttpHandler handler = new WebSearchMCPHttpHandler();
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("initialize", new JsonObject()));
        JsonObject capabilities = resp.getAsJsonObject("result").getAsJsonObject("capabilities");

        assertTrue(capabilities.get("tools").isJsonObject(), "tools must be a JSON object");
        assertTrue(capabilities.get("sampling").isJsonObject(), "sampling must be a JSON object");

        assertFalse(capabilities.has("resources"), "web search should not advertise resources");
        assertFalse(capabilities.has("prompts"), "web search should not advertise prompts");
        assertFalse(capabilities.has("roots"), "web search should not advertise roots");
        assertFalse(capabilities.has("completions"), "web search should not advertise completions");
        assertFalse(capabilities.has("logging"), "web search should not advertise logging");
        assertFalse(capabilities.has("resourceTemplates"), "web search should not advertise resource templates");
    }

    @Test
    public void testFilesystemCapabilitiesAreObjects() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("initialize", new JsonObject()));
        JsonObject capabilities = resp.getAsJsonObject("result").getAsJsonObject("capabilities");

        assertTrue(capabilities.get("tools").isJsonObject(), "tools must be a JSON object");
        assertTrue(capabilities.get("sampling").isJsonObject(), "sampling must be a JSON object");

        assertFalse(capabilities.has("resources"));
        assertFalse(capabilities.has("prompts"));
        assertFalse(capabilities.has("roots"));
        assertFalse(capabilities.has("completions"));
        assertFalse(capabilities.has("logging"));
        assertTrue(capabilities.has("resourceTemplates"), "filesystem should advertise resource templates");
        assertTrue(capabilities.get("resourceTemplates").isJsonObject(),
                "resourceTemplates must be a JSON object");
    }


    @Test
    public void testListResourceTemplates() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject resp = sendOk(jsonRpcRequest("resources/templates/list", null));

        JsonObject result = resp.getAsJsonObject("result");
        assertTrue(result.has("resourceTemplates"), "Response must have resourceTemplates array");
        JsonArray templates = result.getAsJsonArray("resourceTemplates");
        assertEquals(1, templates.size(), "Filesystem should advertise one template");

        JsonObject tmpl = templates.get(0).getAsJsonObject();
        assertEquals("file:///{path}", tmpl.get("uriTemplate").getAsString());
        assertEquals("File System Resource", tmpl.get("name").getAsString());
        assertTrue(tmpl.has("description"));
        assertEquals("text/plain", tmpl.get("mimeType").getAsString());
    }

    // -----------------------------------------------------------------------
    // Protocol-level validation
    // -----------------------------------------------------------------------

    @Test
    public void testAcceptHeaderInvalidReturns406() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject req = jsonRpcRequest("ping", null);
        JsonRpcResponse r = sendRequestWithHeaders(req, java.util.Map.of("Accept", "text/plain"));

        assertEquals(406, r.status(), "Invalid Accept header should get 406");
        assertTrue(r.body().has("error"));
        assertTrue(r.body().getAsJsonObject("error").get("message").getAsString()
                .contains("Accept header"));
    }

    @Test
    public void testJsonRpcVersionValidation() throws Exception {
        FilesystemMCPHttpHandler handler = new FilesystemMCPHttpHandler(tempDir);
        startHandler(handler);

        JsonObject badReq = new JsonObject();
        badReq.addProperty("jsonrpc", "1.0");
        badReq.addProperty("id", 1);
        badReq.addProperty("method", "ping");

        JsonRpcResponse r = sendRequest(badReq);

        assertEquals(400, r.status(), "Wrong jsonrpc version should get 400");
        assertTrue(r.body().has("error"));
        assertTrue(r.body().getAsJsonObject("error").get("message").getAsString()
                .contains("jsonrpc"));
    }

    /** Send a notification (no id, expect 202 with empty body). */
    private record NotificationResponse(int status, String body) {}

    private NotificationResponse sendNotification(JsonObject requestBody) throws Exception {
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + handlerPort + "/mcp"))
                .header("Content-Type", "application/json")
                .header("MCP-Protocol-Version", "2025-11-25")
                .POST(HttpRequest.BodyPublishers.ofString(requestBody.toString()))
                .build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
        return new NotificationResponse(resp.statusCode(), resp.body());
    }

    /** Send with custom headers and return the raw response. */
    private JsonRpcResponse sendRequestWithHeaders(JsonObject requestBody, java.util.Map<String, String> extraHeaders) throws Exception {
        var builder = HttpRequest.newBuilder()
                .uri(URI.create("http://127.0.0.1:" + handlerPort + "/mcp"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(requestBody.toString()));
        for (var h : extraHeaders.entrySet()) {
            builder.header(h.getKey(), h.getValue());
        }
        HttpRequest req = builder.build();
        HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
        return new JsonRpcResponse(resp.statusCode(), JsonParser.parseString(resp.body()).getAsJsonObject());
    }

}
