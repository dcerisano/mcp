package research.v1;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.file.Path;

public class FilesystemHttpMain {
    public static final int PORT = 50062;

    public static void main(String[] args) throws Exception {
        Path outputDir = Path.of(System.getProperty("user.dir"), "output");
        outputDir.toFile().mkdirs();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
        server.createContext("/mcp", new FilesystemMCPHttpHandler(outputDir));
        server.setExecutor(null);
        server.start();
        System.out.println("filesystem MCP HTTP server listening on port " + PORT + " (output: " + outputDir + ")");
        Thread.currentThread().join();
    }
}
