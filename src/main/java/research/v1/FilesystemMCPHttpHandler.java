package research.v1;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.nio.file.Path;
import java.util.List;

/**
 * HTTP (Streamable MCP) handler for the filesystem MCP server.
 * Delegates business logic to {@link FilesystemTool}.
 * Sampling calls {@link OllamaClient} directly for LLM summarization.
 */
public class FilesystemMCPHttpHandler extends McpHttpHandler {

    private final FilesystemTool tool;
    private final MCPLogger log = new MCPLogger("filesystem-mcp-server");

    public FilesystemMCPHttpHandler(Path baseDir) {
        this.tool = new FilesystemTool(baseDir);
    }

    @Override
    protected String serverName() {
        return "filesystem-mcp-server";
    }

    @Override
    protected String serverVersion() {
        return "1.0.0";
    }

    @Override
    protected String serverInstructions() {
        return "Use write_file, read_file, and list_files to manage stored research.";
    }

    @Override
    protected boolean hasTools() {
        return true;
    }

    @Override
    protected boolean hasResourceTemplates() {
        return true;
    }

    @Override
    protected List<ResourceTemplateEntry> listResourceTemplates() {
        return List.of(
            new ResourceTemplateEntry(
                "file:///{path}",
                "File System Resource",
                "Read any file on the server's filesystem using the file:///{path} URI template",
                "text/plain"
            )
        );
    }

    @Override
    protected List<ToolEntry> tools() {
        // write_file schema
        JsonObject writeSchema = new JsonObject();
        writeSchema.addProperty("type", "object");
        JsonObject writeProps = new JsonObject();

        JsonObject nameProp = new JsonObject();
        nameProp.addProperty("type", "string");
        nameProp.addProperty("description", "Output filename");
        writeProps.add("name", nameProp);

        JsonObject contentProp = new JsonObject();
        contentProp.addProperty("type", "string");
        contentProp.addProperty("description", "Text content to write");
        writeProps.add("content", contentProp);

        writeSchema.add("properties", writeProps);
        JsonArray writeRequired = new JsonArray();
        writeRequired.add("name");
        writeRequired.add("content");
        writeSchema.add("required", writeRequired);

        // read_file schema
        JsonObject readSchema = new JsonObject();
        readSchema.addProperty("type", "object");
        JsonObject readProps = new JsonObject();

        JsonObject readNameProp = new JsonObject();
        readNameProp.addProperty("type", "string");
        readNameProp.addProperty("description", "Filename to read");
        readProps.add("name", readNameProp);

        readSchema.add("properties", readProps);
        JsonArray readRequired = new JsonArray();
        readRequired.add("name");
        readSchema.add("required", readRequired);

        return List.of(
            new ToolEntry(
                "write_file",
                "Write text content to a named file in the research store.",
                writeSchema
            ),
            new ToolEntry(
                "read_file",
                "Read the content of a previously stored file by name.",
                readSchema
            ),
            new ToolEntry(
                "list_files",
                "List all files currently in the research store.",
                null  // no parameters
            )
        );
    }

    @Override
    protected String callTool(String name, JsonObject arguments) throws Exception {
        log.agentToTool(getCurrentClientName(), "CallTool", "tool=" + name);
        return switch (name) {
            case "write_file" -> {
                String fileName = arguments.has("name") ? arguments.get("name").getAsString() : "";
                String content = arguments.has("content") ? arguments.get("content").getAsString() : "";
                String raw = tool.writeFile(fileName, content);
                // Summarize via LLM (same behavior as gRPC server)
                String summary;
                log.toolToAgentSampling(getCurrentClientName(), "CreateMessage");
                log.agentToLlm(getCurrentClientName(), "Format report");
                try {
                    summary = OllamaClient.call(
                        "You are a technical writer. Format the following as a clean structured report with a title and bullet points.",
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
                yield summary;
            }
            case "read_file" -> {
                String fileName = arguments.has("name") ? arguments.get("name").getAsString() : "";
                yield tool.readFile(fileName);
            }
            case "list_files" -> tool.listFiles();
            default -> throw new IllegalArgumentException("Unknown tool: " + name);
        };
    }
}
