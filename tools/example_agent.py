"""
Example LangGraph research agent.
Defines the tools that will be exported as MCP proto definitions.
"""

from typing import Optional
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing import Annotated
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Tool definitions — these drive proto generation
# ---------------------------------------------------------------------------

@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information on a topic."""
    return f"Results for: {query}"


@tool
def read_file(path: str) -> str:
    """Read the contents of a file at the given path."""
    return open(path).read()


@tool
def write_file(path: str, content: str, overwrite: bool = False) -> bool:
    """Write content to a file. Returns True on success."""
    with open(path, "w" if overwrite else "x") as f:
        f.write(content)
    return True


@tool
def run_python(code: str, timeout_seconds: int = 30) -> str:
    """Execute a Python code snippet and return its stdout output."""
    import subprocess
    result = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=timeout_seconds)
    return result.stdout or result.stderr


@tool
def http_get(url: str, headers: Optional[dict] = None) -> str:
    """Make an HTTP GET request and return the response body."""
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# Export — the generator reads this
# ---------------------------------------------------------------------------

TOOLS = [web_search, read_file, write_file, run_python, http_get]
AGENT_NAME = "research-agent"
PACKAGE = "research.v1"
