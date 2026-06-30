package research.v1;

import io.grpc.stub.StreamObserver;

// Abstract base class to encapsulate common LLM sampling logic for distributed nodes
public abstract class BaseAgentNode extends MCPClientServiceGrpc.MCPClientServiceImplBase {

    protected final MCPLogger log;

    protected BaseAgentNode(String agentId) {
        this.log = new MCPLogger(agentId);
    }

    @Override
    public void createMessage(Mcp.CreateMessageRequest req, StreamObserver<Mcp.CreateMessageResponse> out) {
        String agent = AgentIdInterceptor.AGENT_ID.get();
        String userText = req.getMessagesCount() > 0
                ? req.getMessages(0).getContent().getText().getText() : "";
        String peer = AgentIdInterceptor.SERVER_NAME.get();
        boolean selfCall = agent.equals(peer);
        if (!selfCall) {
            log.toolToAgentSampling(agent, peer, "\"" + req.getSystemPrompt() + "\"");
            log.agentToLlm(agent, "\"" + req.getSystemPrompt() + "\"");
        }
        try {
            String response = OllamaClient.call(req.getSystemPrompt(), userText,
                    req.getMaxTokens() > 0 ? req.getMaxTokens() : 2048);
            if (!selfCall) {
                log.llmToAgent(agent, "\"" + response.replace("\n", " ").substring(0, Math.min(120, response.length())) + "\"");
                log.agentToToolSampling(agent, peer, "\"" + response.replace("\n", " ").substring(0, Math.min(120, response.length())) + "\"");
            }
            out.onNext(Mcp.CreateMessageResponse.newBuilder()
                    .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_ASSISTANT)
                    .setContent(Mcp.Content.newBuilder()
                            .setText(Mcp.TextContent.newBuilder().setText(response)))
                    .setStopReason(Mcp.StopReason.STOP_REASON_END_TURN)
                    .build());
            out.onCompleted();
        } catch (Exception e) {
            out.onError(io.grpc.Status.INTERNAL
                    .withDescription("llama-server call failed: " + e.getMessage())
                    .asRuntimeException());
        }
    }

    @Override
    public void listRoots(Mcp.ListRootsRequest req, StreamObserver<Mcp.ListRootsResponse> out) {
        out.onNext(Mcp.ListRootsResponse.newBuilder().build());
        out.onCompleted();
    }
}
