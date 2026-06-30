package research.v1;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.List;

/**
 * HTTP (Streamable MCP) handler for the web search MCP server.
 * Delegates business logic to {@link WebSearchTool}.
 * Sampling calls {@link OllamaClient} directly for LLM summarization.
 */
public class WebSearchMCPHttpHandler extends McpHttpHandler {

    private final WebSearchTool tool = new WebSearchTool();
    private final MCPLogger log = new MCPLogger("web-search-mcp-server");

    @Override
    protected String serverName() {
        return "web-search-mcp-server";
    }

    @Override
    protected String serverVersion() {
        return "1.0.0";
    }

    @Override
    protected String serverInstructions() {
        return "Use the web_search tool to look up current information.";
    }

    @Override
    protected boolean hasTools() {
        return true;
    }

    @Override
    protected List<ToolEntry> tools() {
        JsonObject schema = new JsonObject();
        schema.addProperty("type", "object");
        JsonObject props = new JsonObject();
        JsonObject queryProp = new JsonObject();
        queryProp.addProperty("type", "string");
        queryProp.addProperty("description", "The search query");
        props.add("query", queryProp);
        schema.add("properties", props);
        JsonArray required = new JsonArray();
        required.add("query");
        schema.add("required", required);

        return List.of(new ToolEntry(
            "web_search",
            "Search the web for current information. Returns a summary and related topics.",
            schema
        ));
    }

    @Override
    protected String callTool(String name, JsonObject arguments) throws Exception {
        if (!"web_search".equals(name)) {
            throw new IllegalArgumentException("Unknown tool: " + name);
        }
        String query = arguments.has("query") ? arguments.get("query").getAsString() : "";

        log.agentToTool(getCurrentClientName(), "CallTool", "tool=web_search query=" + query);

        // Run the search
        String raw = tool.webSearch(query);

        // Summarize via LLM (same behavior as the gRPC server does via sampling callback)
        String summary;
        log.toolToAgentSampling(getCurrentClientName(), "CreateMessage");
        log.agentToLlm(getCurrentClientName(), "Summarize search results");
        try {
            summary = OllamaClient.call(
                "You are a research analyst. Summarize the most important facts from these search results.",
                raw,
                4096
            );
            log.llmToAgent(getCurrentClientName(), "\"" + summary.replace("\n", " ").substring(0, Math.min(120, summary.length())) + "\"");
            log.agentToToolSampling(getCurrentClientName(), "CreateMessageResult");
        } catch (Exception e) {
            log.llmToAgent(getCurrentClientName(), "LLM failed: " + e.getMessage());
            log.agentToToolSampling(getCurrentClientName(), "CreateMessageResult (failed)");
            summary = raw;
        }

        log.toolToAgent(getCurrentClientName(), "CallTool",
            "\"" + summary.replace("\n", " ").substring(0, Math.min(120, summary.length())) + "\"");
        return summary;
    }
}
