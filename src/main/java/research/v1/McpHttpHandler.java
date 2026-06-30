package research.v1;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.logging.Level;
import java.util.logging.Logger;

public abstract class McpHttpHandler implements HttpHandler {

    private static final Logger LOG = Logger.getLogger(McpHttpHandler.class.getName());
    static { LOG.setLevel(Level.WARNING); }

    /** Supported MCP protocol version. */
    protected static final String PROTOCOL_VERSION = "2025-11-25";

    // ---- Abstract methods (implemented by subclasses) ----

    /** Human-readable server name, e.g. "web-search-mcp-server". */
    protected abstract String serverName();

    /** Server version string. */
    protected abstract String serverVersion();

    /** Instructions sent to the client during initialization. */
    protected abstract String serverInstructions();

    /** True if the server exposes tools capability. */
    protected boolean hasTools() { return true; }

    /** True if the server exposes resources capability. */
    protected boolean hasResources() { return false; }

    /** True if the server supports resource templates (e.g. file:///{path}). */
    protected boolean hasResourceTemplates() { return false; }

    /** True if the server exposes prompts capability. */
    protected boolean hasPrompts() { return false; }

    /** True if the server supports logging. */
    protected boolean hasLogging() { return false; }

    /**
     * Return the list of tools this server provides.
     * Each entry has: name, description, inputSchema (as a JsonObject).
     */
    protected abstract List<ToolEntry> tools();

    /**
     * Execute a tool by name with the given JSON arguments.
     * @return the tool result text
     */
    protected abstract String callTool(String name, JsonObject arguments) throws Exception;

    // ---- JSON-RPC routing ----

    @Override
    public void handle(HttpExchange exchange) throws IOException {
        // Only accept POST
        if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
            respond(exchange, 405, errorResponse(null, -32000, "Method Not Allowed"));
            return;
        }

        // Accept header validation per Streamable HTTP spec
        String acceptHeader = exchange.getRequestHeaders().getFirst("Accept");
        if (acceptHeader != null && !acceptHeader.isEmpty()) {
            boolean hasJson = acceptHeader.contains("application/json");
            boolean hasEventStream = acceptHeader.contains("text/event-stream");
            if (!hasJson && !hasEventStream) {
                respond(exchange, 406, errorResponse(null, -32600,
                    "Accept header must include 'application/json' or 'text/event-stream'"));
                return;
            }
        }

        // Read request body
        byte[] bodyBytes = exchange.getRequestBody().readAllBytes();
        String body = new String(bodyBytes, StandardCharsets.UTF_8);

        JsonObject request;
        try {
            request = JsonParser.parseString(body).getAsJsonObject();
        } catch (Exception e) {
            respond(exchange, 400, errorResponse(null, -32700, "Parse error: invalid JSON"));
            return;
        }

        // Validate jsonrpc field per JSON-RPC 2.0 spec
        if (!request.has("jsonrpc") || !"2.0".equals(request.get("jsonrpc").getAsString())) {
            respond(exchange, 400, errorResponse(null, -32600, "Invalid Request: jsonrpc must be '2.0'"));
            return;
        }

        // Extract JSON-RPC fields
        JsonElement idEl = request.get("id");
        String method = request.has("method") ? request.get("method").getAsString() : null;
        JsonObject params = request.has("params") && request.get("params").isJsonObject()
                ? request.get("params").getAsJsonObject() : new JsonObject();

        // JSON-RPC notification (no id) — no response body, HTTP 202 Accepted
        boolean isNotification = (idEl == null || idEl.isJsonNull());

        if (method == null) {
            respond(exchange, 400, errorResponse(idEl, -32600, "Invalid Request: missing method"));
            return;
        }

        try {
            JsonObject response = dispatch(method, params, idEl);
            if (isNotification) {
                // Notifications get HTTP 202 Accepted with no body
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.getResponseHeaders().set("MCP-Protocol-Version", PROTOCOL_VERSION);
                exchange.sendResponseHeaders(202, -1);
                return;
            }
            respond(exchange, 200, response);
        } catch (Exception e) {
            LOG.log(Level.WARNING, "Error handling method: " + method, e);
            if (isNotification) {
                exchange.sendResponseHeaders(202, -1);
                exchange.close();
                return;
            }
            respond(exchange, 500, errorResponse(idEl, -32603, "Internal error: " + e.getMessage()));
        }
    }

    private JsonObject dispatch(String method, JsonObject params, JsonElement id) throws Exception {
        switch (method) {
            case "initialize":
                return handleInitialize(params, id);
            case "notifications/initialized":
                return handleInitializedNotification(id);
            case "resources/templates/list":
                return handleListResourceTemplates(id);
            case "notifications/cancelled":
                return handleNotification(id, "cancelled");
            case "notifications/roots/list_changed":
                return handleNotification(id, "roots_list_changed");
            case "notifications/resources/list_changed":
                return handleNotification(id, "resources_list_changed");
            case "notifications/tools/list_changed":
                return handleNotification(id, "tools_list_changed");
            case "notifications/prompts/list_changed":
                return handleNotification(id, "prompts_list_changed");
            case "ping":
                return handlePing(id);
            case "tools/list":
                return handleListTools(id);
            case "tools/call":
                return handleCallTool(params, id);
            case "sampling/createMessage":
                return handleSampling(params, id);
            default:
                return errorResponse(id, -32601, "Method not found: " + method);
        }
    }

    // ---- Method handlers ----

    private JsonObject handleInitialize(JsonObject params, JsonElement id) {
        String clientName = "unknown";
        String clientVersion = "0.0";
        if (params.has("clientInfo") && params.get("clientInfo").isJsonObject()) {
            JsonObject ci = params.getAsJsonObject("clientInfo");
            clientName = ci.has("name") ? ci.get("name").getAsString() : clientName;
            clientVersion = ci.has("version") ? ci.get("version").getAsString() : clientVersion;
        }
        currentClientName = clientName;
        LOG.info("Initialize from " + clientName + " " + clientVersion);

        JsonObject serverInfo = new JsonObject();
        serverInfo.addProperty("name", serverName());
        serverInfo.addProperty("version", serverVersion());

        // Build capability objects per spec 2025-11-25
        JsonObject capabilities = new JsonObject();
        if (hasTools()) {
            JsonObject toolsCap = new JsonObject();
            toolsCap.addProperty("listChanged", false);
            capabilities.add("tools", toolsCap);
        }
        if (hasResources()) {
            JsonObject resourcesCap = new JsonObject();
            resourcesCap.addProperty("subscribe", false);
            resourcesCap.addProperty("listChanged", false);
            capabilities.add("resources", resourcesCap);
        }
        if (hasPrompts()) {
            JsonObject promptsCap = new JsonObject();
            promptsCap.addProperty("listChanged", false);
            capabilities.add("prompts", promptsCap);
        }
        if (hasLogging()) {
            capabilities.add("logging", new JsonObject());
        }
        if (hasResourceTemplates()) {
            JsonObject rtCap = new JsonObject();
            rtCap.addProperty("listChanged", false);
            capabilities.add("resourceTemplates", rtCap);
        }
        // Sampling: server supports client-side sampling (can request it)
        JsonObject sampling = new JsonObject();
        capabilities.add("sampling", sampling);

        JsonObject result = new JsonObject();
        result.addProperty("protocolVersion", PROTOCOL_VERSION);
        result.add("serverInfo", serverInfo);
        result.add("capabilities", capabilities);
        if (serverInstructions() != null && !serverInstructions().isEmpty()) {
            result.addProperty("instructions", serverInstructions());
        }

        return successResponse(id, result);
    }

    private JsonObject handleInitializedNotification(JsonElement id) {
        LOG.info("Client initialized notification received");
        return successResponse(id, new JsonObject());
    }

    private JsonObject handleNotification(JsonElement id, String type) {
        LOG.info("Notification received: " + type);
        return successResponse(id, new JsonObject());
    }

    private JsonObject handlePing(JsonElement id) {
        return successResponse(id, new JsonObject());
    }


    private JsonObject handleListResourceTemplates(JsonElement id) {
        JsonArray templates = new JsonArray();

        // Subclasses can override listResourceTemplates() to provide templates.
        // Default implementation returns empty list.
        for (ResourceTemplateEntry e : listResourceTemplates()) {
            JsonObject t = new JsonObject();
            t.addProperty("uriTemplate", e.uriTemplate());
            t.addProperty("name", e.name());
            if (e.description() != null) t.addProperty("description", e.description());
            if (e.mimeType() != null) t.addProperty("mimeType", e.mimeType());
            templates.add(t);
        }

        JsonObject result = new JsonObject();
        result.add("resourceTemplates", templates);
        return successResponse(id, result);
    }

    private JsonObject handleListTools(JsonElement id) {
        JsonArray toolsArray = new JsonArray();
        for (ToolEntry t : tools()) {
            JsonObject toolObj = new JsonObject();
            toolObj.addProperty("name", t.name());
            toolObj.addProperty("description", t.description());
            if (t.inputSchema() != null) {
                toolObj.add("inputSchema", t.inputSchema());
            } else {
                // Default empty schema
                JsonObject schema = new JsonObject();
                schema.addProperty("type", "object");
                schema.add("properties", new JsonObject());
                schema.add("required", new JsonArray());
                toolObj.add("inputSchema", schema);
            }
            toolsArray.add(toolObj);
        }

        JsonObject result = new JsonObject();
        result.add("tools", toolsArray);
        return successResponse(id, result);
    }

    private JsonObject handleCallTool(JsonObject params, JsonElement id) throws Exception {
        String name = params.has("name") ? params.get("name").getAsString() : "";
        JsonObject arguments = params.has("arguments") && params.get("arguments").isJsonObject()
                ? params.getAsJsonObject("arguments") : new JsonObject();

        try {
            String resultText = callTool(name, arguments);

            JsonObject contentItem = new JsonObject();
            contentItem.addProperty("type", "text");
            contentItem.addProperty("text", resultText);

            JsonArray content = new JsonArray();
            content.add(contentItem);

            JsonObject result = new JsonObject();
            result.add("content", content);
            result.addProperty("isError", false);
            return successResponse(id, result);
        } catch (IllegalArgumentException e) {
            return errorResponse(id, -32602, e.getMessage());
        }
    }

    private JsonObject handleSampling(JsonObject params, JsonElement id) {
        String systemPrompt = params.has("systemPrompt") && !params.get("systemPrompt").isJsonNull()
                ? params.get("systemPrompt").getAsString() : "";
        String userMessage = "";
        if (params.has("messages") && params.get("messages").isJsonArray()) {
            var msgs = params.getAsJsonArray("messages");
            if (msgs.size() > 0) {
                var last = msgs.get(msgs.size() - 1).getAsJsonObject();
                if (last.has("content")) {
                    var content = last.get("content");
                    if (content.isJsonObject() && content.getAsJsonObject().has("text")) {
                        userMessage = content.getAsJsonObject().get("text").getAsString();
                    } else if (content.isJsonPrimitive()) {
                        userMessage = content.getAsString();
                    }
                }
            }
        }
        int maxTokens = params.has("maxTokens") ? params.get("maxTokens").getAsInt() : 4096;

        try {
            String responseText = OllamaClient.call(systemPrompt, userMessage, maxTokens);

            JsonObject contentItem = new JsonObject();
            contentItem.addProperty("type", "text");
            contentItem.addProperty("text", responseText);

            JsonArray content = new JsonArray();
            content.add(contentItem);

            JsonObject result = new JsonObject();
            result.addProperty("role", "assistant");
            result.add("content", content);
            result.addProperty("model", OllamaClient.MODEL);
            result.addProperty("stopReason", "endTurn");
            return successResponse(id, result);
        } catch (Exception e) {
            LOG.log(Level.WARNING, "Sampling failed", e);
            return errorResponse(id, -32603, "Sampling failed: " + e.getMessage());
        }
    }

    // ---- JSON-RPC envelope helpers ----

    private static JsonObject successResponse(JsonElement id, JsonObject result) {
        JsonObject resp = new JsonObject();
        resp.addProperty("jsonrpc", "2.0");
        resp.add("id", id != null ? id : new JsonObject());
        resp.add("result", result);
        return resp;
    }

    private static JsonObject errorResponse(JsonElement id, int code, String message) {
        JsonObject error = new JsonObject();
        error.addProperty("code", code);
        error.addProperty("message", message);

        JsonObject resp = new JsonObject();
        resp.addProperty("jsonrpc", "2.0");
        resp.add("id", id != null ? id : JsonNull.INSTANCE);
        resp.add("error", error);
        return resp;
    }

    private static void respond(HttpExchange exchange, int status, JsonObject body) throws IOException {
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.getResponseHeaders().set("MCP-Protocol-Version", PROTOCOL_VERSION);
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(bytes);
        }
    }

    // ---- Data record for tool entries ----

    /** Describes a tool exposed to MCP clients. */
    public record ToolEntry(String name, String description, JsonObject inputSchema) {}


    /** Return the list of resource templates, or empty list if not supported. */
    protected List<ResourceTemplateEntry> listResourceTemplates() {
        return List.of();
    }

    public record ResourceTemplateEntry(String uriTemplate, String name, String description, String mimeType) {}

    /** Client identity set during initialize, used for logging. */
    private String currentClientName = "unknown";

    protected String getCurrentClientName() {
        return currentClientName;
    }
}
