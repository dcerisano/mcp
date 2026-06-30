package research.v1;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Set;

/**
 * Standalone business logic for web search.
 * No gRPC dependencies — usable from any transport adapter.
 */
public class WebSearchTool {

    public static final Set<String> NOISE_WORDS = Set.of(
        "summary", "report", "article", "paper", "write", "research",
        "find", "search", "details", "info", "information",
        "a", "an", "the", "for", "on", "of", "and", "about",
        "to", "in", "with", "writeup", "document"
    );

    private String apiBaseUrl;
    private String htmlBaseUrl;
    private final HttpClient http = HttpClient.newHttpClient();

    public WebSearchTool() {
        this("https://api.duckduckgo.com/", "https://html.duckduckgo.com/html/");
    }

    public WebSearchTool(String apiBaseUrl, String htmlBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.htmlBaseUrl = htmlBaseUrl;
    }

    public String webSearch(String query) throws Exception {
        String cleanQuery = query;
        if (cleanQuery != null) {
            String[] words = cleanQuery.split("\\s+");
            java.util.List<String> filtered = new java.util.ArrayList<>();
            for (String w : words) {
                String lower = w.toLowerCase().replaceAll("[^a-zA-Z0-9]", "");
                if (!lower.isEmpty() && !NOISE_WORDS.contains(lower)) {
                    filtered.add(w);
                }
            }
            if (!filtered.isEmpty()) {
                cleanQuery = String.join(" ", filtered);
            }
        }
        String encoded = URLEncoder.encode(cleanQuery, StandardCharsets.UTF_8);
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(apiBaseUrl + "?q=" + encoded + "&format=json&no_html=1&skip_disambig=1"))
                .header("User-Agent", "MCP-Test-Agent/1.0")
                .GET()
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        JsonObject json = JsonParser.parseString(resp.body()).getAsJsonObject();

        StringBuilder raw = new StringBuilder();
        if (json.has("AbstractText")) {
            String abstractText = json.get("AbstractText").getAsString();
            if (!abstractText.isEmpty()) raw.append(abstractText).append("\n\n");
        }
        if (json.has("RelatedTopics") && json.get("RelatedTopics").isJsonArray()) {
            JsonArray topics = json.getAsJsonArray("RelatedTopics");
            int count = 0;
            for (var el : topics) {
                if (count >= 5 || !el.isJsonObject()) continue;
                JsonObject t = el.getAsJsonObject();
                if (t.has("Text") && !t.get("Text").getAsString().isEmpty()) {
                    raw.append("- ").append(t.get("Text").getAsString()).append("\n");
                    count++;
                }
            }
        }

        if (raw.length() == 0) {
            HttpRequest htmlReq = HttpRequest.newBuilder()
                    .uri(URI.create(htmlBaseUrl + "?q=" + encoded))
                    .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
                    .GET()
                    .build();
            HttpResponse<String> htmlResp = http.send(htmlReq, HttpResponse.BodyHandlers.ofString());
            String html = htmlResp.body();

            java.util.regex.Pattern p = java.util.regex.Pattern.compile(
                "<a class=\"result__snippet\"[^>]*>(.*?)</a>", java.util.regex.Pattern.DOTALL);
            java.util.regex.Matcher m = p.matcher(html);
            int fallbackCount = 0;
            while (m.find() && fallbackCount < 5) {
                String snippetText = m.group(1).trim()
                        .replaceAll("<[^>]*>", "")
                        .replaceAll("&amp;", "&")
                        .replaceAll("&quot;", "\"")
                        .replaceAll("&#x27;", "'")
                        .replaceAll("&lt;", "<")
                        .replaceAll("&gt;", ">")
                        .replaceAll("&nbsp;", " ")
                        .replaceAll("\\s+", " ")
                        .trim();
                if (!snippetText.isEmpty()) {
                    raw.append("- ").append(snippetText).append("\n");
                    fallbackCount++;
                }
            }
        }

        return raw.length() > 0 ? raw.toString().trim() : "No results found for: " + cleanQuery;
    }
}
