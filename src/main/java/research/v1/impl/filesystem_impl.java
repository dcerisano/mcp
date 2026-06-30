private final FilesystemTool fileTool;

public FilesystemMCPServerImpl(Path baseDir) {
    this.fileTool = new FilesystemTool(baseDir);
}

private String write_file(String name, String content) throws Exception {
    return fileTool.writeFile(name, content);
}

private String read_file(String name) throws Exception {
    return fileTool.readFile(name);
}

private String list_files() throws Exception {
    return fileTool.listFiles();
}
