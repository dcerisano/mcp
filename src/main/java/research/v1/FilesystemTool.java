package research.v1;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Collectors;

/**
 * Standalone business logic for filesystem operations.
 * No gRPC dependencies — usable from any transport adapter.
 */
public class FilesystemTool {

    private final Path baseDir;

    public FilesystemTool(Path baseDir) {
        this.baseDir = baseDir;
    }

    public String writeFile(String name, String content) throws Exception {
        Path file = baseDir.resolve(name).normalize();
        if (!file.startsWith(baseDir.normalize())) {
            throw new SecurityException("Path traversal denied: " + name);
        }
        Files.writeString(file, content);
        return "Wrote " + content.length() + " chars to " + name;
    }

    public String readFile(String name) throws Exception {
        Path file = baseDir.resolve(name).normalize();
        if (!file.startsWith(baseDir.normalize())) {
            throw new SecurityException("Path traversal denied: " + name);
        }
        if (!Files.exists(file)) return "File not found: " + name;
        return Files.readString(file);
    }

    public String listFiles() throws Exception {
        try (var stream = Files.list(baseDir)) {
            return stream
                    .map(p -> p.getFileName().toString())
                    .sorted()
                    .collect(Collectors.joining("\n"));
        }
    }
}
