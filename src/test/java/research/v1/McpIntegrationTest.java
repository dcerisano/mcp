package research.v1;

import io.grpc.Server;
import io.grpc.ServerBuilder;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class McpIntegrationTest {

    private static final int TOTAL = 1;
    private static int testNumber = 0;

    private static void section(String title) {
        testNumber++;
        System.out.println("\n=== TEST " + testNumber + " of " + TOTAL + ": " + title + " ===");
    }
    private static void print(String label, Object value) { System.out.println("[" + label + "] " + value); }
    private static void divider() { System.out.println("--------------------------------------------------------------"); }

    @Test
    public void research_orchestration_loop() throws Exception {
        section("Research agent loop - multi-agent end-to-end orchestration via GraphRunner");
        String researchQuestion = "Research the Python programming language and write a summary report";
        print("Research question", researchQuestion);
        divider();

        SupervisorNode supervisorNode = new SupervisorNode();
        ResearchAgentNode researchNode = new ResearchAgentNode();
        WriterAgentNode writerNode = new WriterAgentNode();

        Server supervisorServer = ServerBuilder.forPort(50053)
                .addService(supervisorNode)
                .intercept(new AgentIdInterceptor())
                .build().start();

        Server researchServer = ServerBuilder.forPort(50055)
                .addService(researchNode)
                .intercept(new AgentIdInterceptor())
                .build().start();

        Server writerServer = ServerBuilder.forPort(50056)
                .addService(writerNode)
                .intercept(new AgentIdInterceptor())
                .build().start();

        try {
            GraphRunner runner = new GraphRunner(supervisorNode, researchNode, writerNode);
            AgentState state = new AgentState();
            state.setTask(researchQuestion);

            AgentState result = runner.run(state);

            print("Research results", result.getResearchResults());
            print("Written files", result.getWrittenFiles());

            assertFalse(result.getResearchResults().isEmpty(), "Research results should not be empty");
            assertFalse(result.getWrittenFiles().isEmpty(), "Written files should not be empty");
            assertEquals("research_report.txt", result.getWrittenFiles().get(0));
        } finally {
            supervisorServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
            researchServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
            writerServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
        }
    }
}
