    private WebSearchTool searchTool;

    public WebSearchMCPServerImpl() {
        this.searchTool = new WebSearchTool();
    }

    public WebSearchMCPServerImpl(String apiBaseUrl, String htmlBaseUrl) {
        this.searchTool = new WebSearchTool(apiBaseUrl, htmlBaseUrl);
    }

private String web_search(String query) throws Exception {
    return searchTool.webSearch(query);
}
