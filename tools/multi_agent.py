"""
Multi-agent research system defined in LangGraph.

Agents:
  Supervisor     — routes tasks to specialized agents based on state
  ResearchAgent  — calls web_search via MCP server (gRPC, port 50051)
  WriterAgent    — calls write_file via MCP server (gRPC, port 50052)

LLM sampling (Ollama) is called directly by the agents.
MCP servers handle search and filesystem I/O.
"""

import json
import sys
import os
import urllib.request
from concurrent import futures
from pathlib import Path
from typing import Annotated, Literal
from typing_extensions import TypedDict

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

# ---------------------------------------------------------------------------
# Python gRPC stubs — loaded lazily so the proto generator can import this
# file before stubs are generated
# ---------------------------------------------------------------------------

def _load_grpc():
    sys.path.insert(0, str(Path(__file__).parent.parent / "gen" / "python"))
    import grpc
    from google.protobuf.struct_pb2 import Struct
    from research.v1 import research_agent_pb2 as pb
    from research.v1 import research_agent_pb2_grpc as pb_grpc
    return grpc, Struct, pb, pb_grpc

LLAMA_URL  = "http://localhost:11435/v1/chat/completions"
OLLAMA_URL = "http://localhost:11435/v1/chat/completions"
MODEL      = "qwen2.5:14b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def call_llama(system: str, user: str, max_tokens: int = 4096) -> str:
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }).encode()
    req = urllib.request.Request(
        LLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


CALLBACK_PORT = 50054

_grpc = None
_Struct = None
_pb = None
_pb_grpc = None
_web_search_stub = None
_filesystem_stub = None
_callback_server = None


def _ensure_grpc():
    global _grpc, _Struct, _pb, _pb_grpc, _web_search_stub, _filesystem_stub, _callback_server
    if _web_search_stub is not None:
        return

    _grpc, _Struct, _pb, _pb_grpc = _load_grpc()

    # Start the Python MCPClientService callback server so MCP servers can sample back
    class MCPClientServicer(_pb_grpc.MCPClientServiceServicer):
        def CreateMessage(self, request, context):
            system = request.system_prompt
            user = request.messages[0].content.text.text if request.messages else ""
            max_tokens = request.max_tokens or 256
            response_text = call_llama(system, user, max_tokens)
            return _pb.CreateMessageResponse(
                role=_pb.PromptMessageRole.Value("PROMPT_MESSAGE_ROLE_ASSISTANT"),
                content=_pb.Content(text=_pb.TextContent(text=response_text)),
                model=MODEL,
                stop_reason=_pb.StopReason.Value("STOP_REASON_END_TURN"),
            )

    _callback_server = _grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    _pb_grpc.add_MCPClientServiceServicer_to_server(MCPClientServicer(), _callback_server)
    _callback_server.add_insecure_port(f"[::]:{CALLBACK_PORT}")
    _callback_server.start()
    print(f"Python MCPClientService callback server started on port {CALLBACK_PORT}")

    # Connect to MCP server processes — pass callback address so they can sample back
    _web_search_stub = _pb_grpc.MCPServerServiceStub(_grpc.insecure_channel("localhost:50051"))
    _filesystem_stub = _pb_grpc.MCPServerServiceStub(_grpc.insecure_channel("localhost:50052"))

    callback_addr = f"localhost:{CALLBACK_PORT}"
    for stub, agent_name in [(_web_search_stub, "research_agent"), (_filesystem_stub, "writer_agent")]:
        stub.Initialize(
            _pb.InitializeRequest(
                protocol_version="2025-11-25",
                client_info=_pb.ClientInfo(
                    name=agent_name,
                    version="1.0",
                    callback_address=callback_addr,
                ),
                capabilities=_pb.ClientCapabilities(sampling=_pb.SamplingCapability()),
            ),
            metadata=(("agent-id", agent_name),),
        )


def make_struct(**kwargs):
    _ensure_grpc()
    s = _Struct()
    for k, v in kwargs.items():
        s.fields[k].string_value = v
    return s


def call_tool(stub, tool_name: str, agent_name: str = "multi-agent", **kwargs) -> str:
    _ensure_grpc()
    resp = stub.CallTool(
        _pb.CallToolRequest(name=tool_name, arguments=make_struct(**kwargs)),
        metadata=(("agent-id", agent_name),),
    )
    return resp.content[0].text.text


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class MultiAgentState(TypedDict):
    messages:         Annotated[list[BaseMessage], add_messages]
    task:             str
    research_results: str
    written_files:    list[str]
    next:             str
    chat_history:     list[str]


# ---------------------------------------------------------------------------
# Agent nodes
# ---------------------------------------------------------------------------

def _sample(system: str, user: str, max_tokens: int = 4096, agent_name: str = "supervisor") -> str:
    """Call the agent's own MCPClientService for LLM sampling — no direct Ollama calls."""
    _ensure_grpc()
    stub = _pb_grpc.MCPClientServiceStub(_grpc.insecure_channel(f"localhost:{CALLBACK_PORT}"))
    resp = stub.CreateMessage(
        _pb.CreateMessageRequest(
            system_prompt=system,
            messages=[_pb.SamplingMessage(
                role=_pb.PromptMessageRole.Value("PROMPT_MESSAGE_ROLE_USER"),
                content=_pb.Content(text=_pb.TextContent(text=user)),
            )],
            max_tokens=max_tokens,
        ),
        metadata=(("agent-id", agent_name),),
    )
    return resp.content.text.text


def supervisor_node(state: MultiAgentState) -> dict:
    """Uses LLM (via own MCPClientService) to reason about state, then routes deterministically."""
    research_done = bool(state.get("research_results"))
    files_written = bool(state.get("written_files"))

    decision = "research" if not research_done else ("writer" if not files_written else "FINISH")

    if decision != "FINISH":
        reasoning = _sample(
            system="Reply with ONE word: research, writer, or FINISH.",
            user=(
                f"Task: {state['task']}\n"
                f"Research done: {'yes' if research_done else 'no'}\n"
                f"Files written: {state['written_files'] if files_written else 'none'}"
            ),
            max_tokens=16,
            agent_name="supervisor",
        ).strip()
    else:
        reasoning = f"All done. Files written: {state['written_files']}"

    state["chat_history"].append(reasoning)

    return {
        "next": decision,
        "messages": [AIMessage(content=f"Reasoning: {reasoning}\nDecision: {decision}", name="supervisor")],
    }


def research_agent_node(state: MultiAgentState) -> dict:
    """Uses LLM to choose a search query, then calls web_search MCP server.
    The MCP server samples back to get analysis — agent receives the analyzed result."""
    _ensure_grpc()

    # Agent uses own MCPClientService to pick a search query
    query = _sample(
        system="Reply with a simple search query or topic keyword to look up (e.g. 'Python programming language'). No punctuation or explanation.",
        user=state["task"],
        max_tokens=4096,
        agent_name="research_agent",
    ).strip().strip('"')
    
    query = " ".join(w for w in query.split() if w.isalnum() or len(w) > 1)

    # MCP server fetches results AND samples back to client for analysis
    result = call_tool(_web_search_stub, "web_search", agent_name="research_agent", query=query)

    thought = "Research Agent: Searched for '" + query + "' and retrieved results."
    state["chat_history"].append(thought)

    return {
        "research_results": result,
        "messages": [AIMessage(
            content=f"Searched '{query}' via MCP server (server sampled client for analysis).\nResult: {result}",
            name="research_agent",
        )],
    }


def writer_agent_node(state: MultiAgentState) -> dict:
    """Uses LLM to draft content, then calls write_file MCP server.
    The MCP server samples back for formatting before writing."""
    _ensure_grpc()

    # Agent uses own MCPClientService to draft the content
    draft = _sample(
        system="You are a technical writer. Write a 3-5 sentence summary of the research. Be factual, no introductions.",
        user=f"Task: {state['task']}\nResearch: {state['research_results']}",
        max_tokens=2048,
        agent_name="writer_agent",
    )

    # MCP server samples back to client for formatting, then writes
    filename = "research_report.txt"
    result = call_tool(_filesystem_stub, "write_file", agent_name="writer_agent", name=filename, content=draft)

    thought = "Writer Agent: Wrote report to '" + filename + "'."
    state["chat_history"].append(thought)

    return {
        "written_files": [filename],
        "messages": [AIMessage(
            content=f"MCP filesystem server formatted and wrote the report.\n{result}",
            name="writer_agent",
        )],
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def route(state: MultiAgentState) -> Literal["research_agent", "writer_agent", "__end__"]:
    n = state["next"]
    if n == "FINISH": return "__end__"
    return f"{n}_agent"


builder = StateGraph(MultiAgentState)
builder.add_node("supervisor",     supervisor_node)
builder.add_node("research_agent", research_agent_node)
builder.add_node("writer_agent",   writer_agent_node)

builder.set_entry_point("supervisor")
builder.add_conditional_edges("supervisor", route)
builder.add_edge("research_agent", "supervisor")
builder.add_edge("writer_agent",   "supervisor")

app = builder.compile()


# ---------------------------------------------------------------------------
# Export — for langgraph_to_proto.py
# ---------------------------------------------------------------------------

@tool
def web_search_and_analyze(query: str) -> str:
    """Search the web via MCP server and synthesize key facts using LLM sampling."""
    _ensure_grpc()
    raw = call_tool(_web_search_stub, "web_search", agent_name="web_search_and_analyze", query=query)
    return call_llama("List 3-5 key facts, one sentence each.", raw, 1024)


@tool
def format_and_write(filename: str, content: str) -> str:
    """Format content as a structured report using LLM sampling, then write via MCP filesystem server."""
    _ensure_grpc()
    formatted = call_llama(
        "Format as 2-3 bullet points, concise.", content, 1024)
    return call_tool(_filesystem_stub, "write_file", agent_name="format_and_write", name=filename, content=formatted)


TOOLS      = [web_search_and_analyze, format_and_write]
AGENT_NAME = "multi-research-agent"
PACKAGE    = "research.v1"

# Shared LLM config — picked up by OllamaClient generator
OLLAMA_MODEL = MODEL
OLLAMA_URL   = LLAMA_URL  # already defined above

# Top-level MCP server registry — used to generate ServerMain + MCPServerImpl classes
MCP_SERVERS = [
    {
        "name":         "web-search",
        "port":         50051,
        "output_dir":   False,
        "instructions": "Use the web_search tool to look up current information.",
        "noise_words": [
            "summary", "report", "article", "paper", "write", "research", "find", 
            "search", "details", "info", "information", "a", "an", "the", "for", 
            "on", "of", "and", "about", "to", "in", "with", "writeup", "document"
        ],
        "imports": [
            "com.google.gson.JsonArray",
            "com.google.gson.JsonObject",
            "com.google.gson.JsonParser",
            "java.net.URI",
            "java.net.URLEncoder",
            "java.net.http.HttpClient",
            "java.net.http.HttpRequest",
            "java.net.http.HttpResponse",
            "java.nio.charset.StandardCharsets",
        ],
        "tools": [
            {
                "name":        "web_search",
                "description": "Search the web for current information. Returns a summary and related topics.",
                "params":      ["query"],
                "sampling": {
                    "system":     "You are a research analyst. List 3-5 key facts from these search results, one short sentence each. Be concise.",
                    "input_param": "query",
                    "max_tokens":  1024,
                },
            },
        ],
        "snippet": "src/main/java/research/v1/impl/web_search_impl.java",
    },
    {
        "name":         "filesystem",
        "port":         50052,
        "output_dir":   True,
        "instructions": "Use write_file, read_file, and list_files to manage stored research.",
        "imports": [
            "java.io.IOException",
            "java.nio.file.Files",
            "java.nio.file.Path",
            "java.util.stream.Collectors",
        ],
        "tools": [
            {
                "name":        "write_file",
                "description": "Write text content to a named file in the research store.",
                "params":      ["name", "content"],
                "sampling": {
                    "system":     "Format the following as 2-3 bullet points. Be concise.",
                    "input_param": "content",
                    "max_tokens":  1024,
                },
            },
            {
                "name":        "read_file",
                "description": "Read the content of a previously stored file by name.",
                "params":      ["name"],
                "sampling":    None,
            },
            {
                "name":        "list_files",
                "description": "List all files currently in the research store.",
                "params":      [],
                "sampling":    None,
            },
        ],
        "snippet": "src/main/java/research/v1/impl/filesystem_impl.java",
    },
]

# ---------------------------------------------------------------------------
# Graph metadata — consumed by langgraph_to_proto.py to generate skeletons
# ---------------------------------------------------------------------------

AGENT_NODES = [
    {
        "name":        "supervisor",
        "fn":          supervisor_node,
        "description": "Routes tasks to specialized agents based on state. Uses LLM sampling to reason about next step.",
        "tools":       [],
        "mcp_servers": [],
        "port":        50053,
    },
    {
        "name":        "research_agent",
        "fn":          research_agent_node,
        "description": "Chooses a search query via LLM sampling, then calls the web-search MCP server.",
        "tools":       ["web_search_and_analyze"],
        "mcp_servers": [{"name": "web-search", "port": 50051, "tool": "web_search"}],
        "port":        50055,
    },
    {
        "name":        "writer_agent",
        "fn":          writer_agent_node,
        "description": "Drafts content via LLM sampling, then calls the filesystem MCP server to write it.",
        "tools":       ["format_and_write"],
        "mcp_servers": [{"name": "filesystem", "port": 50052, "tool": "write_file"}],
        "port":        50056,
    },
]

GRAPH_EDGES = [
    {"from": "supervisor",      "to": "research_agent", "condition": "next == 'research'"},
    {"from": "supervisor",      "to": "writer_agent",   "condition": "next == 'writer'"},
    {"from": "supervisor",      "to": "__end__",         "condition": "next == 'FINISH'"},
    {"from": "research_agent",  "to": "supervisor",     "condition": None},
    {"from": "writer_agent",    "to": "supervisor",     "condition": None},
]

STATE_FIELDS = [
    {"name": "task",             "type": "string",          "description": "The research task to complete"},
    {"name": "research_results", "type": "string",          "description": "Results from the research agent"},
    {"name": "written_files",    "type": "repeated string", "description": "Files written by the writer agent"},
    {"name": "next",             "type": "string",          "description": "Next node to route to"},
    {"name": "chat_history",     "type": "repeated string", "description": "Conversation history"},
]


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    task = "Research the Python programming language and write a summary report"
    print(f"Task: {task}\n{'='*60}")

    result = app.invoke({
        "task":             task,
        "messages":         [HumanMessage(content=task)],
        "research_results": "",
        "written_files":    [],
        "next":             "",
        "chat_history":     [],
    })

    print("\n--- Agent trace ---")
    for msg in result["messages"]:
        name = getattr(msg, "name", type(msg).__name__)
        print(f"\n[{name}]\n{msg.content}")

    print(f"\n{'='*60}")
    print(f"Files written: {result['written_files']}")
