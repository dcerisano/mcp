package research.v1;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;

public class WebSearchHttpMain {
    public static final int PORT = 50061;

    public static void main(String[] args) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", PORT), 0);
        server.createContext("/mcp", new WebSearchMCPHttpHandler());
        server.setExecutor(null);
        server.start();
        System.out.println("web-search MCP HTTP server listening on port " + PORT);
        Thread.currentThread().join();
    }
}
