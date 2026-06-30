#!/usr/bin/env python3
"""
langgraph_to_proto.py

Generates MCP .proto definitions from a LangGraph agent's tool definitions.

Usage:
    python tools/langgraph_to_proto.py                          # uses example_agent.py
    python tools/langgraph_to_proto.py tools/my_agent.py        # uses your agent file
    python tools/langgraph_to_proto.py tools/my_agent.py out.proto
"""

import ast
import importlib.util
import sys
import os
import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# JSON Schema → Proto type
# ---------------------------------------------------------------------------

def json_schema_to_proto(schema: dict) -> tuple[str, bool]:
    """Returns (proto_type, is_repeated)."""
    # anyOf / oneOf — used by Pydantic for Optional[T] → pick the non-null branch
    for key in ("anyOf", "oneOf"):
        if key in schema:
            non_null = [s for s in schema[key] if s.get("type") != "null"]
            if non_null:
                return json_schema_to_proto(non_null[0])
            return "string", False  # Optional with no type info

    t = schema.get("type", "string")
    if t == "array":
        items = schema.get("items", {})
        item_type, _ = json_schema_to_proto(items)
        return item_type, True
    return {
        "string":  "string",
        "integer": "int32",
        "number":  "double",
        "boolean": "bool",
        "object":  "google.protobuf.Struct",
        "null":    "google.protobuf.Value",
    }.get(t, "string"), False


# ---------------------------------------------------------------------------
# Tool → input message
# ---------------------------------------------------------------------------

def to_camel(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def tool_input_message(tool) -> str:
    lines = []
    desc_line = tool.description.split("\n")[0].strip() if tool.description else tool.name
    lines.append(f"// {desc_line}")
    lines.append(f"message {to_camel(tool.name)}Input {{")

    for i, (arg, schema) in enumerate(tool.args.items(), start=1):
        proto_type, repeated = json_schema_to_proto(schema)
        prefix = "repeated " if repeated else ""

        parts = []
        if schema.get("description"):
            parts.append(schema["description"])
        if "default" in schema:
            parts.append(f"default={schema['default']}")
        if parts:
            lines.append(f"  // {'; '.join(parts)}")

        lines.append(f"  {prefix}{proto_type} {arg} = {i};")

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proto template
# ---------------------------------------------------------------------------

HEADER = '''\
// AUTO-GENERATED — DO NOT EDIT.  Modify tools/langgraph_to_proto.py instead.
// Re-run ./build.sh to regenerate.
syntax = "proto3";

package {package};

option java_outer_classname = "Mcp";

import "google/protobuf/struct.proto";

// Agent: {agent_name}
// Tools: {tool_list}
'''

CONTENT_TYPES = '''\
// ---------------------------------------------------------------------------
// Content types
// ---------------------------------------------------------------------------

message TextContent {
  string text = 1;
}

message ImageContent {
  string data = 1;
  string mime_type = 2;
}

message ResourceContent {
  string uri = 1;
  string mime_type = 2;
  oneof body {
    string text = 3;
    bytes blob = 4;
  }
}

message Content {
  oneof kind {
    TextContent text = 1;
    ImageContent image = 2;
    ResourceContent resource = 3;
  }
}
'''

CAPABILITY_TYPES = '''\
// ---------------------------------------------------------------------------
// Capability types (object-based, per spec 2025-11-25)
// ---------------------------------------------------------------------------

message ResourcesCapability { bool subscribe = 1; bool list_changed = 2; }
message ToolsCapability { bool list_changed = 1; }
message PromptsCapability { bool list_changed = 1; }
message LoggingCapability {}
message CompletionsCapability {}

message RootsCapability { bool list_changed = 1; }
message SamplingCapability { bool context = 1; bool tools = 2; }
'''

NOTIFICATION_MESSAGES = '''\\
// ---------------------------------------------------------------------------
// Notification infrastructure
// ---------------------------------------------------------------------------

message CancelledNotification {
  oneof request_id {
    string string_id = 1;
    int64  int_id    = 2;
  }
  string reason = 3;
}

message RootsListChangedNotification {}
message ResourceListChangedNotification {}
message ToolListChangedNotification {}
message PromptListChangedNotification {}

message NotifyRequest {
  oneof notification {
    CancelledNotification cancelled             = 1;
    InitializedNotification initialized          = 2;
    RootsListChangedNotification roots_list_changed    = 3;
    ResourceListChangedNotification resource_list_changed  = 4;
    ToolListChangedNotification tool_list_changed      = 5;
    PromptListChangedNotification prompt_list_changed    = 6;
  }
}

message NotifyResponse {}

message InitializedNotification {}
'''

TOOL_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Tool RPCs
// ---------------------------------------------------------------------------

message Tool {
  string name = 1;
  string description = 2;
  google.protobuf.Struct input_schema = 3;
}

message ListToolsRequest  { string cursor = 1; }
message ListToolsResponse { repeated Tool tools = 1; string next_cursor = 2; }

message CallToolRequest {
  string name = 1;
  google.protobuf.Struct arguments = 2;
}

message CallToolResponse {
  repeated Content content = 1;
  bool is_error = 2;
}
'''

INIT_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

message ClientInfo {
  string name = 1;
  string version = 2;
  string callback_address = 3;  // host:port of the client's MCPClientService
}
message ServerInfo { string name = 1; string version = 2; }

message ClientCapabilities {
  RootsCapability roots = 1;
  SamplingCapability sampling = 2;
}
message ServerCapabilities {
  ResourcesCapability resources = 1;
  ToolsCapability tools = 2;
  PromptsCapability prompts = 3;
  LoggingCapability logging = 4;
  CompletionsCapability completions = 5;
}

message InitializeRequest {
  string protocol_version = 1;
  ClientInfo client_info = 2;
  ClientCapabilities capabilities = 3;
}

message InitializeResponse {
  string protocol_version = 1;
  ServerInfo server_info = 2;
  ServerCapabilities capabilities = 3;
  string instructions = 4;
}

message PingRequest  {}
message PingResponse {}
'''

RESOURCE_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Resources
// ---------------------------------------------------------------------------

message Resource {
  string uri = 1;
  string name = 2;
  string description = 3;
  string mime_type = 4;
}

message ResourceTemplate {
  string uri_template = 1;
  string name = 2;
  string description = 3;
  string mime_type = 4;
}

message ListResourcesRequest  { string cursor = 1; }
message ListResourcesResponse { repeated Resource resources = 1; string next_cursor = 2; }

message ListResourceTemplatesRequest  { string cursor = 1; }
message ListResourceTemplatesResponse { repeated ResourceTemplate resource_templates = 1; string next_cursor = 2; }

message ReadResourceRequest   { string uri = 1; }
message ReadResourceResponse  { repeated ResourceContent contents = 1; }

message SubscribeResourceRequest   { string uri = 1; }
message SubscribeResourceResponse  {}
message UnsubscribeResourceRequest  { string uri = 1; }
message UnsubscribeResourceResponse {}

message WatchResourcesRequest  { string uri = 1; }
message WatchResourcesResponse { string uri = 1; }
'''

PROMPT_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

message PromptArgument {
  string name = 1;
  string description = 2;
  bool required = 3;
}

message Prompt {
  string name = 1;
  string description = 2;
  repeated PromptArgument arguments = 3;
}

message PromptMessage {
  PromptMessageRole role = 1;
  Content content = 2;
}

message ListPromptsRequest  { string cursor = 1; }
message ListPromptsResponse { repeated Prompt prompts = 1; string next_cursor = 2; }

message GetPromptRequest  { string name = 1; map<string, string> arguments = 2; }
message GetPromptResponse { string description = 1; repeated PromptMessage messages = 2; }

message CompleteRequest {
  string prompt_name = 1;
  string argument_name = 2;
  string current_value = 3;
}

message CompleteResponse {
  repeated string completions = 1;
  bool has_more = 2;
}
'''

LOGGING_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Server Logging
// ---------------------------------------------------------------------------

enum LogLevel {
  LOG_LEVEL_UNSPECIFIED = 0;
  LOG_LEVEL_DEBUG       = 1;
  LOG_LEVEL_INFO        = 2;
  LOG_LEVEL_WARNING     = 3;
  LOG_LEVEL_ERROR       = 4;
}

message LogEntry {
  LogLevel level = 1;
  string logger = 2;
  string message = 3;
}

message LoggingRequest {
  LogLevel min_level = 1;
}
'''

ROOTS_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Workspace Roots
// ---------------------------------------------------------------------------

message Root {
  string uri = 1;
  string name = 2;
}

message ListRootsRequest {}
message ListRootsResponse {
  repeated Root roots = 1;
}
'''

SAMPLING_MESSAGES = '''\
// ---------------------------------------------------------------------------
// Sampling (client-side LLM inference)
// ---------------------------------------------------------------------------

enum PromptMessageRole {
  PROMPT_MESSAGE_ROLE_UNSPECIFIED = 0;
  PROMPT_MESSAGE_ROLE_USER        = 1;
  PROMPT_MESSAGE_ROLE_ASSISTANT   = 2;
}

enum StopReason {
  STOP_REASON_UNSPECIFIED   = 0;
  STOP_REASON_END_TURN      = 1;
  STOP_REASON_MAX_TOKENS    = 2;
  STOP_REASON_STOP_SEQUENCE = 3;
}

message ModelHint        { string name = 1; }
message ModelPreferences {
  repeated ModelHint hints    = 1;
  float cost_priority         = 2;
  float speed_priority        = 3;
  float intelligence_priority = 4;
}

message SamplingMessage {
  PromptMessageRole role = 1;
  Content content        = 2;
}

message CreateMessageRequest {
  repeated SamplingMessage messages  = 1;
  ModelPreferences model_preferences = 2;
  string system_prompt               = 3;
  int32  max_tokens                  = 4;
  repeated string stop_sequences     = 5;
  float  temperature                 = 6;
  map<string, string> metadata       = 7;
}

message CreateMessageResponse {
  PromptMessageRole role = 1;
  Content content        = 2;
  string model           = 3;
  StopReason stop_reason = 4;
}
'''

SERVER_SERVICE = '''\
// ---------------------------------------------------------------------------
// MCPServerService — exposes the tools defined in this agent
// ---------------------------------------------------------------------------

service MCPServerService {
  rpc Initialize(InitializeRequest)           returns (InitializeResponse);
  rpc Ping(PingRequest)                       returns (PingResponse);
  rpc Notify(NotifyRequest)                   returns (NotifyResponse);
  rpc ListResources(ListResourcesRequest)     returns (ListResourcesResponse);
  rpc ListResourceTemplates(ListResourceTemplatesRequest) returns (ListResourceTemplatesResponse);
  rpc ReadResource(ReadResourceRequest)       returns (ReadResourceResponse);
  rpc SubscribeResource(SubscribeResourceRequest)     returns (SubscribeResourceResponse);
  rpc UnsubscribeResource(UnsubscribeResourceRequest) returns (UnsubscribeResourceResponse);
  rpc WatchResources(WatchResourcesRequest)   returns (stream WatchResourcesResponse);
  rpc ListTools(ListToolsRequest)             returns (ListToolsResponse);
  rpc CallTool(CallToolRequest)               returns (CallToolResponse);
  rpc ListPrompts(ListPromptsRequest)         returns (ListPromptsResponse);
  rpc GetPrompt(GetPromptRequest)             returns (GetPromptResponse);
  rpc StreamLogs(LoggingRequest)              returns (stream LogEntry);
  rpc Complete(CompleteRequest)               returns (CompleteResponse);
}
'''

CLIENT_SERVICE = '''\
// ---------------------------------------------------------------------------
// MCPClientService — implemented by the client; called by the server for LLM sampling
// ---------------------------------------------------------------------------

service MCPClientService {
  rpc CreateMessage(CreateMessageRequest) returns (CreateMessageResponse);
  rpc ListRoots(ListRootsRequest)         returns (ListRootsResponse);
}
'''


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_proto(tools: list, agent_name: str, package: str) -> str:
    tool_input_section = (
        "// ---------------------------------------------------------------------------\n"
        "// Tool input schemas (generated from LangGraph tool definitions)\n"
        "// ---------------------------------------------------------------------------\n\n"
        + "\n\n".join(tool_input_message(t) for t in tools)
    )

    return "\n".join([
        HEADER.format(
            package=package,
            agent_name=agent_name,
            tool_list=", ".join(t.name for t in tools),
        ),
        CONTENT_TYPES,
        tool_input_section,
        "",
        CAPABILITY_TYPES,
        "",
        RESOURCE_MESSAGES,
        TOOL_MESSAGES,
        PROMPT_MESSAGES,
        LOGGING_MESSAGES,
        ROOTS_MESSAGES,
        INIT_MESSAGES,
        NOTIFICATION_MESSAGES,
        "",
        SAMPLING_MESSAGES,
        SERVER_SERVICE,
        CLIENT_SERVICE,
    ])


# ---------------------------------------------------------------------------
# Java test generator
# ---------------------------------------------------------------------------

def to_java_sample(proto_type: str, repeated: bool, field_name: str) -> dict:
    """Returns {'set': builder_call, 'assert': assertion_statement}."""
    camel = to_camel(field_name)
    if repeated:
        return {
            'set':    f'.add{camel}("sample_{field_name}")',
            'assert': f'assertEquals(1, parsed.get{camel}Count());',
        }
    return {
        'string': {
            'set':    f'.set{camel}("test_{field_name}")',
            'assert': f'assertEquals("test_{field_name}", parsed.get{camel}());',
        },
        'int32': {
            'set':    f'.set{camel}(42)',
            'assert': f'assertEquals(42, parsed.get{camel}());',
        },
        'double': {
            'set':    f'.set{camel}(3.14)',
            'assert': f'assertEquals(3.14, parsed.get{camel}(), 0.001);',
        },
        'bool': {
            'set':    f'.set{camel}(true)',
            'assert': f'assertTrue(parsed.get{camel}());',
        },
        'google.protobuf.Struct': {
            'set':    (f'.set{camel}(com.google.protobuf.Struct.newBuilder()'
                       f'.putFields("key", com.google.protobuf.Value.newBuilder().setStringValue("val").build()).build())'),
            'assert': f'assertFalse(parsed.get{camel}().getFieldsMap().isEmpty());',
        },
    }.get(proto_type, {
        'set':    f'.set{camel}("test")',
        'assert': f'assertNotNull(parsed.get{camel}());',
    })


def struct_put(field_name: str, proto_type: str) -> str:
    if proto_type in ('int32', 'double'):
        val = 'com.google.protobuf.Value.newBuilder().setNumberValue(1).build()'
    elif proto_type == 'bool':
        val = 'com.google.protobuf.Value.newBuilder().setBoolValue(false).build()'
    else:
        val = f'com.google.protobuf.Value.newBuilder().setStringValue("test_{field_name}").build()'
    return f'.putFields("{field_name}", {val})'


def gen_tool_input_test(tool, test_num: int, total: int) -> str:
    msg  = to_camel(tool.name) + "Input"
    desc = (tool.description or tool.name).split("\n")[0].strip()
    samples = {f: to_java_sample(*(json_schema_to_proto(s)), f) for f, s in tool.args.items()}
    sets    = "\n                ".join(v['set'] for v in samples.values())
    asserts = "\n        ".join(v['assert'] for v in samples.values())
    return (
        f"\n    @Test\n"
        f"    public void {tool.name}_input_roundTrip() throws InvalidProtocolBufferException {{\n"
        f'        section("TEST {test_num} of {total}: {msg} — {desc} — round-trip serialize/parse");\n'
        f"        Mcp.{msg} msg = Mcp.{msg}.newBuilder()\n"
        f"                {sets}\n"
        f"                .build();\n"
        f"        print(\"Original\", msg);\n"
        f"        Mcp.{msg} parsed = Mcp.{msg}.parseFrom(msg.toByteArray());\n"
        f"        print(\"Parsed\", parsed);\n"
        f"        print(\"Serialized bytes\", msg.toByteArray().length + \" bytes\");\n"
        f"        {asserts}\n"
        f"    }}"
    )


def gen_call_tool_test(tool, test_num: int, total: int) -> str:
    puts = "\n                        ".join(
        struct_put(f, json_schema_to_proto(s)[0])
        for f, s in tool.args.items()
    )
    return (
        f"\n    @Test\n"
        f"    public void callToolRequest_{tool.name}() throws InvalidProtocolBufferException {{\n"
        f'        section("TEST {test_num} of {total}: CallToolRequest for \'{tool.name}\' — name and arguments serialize correctly");\n'
        f"        Mcp.CallToolRequest req = Mcp.CallToolRequest.newBuilder()\n"
        f'                .setName("{tool.name}")\n'
        f"                .setArguments(com.google.protobuf.Struct.newBuilder()\n"
        f"                        {puts}\n"
        f"                        .build())\n"
        f"                .build();\n"
        f"        print(\"CallToolRequest\", req);\n"
        f"        Mcp.CallToolRequest parsed = Mcp.CallToolRequest.parseFrom(req.toByteArray());\n"
        f'        assertEquals("{tool.name}", parsed.getName());\n'
        f"        print(\"Tool name\", parsed.getName());\n"
        f"        print(\"Argument count\", parsed.getArguments().getFieldsCount());\n"
        f"    }}"
    )


def generate_test_java(tools: list, agent_name: str, package: str) -> str:
    n_fixed = 5  # enum x2, content, initialize, createMessage
    total   = n_fixed + 2 * len(tools)
    t       = n_fixed  # running test counter for fixed tests

    fixed = f"""\

    // -----------------------------------------------------------------------
    // Fixed protocol tests
    // -----------------------------------------------------------------------

    @Test
    public void promptMessageRole_values() throws Exception {{
        section("TEST 1 of {total}: PromptMessageRole — all enum values and wire numbers");
        for (Mcp.PromptMessageRole r : Mcp.PromptMessageRole.values()) {{
            if (r == Mcp.PromptMessageRole.UNRECOGNIZED) continue;
            print("PromptMessageRole", r.name() + " = " + r.getNumber());
        }}
        assertEquals(0, Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_UNSPECIFIED.getNumber());
        assertEquals(1, Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER.getNumber());
        assertEquals(2, Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_ASSISTANT.getNumber());
    }}

    @Test
    public void stopReason_values() throws Exception {{
        section("TEST 2 of {total}: StopReason — all enum values and wire numbers");
        for (Mcp.StopReason r : Mcp.StopReason.values()) {{
            if (r == Mcp.StopReason.UNRECOGNIZED) continue;
            print("StopReason", r.name() + " = " + r.getNumber());
        }}
        assertEquals(1, Mcp.StopReason.STOP_REASON_END_TURN.getNumber());
        assertEquals(2, Mcp.StopReason.STOP_REASON_MAX_TOKENS.getNumber());
        assertEquals(3, Mcp.StopReason.STOP_REASON_STOP_SEQUENCE.getNumber());
    }}

    @Test
    public void content_textKind() throws Exception {{
        section("TEST 3 of {total}: Content oneof — TEXT variant carries the string");
        Mcp.Content c = Mcp.Content.newBuilder()
                .setText(Mcp.TextContent.newBuilder().setText("hello world"))
                .build();
        print("Content", c);
        assertEquals(Mcp.Content.KindCase.TEXT, c.getKindCase());
        assertEquals("hello world", c.getText().getText());
    }}

    @Test
    public void initializeRequest_roundTrip() throws InvalidProtocolBufferException {{
        section("TEST 4 of {total}: InitializeRequest — protocol version + capabilities survive serialize/parse");
        Mcp.InitializeRequest req = Mcp.InitializeRequest.newBuilder()
                .setProtocolVersion("2025-11-25")
                .setClientInfo(Mcp.ClientInfo.newBuilder().setName("test-client").setVersion("1.0"))
                .setCapabilities(Mcp.ClientCapabilities.newBuilder()
                        .setSampling(Mcp.SamplingCapability.newBuilder().build()))
                .build();
        print("Original", req);
        Mcp.InitializeRequest parsed = Mcp.InitializeRequest.parseFrom(req.toByteArray());
        print("Parsed", parsed);
        print("Serialized size", req.toByteArray().length + " bytes");
        assertEquals("2025-11-25", parsed.getProtocolVersion());
        assertEquals("test-client", parsed.getClientInfo().getName());
        assertTrue(parsed.getCapabilities().hasSampling());
    }}

    @Test
    public void createMessageRequest_roundTrip() throws InvalidProtocolBufferException {{
        section("TEST 5 of {total}: CreateMessageRequest — sampling request survives serialize/parse");
        Mcp.CreateMessageRequest req = Mcp.CreateMessageRequest.newBuilder()
                .addMessages(Mcp.SamplingMessage.newBuilder()
                        .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER)
                        .setContent(Mcp.Content.newBuilder()
                                .setText(Mcp.TextContent.newBuilder().setText("Hello"))))
                .setModelPreferences(Mcp.ModelPreferences.newBuilder()
                        .addHints(Mcp.ModelHint.newBuilder().setName("test-model")))
                .setMaxTokens(256)
                .build();
        print("Original", req);
        Mcp.CreateMessageRequest parsed = Mcp.CreateMessageRequest.parseFrom(req.toByteArray());
        print("Parsed", parsed);
        assertEquals(1, parsed.getMessagesCount());
        assertEquals("test-model", parsed.getModelPreferences().getHints(0).getName());
        assertEquals(256, parsed.getMaxTokens());
    }}"""

    tool_tests = []
    for i, tool in enumerate(tools):
        input_num = n_fixed + i + 1
        call_num  = n_fixed + len(tools) + i + 1
        tool_tests.append(gen_tool_input_test(tool, input_num, total))
        tool_tests.append(gen_call_tool_test(tool, call_num, total))

    # Interleave: all input tests then all call tests — group by tool instead
    input_tests = [gen_tool_input_test(t, n_fixed + i + 1, total) for i, t in enumerate(tools)]
    call_tests  = [gen_call_tool_test(t, n_fixed + len(tools) + i + 1, total) for i, t in enumerate(tools)]

    java_package = package.replace(".", "/")  # for comment only
    return "\n".join([
        f"package {package};",
        "",
        "import com.google.protobuf.InvalidProtocolBufferException;",
        "import org.junit.jupiter.api.Test;",
        "import static org.junit.jupiter.api.Assertions.*;",
        "",
        f"// Auto-generated by langgraph_to_proto.py — agent: {agent_name}",
        f"// Tools: {', '.join(t.name for t in tools)}",
        "public class McpProtoTest {",
        "",
        "    private static void section(String title) { System.out.println(\"\\n\" + title); }",
        "    private static void print(String l, Object v) { System.out.println(\"[\" + l + \"] \" + v); }",
        "",
        fixed,
        "",
        "    // -----------------------------------------------------------------------",
        "    // Generated per-tool: input message round-trip",
        "    // -----------------------------------------------------------------------",
        "\n".join(input_tests),
        "",
        "    // -----------------------------------------------------------------------",
        "    // Generated per-tool: CallToolRequest",
        "    // -----------------------------------------------------------------------",
        "\n".join(call_tests),
        "}",
    ])


# ---------------------------------------------------------------------------
# Agent node skeleton generator
# ---------------------------------------------------------------------------

def to_pascal(snake: str) -> str:
    return "".join(w.capitalize() for w in snake.split("_"))


def generate_agent_node_java(node: dict, package: str, tool_map: dict) -> str:
    class_name   = to_pascal(node["name"]) + "Node"
    server_name  = node["name"].replace("_", "-") + "-agent"
    description  = node.get("description", "")
    tools        = node.get("tools", [])
    mcp_servers  = node.get("mcp_servers", [])
    port         = node.get("port", 50060)

    # Build stub fields for each MCP server this node talks to
    stub_fields = []
    stub_inits  = []
    for srv in mcp_servers:
        field = srv["name"].replace("-", "_") + "_stub"
        stub_fields.append(
            f"    private MCPServerServiceGrpc.MCPServerServiceBlockingStub {field};"
        )
        stub_inits.append(textwrap.dedent(f"""\
            {field} = MCPServerServiceGrpc.newBlockingStub(
                        ManagedChannelBuilder.forAddress("localhost", {srv['port']}).usePlaintext().build());"""))

    # Build tool dispatch methods
    tool_methods = []
    for tool_name in tools:
        tool = tool_map.get(tool_name)
        if tool is None:
            continue
        method_name = tool_name
        params      = ", ".join(f"String {a}" for a in tool.args)
        put_fields  = "\n                        ".join(
            f'.putFields("{a}", com.google.protobuf.Value.newBuilder().setStringValue({a}).build())'
            for a in tool.args
        )
        srv_field = mcp_servers[0]["name"].replace("-", "_") + "_stub" if mcp_servers else "// no stub"
        tool_methods.append(textwrap.dedent(f"""\
    String {method_name}({params}) {{
        Mcp.CallToolResponse resp = {srv_field}.callTool(
                Mcp.CallToolRequest.newBuilder()
                        .setName("{tool_name}")
                        .setArguments(com.google.protobuf.Struct.newBuilder()
                                {put_fields}
                                .build())
                        .build());
        return resp.getContent(0).getText().getText();
    }}"""))

    stub_fields_str = "\n".join(stub_fields)
    stub_inits_str  = "\n            ".join(stub_inits)
    tool_methods_str = "\n\n".join(tool_methods)

    return textwrap.dedent(f"""\
package {package};

import io.grpc.ManagedChannelBuilder;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.stub.StreamObserver;
import java.util.concurrent.TimeUnit;

// Auto-generated by langgraph_to_proto.py
// Node: {node['name']} — {description}
public class {class_name} extends MCPClientServiceGrpc.MCPClientServiceImplBase {{

    public static final int PORT = {port};

{stub_fields_str}

    public {class_name}() {{
        {stub_inits_str}
    }}

    @Override
    public void createMessage(Mcp.CreateMessageRequest req, StreamObserver<Mcp.CreateMessageResponse> out) {{
        try {{
            String userText = req.getMessagesCount() > 0
                    ? req.getMessages(0).getContent().getText().getText() : "";
            String response = OllamaClient.call(req.getSystemPrompt(), userText,
                    req.getMaxTokens() > 0 ? req.getMaxTokens() : 4096);
            out.onNext(Mcp.CreateMessageResponse.newBuilder()
                    .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_ASSISTANT)
                    .setContent(Mcp.Content.newBuilder()
                            .setText(Mcp.TextContent.newBuilder().setText(response)))
                    .setStopReason(Mcp.StopReason.STOP_REASON_END_TURN)
                    .build());
            out.onCompleted();
        }} catch (Exception e) {{
            out.onError(io.grpc.Status.INTERNAL
                    .withDescription("llama-server call failed: " + e.getMessage())
                    .asRuntimeException());
        }}
    }}

    // TODO: implement agent logic for node '{node['name']}'
    // Description: {description}
    public AgentState run(AgentState state) {{
        throw new UnsupportedOperationException("Implement {node['name']} logic here");
    }}

{tool_methods_str}

    public static void main(String[] args) throws Exception {{
        Server server = ServerBuilder.forPort(PORT)
                .addService(new {class_name}())
                .intercept(new AgentIdInterceptor())
                .build().start();
        System.out.println("{class_name} listening on port " + PORT);
        server.awaitTermination();
    }}
}}
""")


# ---------------------------------------------------------------------------
# AgentState message generator
# ---------------------------------------------------------------------------

def generate_agent_state_java(state_fields: list, package: str) -> str:
    fields = []
    for f in state_fields:
        is_repeated = f["type"].startswith("repeated ")
        java_type   = "java.util.List<String>" if is_repeated else "String"
        default_val = "new java.util.ArrayList<>()" if is_repeated else '""'
        desc        = f.get("description", "")
        fields.append(f"    // {desc}\n    private {java_type} {f['name']} = {default_val};")

    getters_setters = []
    for f in state_fields:
        is_repeated = f["type"].startswith("repeated ")
        java_type   = "java.util.List<String>" if is_repeated else "String"
        pascal      = to_pascal(f["name"])
        getters_setters.append(
            f"    public {java_type} get{pascal}() {{ return {f['name']}; }}\n"
            f"    public void set{pascal}({java_type} v) {{ this.{f['name']} = v; }}"
        )

    fields_str = "\n\n".join(fields)
    gs_str     = "\n\n".join(getters_setters)

    return textwrap.dedent(f"""\
package {package};

import java.util.List;

// Auto-generated by langgraph_to_proto.py
public class AgentState {{

{fields_str}

{gs_str}
}}
""")


# ---------------------------------------------------------------------------
# Orchestration test generator
# ---------------------------------------------------------------------------

def generate_orchestration_test_java(
    agent_nodes: list, graph_edges: list, state_fields: list,
    tools: list, package: str, agent_name: str
) -> str:
    tool_map    = {t.name: t for t in tools}
    total_tests = len(agent_nodes)  # one test per agent node path

    # Build per-node test methods
    test_methods = []
    for i, node in enumerate(agent_nodes, start=1):
        class_name  = to_pascal(node["name"]) + "Node"
        server_name = node["name"]
        port        = node.get("port", 50060)
        tools_used  = node.get("tools", [])
        mcp_servers = node.get("mcp_servers", [])
        description = node.get("description", "")

        # Outgoing edges from this node
        out_edges = [e for e in graph_edges if e["from"] == server_name]
        routing_comment = "\n        // ".join(
            f"-> {e['to']}" + (f" when {e['condition']}" if e["condition"] else " (unconditional)")
            for e in out_edges
        ) or "terminal node"

        # Build tool call assertions for any tools this node uses
        tool_assertions = []
        for tool_name in tools_used:
            tool = tool_map.get(tool_name)
            if tool is None:
                continue
            sample_args = {a: f"\"test_{a}\"" for a in tool.args}
            args_str    = ", ".join(sample_args.values())
            tool_assertions.append(
                f'        // verify {tool_name}({", ".join(tool.args)})\n'
                f'        assertNotNull("Tool {tool_name} must return a result", '
                f'node.{tool_name}({args_str}));'
            )

        tool_assertions_str = "\n".join(tool_assertions) if tool_assertions else \
            f'        // {server_name} uses no direct tool calls — routes via sampling'

        # MCP server stub setup for this test
        stub_setup = []
        stub_teardown = []
        for srv in mcp_servers:
            field = srv["name"].replace("-", "_") + "Channel"
            stub_setup.append(
                f'        ManagedChannel {field} = ManagedChannelBuilder\n'
                f'                .forAddress("localhost", {srv["port"]}).usePlaintext().build();\n'
                f'        MCPServerServiceGrpc.MCPServerServiceBlockingStub '
                f'{srv["name"].replace("-","_")}Stub =\n'
                f'                MCPServerServiceGrpc.newBlockingStub({field});'
            )
            stub_teardown.append(f'        {field}.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);')

        stub_setup_str    = "\n".join(stub_setup)
        stub_teardown_str = "\n".join(stub_teardown)

        test_methods.append(textwrap.dedent(f"""\
    @Test
    public void {server_name}_node_runs() throws Exception {{
        section("TEST {i} of {total_tests}: {class_name} — {description}");
        // Routing from this node:
        // {routing_comment}

        {class_name} node = new {class_name}();
{stub_setup_str}

        // Verify the node's MCPClientService handles sampling
        Server nodeServer = ServerBuilder.forPort({port})
                .addService(node)
                .intercept(new AgentIdInterceptor())
                .build().start();
        ManagedChannel nodeChannel = ManagedChannelBuilder
                .forAddress("localhost", {port}).usePlaintext().build();
        MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingStub =
                MCPClientServiceGrpc.newBlockingStub(nodeChannel);

        Mcp.CreateMessageResponse resp = samplingStub.createMessage(
                Mcp.CreateMessageRequest.newBuilder()
                        .setSystemPrompt("You are a helpful assistant.")
                        .addMessages(Mcp.SamplingMessage.newBuilder()
                                .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER)
                                .setContent(Mcp.Content.newBuilder()
                                        .setText(Mcp.TextContent.newBuilder()
                                                .setText("Say hello in one word."))))
                        .setMaxTokens(16)
                        .build());
        assertFalse("Node {server_name} must return a non-empty response",
                resp.getContent().getText().getText().isEmpty());
        print("Response from {server_name}", resp.getContent().getText().getText());

{tool_assertions_str}

        nodeChannel.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
        nodeServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
{stub_teardown_str}
    }}"""))

    # Build graph topology comment
    topology_lines = []
    for edge in graph_edges:
        cond = f" [{edge['condition']}]" if edge["condition"] else ""
        topology_lines.append(f" *   {edge['from']} -> {edge['to']}{cond}")
    topology_str = "\n".join(topology_lines)

    tests_str = "\n\n".join(test_methods)

    return textwrap.dedent(f"""\
package {package};

import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import org.junit.jupiter.api.Test;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Auto-generated by langgraph_to_proto.py
 * Agent: {agent_name}
 *
 * Graph topology:
{topology_str}
 */
public class McpOrchestrationTest {{

    private static final int TOTAL = {total_tests};
    private static int testNumber = 0;

    private static void section(String title) {{
        testNumber++;
        System.out.println("\\n=== TEST " + testNumber + " of " + TOTAL + ": " + title + " ===");
    }}

    private static void print(String label, Object value) {{
        System.out.println("[" + label + "] " + value);
    }}

{tests_str}
}}
""")


# ---------------------------------------------------------------------------
# Python AST → Java translator
# ---------------------------------------------------------------------------

# Maps Python _sample() agent_name args to the Java node's samplingStub field name.
# Falls back to "samplingStub" if not found.
_AGENT_SAMPLE_STUB = "samplingStub"

class JavaTranslator(ast.NodeVisitor):
    """
    Translates a LangGraph agent node function body to Java statements.

    Supported patterns:
      state['key'] / state.get('key')    → state.getKey()
      state.get('key') with bool()       → !state.getKey().isEmpty()
      _sample(system=, user=, max_tokens=, agent_name=)  → sample(system, user, N)
      call_tool(stub, 'name', arg=val)   → toolMethod(val, ...)
      f-strings                          → Java string concatenation
      if/else, ternary                   → Java if/else / ternary
      bool(x)                            → !x.isEmpty()
      str.strip()                        → .trim()
      str.join(gen/list)                 → String.join(sep, items)
      " ".join(w for w in x[:N] if cond) → translated with stream
      return {key: val, ...}             → state.setKey(val); ... return state;
      AIMessage(...) / _ensure_grpc()    → skipped
      string concatenation               → Java +
      variable assignments               → Java type-inferred (String/boolean)
    """

    # Python built-in / LangGraph calls to skip entirely
    SKIP_CALLS = {"_ensure_grpc", "AIMessage", "HumanMessage", "BaseMessage"}

    def __init__(self, node_meta: dict, tool_map: dict, state_fields: list):
        self.node_meta    = node_meta
        self.tool_map     = tool_map                    # tool_name → tool object
        self.state_fields = {f["name"]: f for f in state_fields}
        self.lines        = []                          # output Java lines
        self._indent      = 2                           # indent level (in units)
        self._vars        = {}                          # name → inferred Java type

        # Build stub name map: mcp server name → Java field name
        self._stub_map = {}
        for srv in node_meta.get("mcp_servers", []):
            self._stub_map[srv["name"]] = srv["name"].replace("-", "_") + "_stub"

        # Map Python stub variables to Java field names
        # e.g. _web_search_stub → web_search_stub
        self._py_stub_to_java = {}
        for srv in node_meta.get("mcp_servers", []):
            py_var = "_" + srv["name"].replace("-", "_") + "_stub"
            self._py_stub_to_java[py_var] = srv["name"].replace("-", "_") + "_stub"

    def _emit(self, line: str):
        indent = "    " * self._indent
        self.lines.append(indent + line)

    def _emit_comment(self, text: str):
        self._emit("// " + text)

    def translate_body(self, fn_node: ast.FunctionDef) -> list[str]:
        for stmt in fn_node.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                continue  # skip docstring
            self._translate_stmt(stmt)
        return self.lines

    # ------------------------------------------------------------------
    # Statement dispatch
    # ------------------------------------------------------------------

    def _translate_stmt(self, stmt):
        if isinstance(stmt, ast.Assign):
            self._translate_assign(stmt)
        elif isinstance(stmt, ast.If):
            self._translate_if(stmt)
        elif isinstance(stmt, ast.Return):
            self._translate_return(stmt)
        elif isinstance(stmt, ast.Expr):
            # Standalone expression — only care about calls we don't skip
            if isinstance(stmt.value, ast.Call):
                fn = stmt.value.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                if name not in self.SKIP_CALLS:
                    self._emit(self._translate_expr(stmt.value) + ";")
            # else skip

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def _translate_assign(self, stmt: ast.Assign):
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            self._emit_comment("TODO: complex assignment target")
            return

        var   = target.id
        value = stmt.value

        # Skip _ensure_grpc() assignments (none exist but guard anyway)
        if isinstance(value, ast.Call):
            fn = value.func
            fn_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if fn_name in self.SKIP_CALLS:
                return

        java_val, java_type = self._translate_expr_typed(value)

        # Decide whether to declare or reassign
        if var not in self._vars:
            self._vars[var] = java_type
            self._emit(f"{java_type} {var} = {java_val};")
        else:
            self._emit(f"{var} = {java_val};")

    # ------------------------------------------------------------------
    # If / else
    # ------------------------------------------------------------------

    def _translate_if(self, stmt: ast.If):
        # Hoist variables assigned in only one branch so both branches can use them
        def assigned_names(stmts):
            names = set()
            for s in stmts:
                if isinstance(s, ast.Assign):
                    for t in s.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
            return names

        body_vars  = assigned_names(stmt.body)
        else_vars  = assigned_names(stmt.orelse)
        hoist_vars = body_vars | else_vars
        for var in hoist_vars:
            if var not in self._vars:
                self._vars[var] = "String"
                self._emit(f"String {var} = null;")

        cond = self._translate_expr(stmt.test)
        self._emit(f"if ({cond}) {{")
        self._indent += 1
        for s in stmt.body:
            self._translate_stmt(s)
        self._indent -= 1
        if stmt.orelse:
            self._emit("} else {")
            self._indent += 1
            for s in stmt.orelse:
                self._translate_stmt(s)
            self._indent -= 1
        self._emit("}")

    # ------------------------------------------------------------------
    # Return dict → state setters + return state
    # ------------------------------------------------------------------

    def _translate_return(self, stmt: ast.Return):
        val = stmt.value
        if isinstance(val, ast.Dict):
            for key, value in zip(val.keys, val.values):
                if not isinstance(key, ast.Constant):
                    continue
                field = key.value
                if field == "messages":
                    continue  # Java state doesn't track LangGraph messages
                if field not in self.state_fields:
                    self._emit_comment(f"TODO: unknown state field '{field}'")
                    continue
                setter = "set" + to_pascal(field)
                java_val = self._translate_expr(value)
                self._emit(f"state.{setter}({java_val});")
            self._emit("return state;")
        else:
            self._emit(f"return {self._translate_expr(val)};")

    # ------------------------------------------------------------------
    # Expression translation (returns Java string)
    # ------------------------------------------------------------------

    def _translate_expr(self, node) -> str:
        return self._translate_expr_typed(node)[0]

    def _translate_expr_typed(self, node) -> tuple[str, str]:
        """Returns (java_expr, java_type)."""

        # Constant
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                escaped = node.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
                return f'"{escaped}"', "String"
            if isinstance(node.value, bool):
                return str(node.value).lower(), "boolean"
            if isinstance(node.value, int):
                return str(node.value), "int"
            if isinstance(node.value, float):
                return str(node.value) + "f", "float"
            return str(node.value), "Object"

        # Name (variable reference)
        if isinstance(node, ast.Name):
            name = node.id
            if name == "True":  return "true",  "boolean"
            if name == "False": return "false", "boolean"
            if name == "None":  return "null",  "Object"
            return name, self._vars.get(name, "String")

        # state['key']
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "state":
            key = node.slice.value if isinstance(node.slice, ast.Constant) else self._translate_expr(node.slice)
            getter = "get" + to_pascal(key)
            sf = self.state_fields.get(key, {})
            java_type = "java.util.List<String>" if sf.get("type", "").startswith("repeated") else "String"
            return f"state.{getter}()", java_type

        # state.get('key')
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "state"
                and node.args and isinstance(node.args[0], ast.Constant)):
            key = node.args[0].value
            getter = "get" + to_pascal(key)
            sf = self.state_fields.get(key, {})
            java_type = "java.util.List<String>" if sf.get("type", "").startswith("repeated") else "String"
            return f"state.{getter}()", java_type

        # Attribute access (e.g. x.strip(), " ".join(...))
        if isinstance(node, ast.Attribute):
            obj = self._translate_expr(node.value)
            return f"{obj}.{node.attr}", "String"

        # Function call
        if isinstance(node, ast.Call):
            return self._translate_call(node)

        # f-string (JoinedStr)
        if isinstance(node, ast.JoinedStr):
            return self._translate_fstring(node), "String"

        # Unary op
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                operand, t = self._translate_expr_typed(node.operand)
                if t == "boolean":
                    return f"!{operand}", "boolean"
                # bool(x) pattern — treat as !x.isEmpty()
                return f"!{operand}.isEmpty()", "boolean"
            if isinstance(node.op, ast.USub):
                return f"-{self._translate_expr(node.operand)}", "int"

        # Binary op
        if isinstance(node, ast.BinOp):
            left,  lt = self._translate_expr_typed(node.left)
            right, rt = self._translate_expr_typed(node.right)
            if isinstance(node.op, ast.Add):
                if lt == "String" or rt == "String":
                    return f"{left} + {right}", "String"
                return f"{left} + {right}", lt
            if isinstance(node.op, ast.Mod):
                return f"{left} % {right}", lt

        # BoolOp (and / or)
        if isinstance(node, ast.BoolOp):
            op = " && " if isinstance(node.op, ast.And) else " || "
            parts = [self._translate_expr(v) for v in node.values]
            return op.join(parts), "boolean"

        # Compare
        if isinstance(node, ast.Compare):
            left = self._translate_expr(node.left)
            ops_map = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.Gt: ">", ast.LtE: "<=", ast.GtE: ">="
            }
            parts = []
            for op, comp in zip(node.ops, node.comparators):
                java_op = ops_map.get(type(op), "==")
                right = self._translate_expr(comp)
                # Use .equals() for string comparisons
                left_type = self._vars.get(node.left.id if isinstance(node.left, ast.Name) else "", "String")
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    if java_op == "==":
                        parts.append(f"{left}.equals({right})")
                    elif java_op == "!=":
                        parts.append(f"!{left}.equals({right})")
                    else:
                        parts.append(f"{left} {java_op} {right}")
                else:
                    parts.append(f"{left} {java_op} {right}")
                left = right
            return " && ".join(parts), "boolean"

        # Ternary (IfExp)
        if isinstance(node, ast.IfExp):
            test  = self._translate_expr(node.test)
            body, bt = self._translate_expr_typed(node.body)
            else_, _  = self._translate_expr_typed(node.orelse)
            return f"({test} ? {body} : {else_})", bt

        # List literal
        if isinstance(node, ast.List):
            elts = [self._translate_expr(e) for e in node.elts]
            if len(elts) == 1:
                return f"java.util.Arrays.asList({elts[0]})", "java.util.List<String>"
            joined = ", ".join(elts)
            return f"java.util.Arrays.asList({joined})", "java.util.List<String>"

        # Subscript slice (e.g. query.split()[:4])
        if isinstance(node, ast.Subscript):
            obj = self._translate_expr(node.value)
            if isinstance(node.slice, ast.Slice):
                upper = node.slice.upper
                if upper and isinstance(upper, ast.Constant):
                    return f"Arrays.copyOfRange({obj}, 0, Math.min({upper.value}, {obj}.length))", "String[]"
            return f"{obj}[{self._translate_expr(node.slice)}]", "String"

        # GeneratorExp used in " ".join(w for w in x if cond)
        if isinstance(node, ast.GeneratorExp):
            return self._translate_generator(node), "String"

        return f"/* TODO: {ast.dump(node)[:60]} */", "Object"

    # ------------------------------------------------------------------
    # Call translation
    # ------------------------------------------------------------------

    def _translate_call(self, node: ast.Call) -> tuple[str, str]:
        fn = node.func

        # _sample(system=, user=, max_tokens=, agent_name=) → sample(system, user, maxTokens)
        if isinstance(fn, ast.Name) and fn.id == "_sample":
            kw = {k.arg: k.value for k in node.keywords}
            system     = self._translate_expr(kw["system"])     if "system"     in kw else '""'
            user       = self._translate_expr(kw["user"])       if "user"       in kw else '""'
            max_tokens = self._translate_expr(kw["max_tokens"]) if "max_tokens" in kw else "2048"
            return f"sample({system}, {user}, {max_tokens})", "String"

        # call_tool(stub, 'mcp_tool_name', arg=val, ...) → pythonToolMethod(val, ...)
        if isinstance(fn, ast.Name) and fn.id == "call_tool":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mcp_tool_name = node.args[1].value
                kw = {k.arg: k.value for k in node.keywords if k.arg != "agent_name"}
                # First try direct match in tool_map
                tool = self.tool_map.get(mcp_tool_name)
                # Then try matching via mcp_servers[*].tool -> python tool name
                if tool is None:
                    for srv in self.node_meta.get("mcp_servers", []):
                        if srv.get("tool") == mcp_tool_name:
                            for t in self.tool_map.values():
                                if t.name in self.node_meta.get("tools", []):
                                    tool = t
                                    break
                            break
                if tool:
                    # Pass kwargs in tool.args order, falling back to positional kw values
                    kw_vals = list(kw.values())
                    arg_vals = []
                    for i, arg_name in enumerate(tool.args):
                        if arg_name in kw:
                            arg_vals.append(self._translate_expr(kw[arg_name]))
                        elif i < len(kw_vals):
                            arg_vals.append(self._translate_expr(kw_vals[i]))
                    return f"{tool.name}({', '.join(arg_vals)})", "String"
            return f"/* TODO: call_tool({ast.dump(node.args[1])[:30]}) */", "String"

        # bool(x) → !x.isEmpty()
        if isinstance(fn, ast.Name) and fn.id == "bool":
            inner, _ = self._translate_expr_typed(node.args[0])
            return f"({inner} != null && !{inner}.isEmpty())", "boolean"

        # str.strip() → .trim()
        if isinstance(fn, ast.Attribute) and fn.attr == "strip":
            obj = self._translate_expr(fn.value)
            return f"{obj}.trim()", "String"

        # list.append(x) → .add(x)
        if isinstance(fn, ast.Attribute) and fn.attr == "append" and node.args:
            obj = self._translate_expr(fn.value)
            arg = self._translate_expr(node.args[0])
            return f"{obj}.add({arg})", "boolean"

        # str.strip('"') → .replace("\"", "")
        if isinstance(fn, ast.Attribute) and fn.attr == "strip" and node.args:
            obj = self._translate_expr(fn.value)
            ch  = self._translate_expr(node.args[0])
            return f"{obj}.replace({ch}, \"\")", "String"

        # " ".join(generator) → stream-based join
        if isinstance(fn, ast.Attribute) and fn.attr == "join":
            sep = self._translate_expr(fn.value)
            if node.args:
                inner = self._translate_expr(node.args[0])
                return f"String.join({sep}, {inner})", "String"

        # skip SKIP_CALLS
        fn_name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if fn_name in self.SKIP_CALLS:
            return '""', "String"

        # Generic call fallback
        if isinstance(fn, ast.Name):
            args = [self._translate_expr(a) for a in node.args]
            args += [f"{k.arg}={self._translate_expr(k.value)}" for k in node.keywords]
            return f"{fn.id}({', '.join(args)})", "String"
        if isinstance(fn, ast.Attribute):
            obj  = self._translate_expr(fn.value)
            args = [self._translate_expr(a) for a in node.args]
            args += [self._translate_expr(k.value) for k in node.keywords]
            return f"{obj}.{fn.attr}({', '.join(args)})", "String"

        return f"/* TODO: call {ast.dump(fn)[:40]} */", "Object"

    # ------------------------------------------------------------------
    # f-string translation
    # ------------------------------------------------------------------

    def _translate_fstring(self, node: ast.JoinedStr) -> str:
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                escaped = v.value.replace('"', '\\"').replace('\n', '\\n')
                parts.append(f'"{escaped}"')
            elif isinstance(v, ast.FormattedValue):
                parts.append(self._translate_expr(v.value))
        if not parts:
            return '""'
        return " + ".join(parts)

    # ------------------------------------------------------------------
    # Generator expression (for " ".join(...))
    # ------------------------------------------------------------------

    def _translate_generator(self, node: ast.GeneratorExp) -> str:
        comp = node.generators[0]
        target = comp.target.id if isinstance(comp.target, ast.Name) else "w"

        # Resolve iter: handle x.split()[:N] → limit(N) on stream
        iter_node = comp.iter
        limit_str = ""
        if isinstance(iter_node, ast.Subscript) and isinstance(iter_node.slice, ast.Slice):
            upper = iter_node.slice.upper
            if upper and isinstance(upper, ast.Constant):
                limit_str = f".limit({upper.value})"
            iter_node = iter_node.value  # the expression before [:]

        iter_expr = self._translate_expr(iter_node)

        # Handle x.split() with no args → split("\\s+")
        if (isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Attribute)
                and iter_node.func.attr == "split" and not iter_node.args):
            base = self._translate_expr(iter_node.func.value)
            iter_expr = f"{base}.split(\"\\\\s+\")"

        # Translate filter conditions — replace Python builtins with Java equivalents
        if comp.ifs:
            raw_cond = self._translate_expr(comp.ifs[0])
            # isalnum() → matches("[a-zA-Z0-9]+")
            raw_cond = raw_cond.replace(f"{target}.isalnum()", f"{target}.matches(\"[a-zA-Z0-9]+\")")
            # len(w) > N → w.length() > N
            import re as _re
            raw_cond = _re.sub(r'len\((\w+)\)', r'\1.length()', raw_cond)
            elt_expr = self._translate_expr(node.elt)
            return (f"java.util.Arrays.stream({iter_expr}){limit_str}"
                    f".filter({target} -> {raw_cond})"
                    f".map({target} -> {elt_expr})"
                    f".collect(java.util.stream.Collectors.joining(\" \"))")

        elt_expr = self._translate_expr(node.elt)
        return (f"java.util.Arrays.stream({iter_expr}){limit_str}"
                f".map({target} -> {elt_expr})"
                f".collect(java.util.stream.Collectors.joining(\" \"))")


# ---------------------------------------------------------------------------
# Parse node function body from source file
# ---------------------------------------------------------------------------

def parse_node_fn(source: str, fn_name: str):
    """Return the ast.FunctionDef for fn_name from source."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn_name:
            return node
    return None


# ---------------------------------------------------------------------------
# Full agent node Java generator (with translated body)
# ---------------------------------------------------------------------------

def generate_agent_node_java(node: dict, package: str, tool_map: dict,
                              state_fields: list, source: str) -> str:
    class_name  = to_pascal(node["name"]) + "Node"
    server_name = node["name"].replace("_", "-") + "-agent"
    description = node.get("description", "")
    tools       = node.get("tools", [])
    mcp_servers = node.get("mcp_servers", [])
    port        = node.get("port", 50060)

    # Map node name to agent-id
    node_name = node["name"]
    if node_name == "supervisor":
        agent_id = "orchestrator"
    elif node_name == "research_agent":
        agent_id = "searcher"
    elif node_name == "writer_agent":
        agent_id = "writer"
    else:
        agent_id = node_name

    # Determine HTTP ports (gRPC port + 10 convention)
    http_ports = {srv['name']: srv['port'] + 10 for srv in mcp_servers}

    # Stub field declarations
    class_fields = []
    stub_fields = []
    stub_inits  = []
    for srv in mcp_servers:
        field = srv["name"].replace("-", "_") + "_stub"
        http_url_var = srv["name"].replace("-", "_").upper() + "_HTTP_URL"
        http_avail = srv["name"].replace("-", "_") + "_httpAvailable"
        stub_fields.append(
            f"    private MCPServerServiceGrpc.MCPServerServiceBlockingStub {field};"
        )
        class_fields.append(
            f"    private static final String {http_url_var} = \"http://localhost:{http_ports[srv['name']]}/mcp\";"
        )
        class_fields.append(
            f"    private boolean {http_avail} = false;"
        )
        stub_inits.append(
            f"{http_avail} = initHttpServer({http_url_var}, \"{agent_id}\");\n"
            f"        if (!{http_avail}) {{\n"
            f"            io.grpc.Metadata headers_{field} = new io.grpc.Metadata();\n"
            f"            headers_{field}.put(AgentIdInterceptor.AGENT_ID_META, \"{agent_id}\");\n"
            f"            {field} = MCPServerServiceGrpc.newBlockingStub(\n"
            f"                    ManagedChannelBuilder.forAddress(\"localhost\", {srv['port']}).usePlaintext().build())\n"
            f"                    .withInterceptors(io.grpc.stub.MetadataUtils.newAttachHeadersInterceptor(headers_{field}));\n"
            f"            {field}.initialize(Mcp.InitializeRequest.newBuilder()\n"
            f"                    .setProtocolVersion(\"2025-11-25\")\n"
            f"                    .setClientInfo(Mcp.ClientInfo.newBuilder()\n"
            f"                            .setName(\"{agent_id}\")\n"
            f"                            .setVersion(\"1.0\")\n"
            f"                            .setCallbackAddress(\"localhost:{port}\"))\n"
            f"                    .setCapabilities(Mcp.ClientCapabilities.newBuilder()\n"
            f"                            .setSampling(Mcp.SamplingCapability.newBuilder().build())\n"
            f"                            .build())\n"
            f"                    .build());\n"
            f"            {field}.notify(Mcp.NotifyRequest.newBuilder()\n"
            f"                    .setInitialized(Mcp.InitializedNotification.newBuilder().build())"
            f"                    .build());\n"
            f"        }}"
        )

    # samplingStub for MCPClientService callbacks
    stub_fields.append(
        "    private MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingStub;"
    )
    stub_inits.append(
        f"io.grpc.Metadata headers_sampling = new io.grpc.Metadata();\n"
        f"        headers_sampling.put(AgentIdInterceptor.AGENT_ID_META, \"{agent_id}\");\n"
        f"        headers_sampling.put(AgentIdInterceptor.SERVER_NAME_META, \"{agent_id}\");\n"
        f"        samplingStub = MCPClientServiceGrpc.newBlockingStub(\n"
        f"                ManagedChannelBuilder.forAddress(\"localhost\", {port}).usePlaintext().build())\n"
        f"                .withInterceptors(io.grpc.stub.MetadataUtils.newAttachHeadersInterceptor(headers_sampling));"
    )

    # sample() helper
    # HTTP init helpers
    helper_methods = textwrap.dedent(f"""\
    private boolean initHttpServer(String url, String agentName) {{
        try {{
            JsonObject ping = new JsonObject();
            ping.addProperty("jsonrpc", "2.0");
            ping.addProperty("method", "ping");
            ping.addProperty("id", 0);
            ping.add("params", new JsonObject());
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .header("MCP-Protocol-Version", "2025-11-25")
                    .POST(BodyPublishers.ofString(ping.toString()))
                    .build();
            HttpResponse<String> resp = httpClient.send(req, BodyHandlers.ofString());
            if (resp.statusCode() != 200) return false;
            JsonObject clientInfo = new JsonObject();
            clientInfo.addProperty("name", agentName);
            clientInfo.addProperty("version", "1.0");
            JsonObject caps = new JsonObject();
            caps.add("sampling", new JsonObject());
            JsonObject initParams = new JsonObject();
            initParams.addProperty("protocolVersion", "2025-11-25");
            initParams.add("clientInfo", clientInfo);
            initParams.add("capabilities", caps);
            jsonRpcRequest(url, 1, "initialize", initParams);
            jsonRpcRequest(url, 0, "notifications/initialized", null);
            return true;
        }} catch (Exception e) {{
            return false;
        }}
    }}

    private JsonObject jsonRpcRequest(String url, int id, String method, JsonObject params) throws Exception {{
        JsonObject envelope = new JsonObject();
        envelope.addProperty("jsonrpc", "2.0");
        envelope.addProperty("method", method);
        envelope.addProperty("id", id);
        if (params != null) {{
            envelope.add("params", params);
        }}
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json")
                .header("MCP-Protocol-Version", "2025-11-25")
                .POST(BodyPublishers.ofString(envelope.toString()))
                .build();
        HttpResponse<String> resp = httpClient.send(req, BodyHandlers.ofString());
        return JsonParser.parseString(resp.body()).getAsJsonObject();
    }}""")

    sample_helper = textwrap.dedent(f"""\
    private String sample(String system, String user, int maxTokens) {{
        log.agentToLlm("{agent_id}", "\\"" + system + "\\"");
        String result = samplingStub.createMessage(Mcp.CreateMessageRequest.newBuilder()
                .setSystemPrompt(system)
                .addMessages(Mcp.SamplingMessage.newBuilder()
                        .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER)
                        .setContent(Mcp.Content.newBuilder()
                                .setText(Mcp.TextContent.newBuilder().setText(user))))
                .setMaxTokens(maxTokens)
                .build())
                .getContent().getText().getText().trim();
        log.llmToAgent("{agent_id}", "\\"" + result.replace("\\n", " ").substring(0, Math.min(120, result.length())) + "\\"");
        return result;
    }}""")

    # Tool dispatch methods
    tool_methods = []
    for tool_name in tools:
        tool = tool_map.get(tool_name)
        if tool is None:
            continue
        params = ", ".join(f"String {a}" for a in tool.args)
        
        mcp_tool_name = tool_name
        mcp_param_map = {}
        if mcp_servers:
            for srv in mcp_servers:
                if srv.get("tool"):
                    mcp_tool_name = srv["tool"]
                    if mcp_tool_name == "write_file":
                        mcp_param_map = {"filename": "name"}
                    break

        put_fields = []
        for a in tool.args:
            target_arg = mcp_param_map.get(a, a)
            put_fields.append(
                f'.putFields("{target_arg}", com.google.protobuf.Value.newBuilder()'
                f'.setStringValue({a}).build())'
            )
        put_fields_str = "\n                        ".join(put_fields)
        
        srv_field = mcp_servers[0]["name"].replace("-", "_") + "_stub" if mcp_servers else "/* no stub */"
        http_avail = mcp_servers[0]["name"].replace("-", "_") + "_httpAvailable" if mcp_servers else "false"
        http_url_var = mcp_servers[0]["name"].replace("-", "_").upper() + "_HTTP_URL" if mcp_servers else '""'

        json_args = []
        for a in tool.args:
            target_arg = mcp_param_map.get(a, a)
            json_args.append(f'args.addProperty("{target_arg}", {a});')
        json_args_str = "\n            ".join(json_args)

        tool_methods.append(textwrap.dedent(f"""\
    String {tool_name}({params}) {{
        if ({http_avail}) {{
            try {{
                JsonObject args = new JsonObject();
                {json_args_str}
                JsonObject callParams = new JsonObject();
                callParams.addProperty("name", "{mcp_tool_name}");
                callParams.add("arguments", args);
                JsonObject resp = jsonRpcRequest({http_url_var}, 2, "tools/call", callParams);
                return resp.getAsJsonObject("result").getAsJsonArray("content")
                        .get(0).getAsJsonObject().get("text").getAsString();
            }} catch (Exception e) {{
                // fall through to gRPC
            }}
        }}
        Mcp.CallToolResponse resp = {srv_field}.callTool(
                Mcp.CallToolRequest.newBuilder()
                        .setName("{mcp_tool_name}")
                        .setArguments(com.google.protobuf.Struct.newBuilder()
                                {put_fields_str}
                                .build())
                        .build());
        return resp.getContent(0).getText().getText();
    }}"""))

    # Translate the node function body from the Python source
    fn_name = node["name"] + "_node"
    fn_node = parse_node_fn(source, fn_name)
    if fn_node:
        translator = JavaTranslator(node, tool_map, state_fields)
        body_lines = translator.translate_body(fn_node)
        translated_body = "\n".join(body_lines)
    else:
        translated_body = "        // TODO: implement " + node["name"] + " logic"

    class_fields.append(
        "    private static final HttpClient httpClient = HttpClient.newHttpClient();"
    )
    stub_fields_str = "\n".join(stub_fields)
    class_fields_str = "\n".join(class_fields)
    stub_inits_str  = "\n        ".join(stub_inits)
    tool_methods_str = "\n\n".join(tool_methods)

    return textwrap.dedent(f"""\
package {package};

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import io.grpc.ManagedChannelBuilder;
import io.grpc.Server;
import io.grpc.ServerBuilder;
import io.grpc.stub.StreamObserver;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpRequest.BodyPublishers;
import java.net.http.HttpResponse.BodyHandlers;
import java.util.Arrays;
import java.util.concurrent.TimeUnit;

// Auto-generated by langgraph_to_proto.py
// Node: {node['name']} — {description}
public class {class_name} extends BaseAgentNode {{

{stub_fields_str}
{class_fields_str}

    public {class_name}() {{
        super("{agent_id}");
        {stub_inits_str}
    }}

{sample_helper}

{helper_methods}

    // Translated from Python: {fn_name}
    public AgentState run(AgentState state) {{
{translated_body}
    }}

{tool_methods_str}

    public static void main(String[] args) throws Exception {{
        Server server = ServerBuilder.forPort({port})
                .addService(new {class_name}())
                .intercept(new AgentIdInterceptor())
                .build().start();
        System.out.println("{class_name} listening on port " + {port});
        server.awaitTermination();
    }}
}}
""")


# ---------------------------------------------------------------------------
# GraphRunner generator — drives the agent loop in pure Java
# ---------------------------------------------------------------------------

def generate_graph_runner_java(agent_nodes: list, graph_edges: list,
                                package: str, agent_name: str,
                                source: str) -> str:
    node_fields = []
    node_inits  = []
    inject_params = []
    inject_assigns = []
    for n in agent_nodes:
        class_name = to_pascal(n["name"]) + "Node"
        field_name = n["name"] + "Node"
        node_fields.append(f"    private final {class_name} {field_name};")
        node_inits.append(f'        this.{field_name} = new {class_name}();')
        inject_params.append(f"{class_name} {field_name}")
        inject_assigns.append(f'        this.{field_name} = {field_name};')

    # Parse the route() function and translate it to Java
    route_fn = parse_node_fn(source, "route")
    if route_fn:
        route_body = _translate_route_fn(route_fn, agent_nodes)
    else:
        # Fallback: generate from GRAPH_EDGES
        route_body = _route_body_from_edges(graph_edges)

    # Build the run-loop: call each node's run(), then route
    dispatch_cases = []
    for n in agent_nodes:
        name = n["name"]
        edges = [e for e in graph_edges if e["from"] == name]
        if len(edges) == 1 and edges[0]["condition"] is None:
            to_node = edges[0]["to"]
            if to_node != "__end__" and not to_node.endswith("_agent") and to_node != "supervisor":
                to_node = to_node + "_agent"
            next_stmt = f'current = "{to_node}";'
        else:
            next_stmt = 'current = route(state);'
            
        agent_label = "orchestrator" if name == "supervisor" else (
            "searcher" if name == "research_agent" else (
                "writer" if name == "writer_agent" else name))
        if name == "supervisor":
            dispatch_cases.append(textwrap.dedent(f"""\
            case "{name}":
                state = {name}Node.run(state);
                current = route(state);
                if (!current.equals("__end__")) {{
                    MCPLogger.agentToAgent("{name}", current, "Dispatch", "");
                }} else {{
                    MCPLogger.agentToAgent("{name}", "{name}", "Complete", "");
                }}
                break;"""))
        else:
            dispatch_cases.append(textwrap.dedent(f"""\
            case "{name}":
                state = {name}Node.run(state);
                MCPLogger.agentToAgent("{name}", "supervisor", "Complete", "");
                current = "supervisor";
                break;"""))

    topology_lines = []
    for e in graph_edges:
        cond = f" [{e['condition']}]" if e["condition"] else ""
        topology_lines.append(f"//   {e['from']} -> {e['to']}{cond}")
    topology_str = "\n".join(topology_lines)

    node_fields_str    = "\n".join(node_fields)
    node_inits_str     = "\n".join(node_inits)
    inject_params_str  = ", ".join(inject_params)
    inject_assigns_str = "\n".join(inject_assigns)
    dispatch_cases_str = "\n".join(dispatch_cases)

    # Entry node is the first agent node (supervisor)
    entry_node = agent_nodes[0]["name"] if agent_nodes else "supervisor"

    return textwrap.dedent(f"""\
package {package};

// Auto-generated by langgraph_to_proto.py — Agent: {agent_name}
// Graph topology:
{topology_str}
public class GraphRunner {{

{node_fields_str}

    public GraphRunner() {{
{node_inits_str}
    }}

    public GraphRunner({inject_params_str}) {{
{inject_assigns_str}
    }}

    public AgentState run(AgentState initialState) {{
        AgentState state = initialState;
        String current = "{entry_node}";
        int maxSteps = 20;
        for (int step = 0; step < maxSteps; step++) {{
            if (current.equals("__end__")) break;
            switch (current) {{
{dispatch_cases_str}
                default:
                    System.err.println("Unknown node: " + current);
                    return state;
            }}
        }}
        return state;
    }}

    private String route(AgentState state) {{
{route_body}
    }}

    public static void main(String[] args) {{
        AgentState state = new AgentState();
        state.setTask(args.length > 0 ? args[0]
                : "Research the Python programming language and write a summary report");
        AgentState result = new GraphRunner().run(state);
        System.out.println("Files written: " + result.getWrittenFiles());
    }}
}}
""")


def _translate_route_fn(fn: ast.FunctionDef, agent_nodes: list) -> str:
    """Translate the Python route() function body to Java."""
    lines = []
    indent = "        "
    for stmt in fn.body:
        if isinstance(stmt, ast.Assign):
            target = stmt.targets[0].id if isinstance(stmt.targets[0], ast.Name) else "_"
            val = _simple_expr(stmt.value)
            lines.append(f"{indent}String {target} = {val};")
        elif isinstance(stmt, ast.If):
            cond = _simple_expr(stmt.test)
            lines.append(f"{indent}if ({cond}) {{")
            for s in stmt.body:
                if isinstance(s, ast.Return):
                    lines.append(f"{indent}    return {_simple_expr(s.value)};")
            lines.append(f"{indent}}}")
        elif isinstance(stmt, ast.Return):
            lines.append(f"{indent}return {_simple_expr(stmt.value)};")
    return "\n".join(lines)


def _simple_expr(node) -> str:
    """Minimal expression translator for the route() function."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return f'"{node.value}"'
        return str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "state":
        key = node.slice.value if isinstance(node.slice, ast.Constant) else "?"
        return f'state.get{to_pascal(key)}()'
    if isinstance(node, ast.Attribute):
        return f"{_simple_expr(node.value)}.{node.attr}"
    if isinstance(node, ast.Compare):
        left = _simple_expr(node.left)
        op = {ast.Eq: "==", ast.NotEq: "!="}.get(type(node.ops[0]), "==")
        right = _simple_expr(node.comparators[0])
        if isinstance(node.comparators[0], ast.Constant) and isinstance(node.comparators[0].value, str):
            if op == "==":  return f'{left}.equals({right})'
            if op == "!=":  return f'!{left}.equals({right})'
        return f"{left} {op} {right}"
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(f'"{v.value}"')
            elif isinstance(v, ast.FormattedValue):
                parts.append(_simple_expr(v.value))
        return " + ".join(parts)
    if isinstance(node, ast.IfExp):
        return f"({_simple_expr(node.test)} ? {_simple_expr(node.body)} : {_simple_expr(node.orelse)})"
    return f'/* TODO: {ast.dump(node)[:40]} */'


def _route_body_from_edges(graph_edges: list) -> str:
    lines = ["        // Generated from GRAPH_EDGES"]
    terminal_src = None
    for e in graph_edges:
        if e["to"] == "__end__":
            terminal_src = e["from"]
    if terminal_src:
        lines.append(f'        if (state.getNext().equals("FINISH")) return "__end__";')
    lines.append('        return state.getNext() + "_agent";')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Infrastructure generators
# ---------------------------------------------------------------------------

def generate_ollama_client_java(package: str, model: str, url: str) -> str:
    return textwrap.dedent(f"""\
package {package};

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

// Auto-generated by langgraph_to_proto.py
public class OllamaClient {{

    private static final String URL   = "{url}";
    static final String MODEL = "{model}";
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    public static String call(String systemPrompt, String userMessage, int maxTokens) {{
        // Allow stub via system property for testing without LLM server
        String stub = System.getProperty("ollama.stub");
        if (stub != null && !stub.isEmpty()) {{
            return stub;
        }}
        int maxAttempts = 2;
        long delayMs = 500;
        Exception lastException = null;

        for (int attempt = 1; attempt <= maxAttempts; attempt++) {{
            try {{
                JsonObject body = new JsonObject();
                body.addProperty("model", MODEL);
                body.addProperty("max_tokens", maxTokens);

                JsonArray messages = new JsonArray();
                if (systemPrompt != null && !systemPrompt.isEmpty()) {{
                    JsonObject sys = new JsonObject();
                    sys.addProperty("role", "system");
                    sys.addProperty("content", systemPrompt);
                    messages.add(sys);
                }}
                JsonObject user = new JsonObject();
                user.addProperty("role", "user");
                user.addProperty("content", userMessage);
                messages.add(user);
                body.add("messages", messages);

                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(URL))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
                        .build();

                HttpResponse<String> resp = HTTP.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() != 200) {{
                    throw new RuntimeException("Ollama returned non-200 status code: " + resp.statusCode() + " body: " + resp.body());
                }}

                return JsonParser.parseString(resp.body())
                        .getAsJsonObject()
                        .getAsJsonArray("choices")
                        .get(0).getAsJsonObject()
                        .getAsJsonObject("message")
                        .get("content").getAsString();
            }} catch (Exception e) {{
                System.err.println("[OllamaClient] Attempt " + attempt + " failed: " + e.getMessage());
                lastException = e;
                if (attempt < maxAttempts) {{
                    long sleepTime = delayMs * attempt;
                    System.out.println("[OllamaClient] Sleeping " + sleepTime + "ms before retrying...");
                    try {{
                        Thread.sleep(sleepTime);
                    }} catch (InterruptedException ie) {{
                        Thread.currentThread().interrupt();
                        throw new RuntimeException("Ollama client call interrupted", ie);
                    }}
                }}
            }}
        }}
        throw new RuntimeException("llama-server call failed after " + maxAttempts + " attempts: " + (lastException != null ? lastException.getMessage() : "unknown error"), lastException);
    }}
}}
""")


def generate_mcp_client_impl_java(package: str, model: str) -> str:
    return textwrap.dedent(f"""\
package {package};

import io.grpc.stub.StreamObserver;

// Auto-generated by langgraph_to_proto.py
public class OllamaMCPClientImpl extends MCPClientServiceGrpc.MCPClientServiceImplBase {{

    @Override
    public void createMessage(Mcp.CreateMessageRequest req, StreamObserver<Mcp.CreateMessageResponse> out) {{
        try {{
            String userText = req.getMessagesCount() > 0
                    ? req.getMessages(0).getContent().getText().getText() : "";
            String response = OllamaClient.call(
                    req.getSystemPrompt(),
                    userText,
                    req.getMaxTokens() > 0 ? req.getMaxTokens() : 4096);
            out.onNext(Mcp.CreateMessageResponse.newBuilder()
                    .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_ASSISTANT)
                    .setContent(Mcp.Content.newBuilder()
                            .setText(Mcp.TextContent.newBuilder().setText(response)))
                    .setModel("{model}")
                    .setStopReason(Mcp.StopReason.STOP_REASON_END_TURN)
                    .build());
            out.onCompleted();
        }} catch (Exception e) {{
            out.onError(io.grpc.Status.INTERNAL
                    .withDescription("llama-server call failed: " + e.getMessage())
                    .asRuntimeException());
        }}
    }}

    @Override
    public void listRoots(Mcp.ListRootsRequest req, StreamObserver<Mcp.ListRootsResponse> out) {{
        out.onNext(Mcp.ListRootsResponse.newBuilder().build());
        out.onCompleted();
    }}
}}
""")


def generate_agent_id_interceptor_java(package: str) -> str:
    return textwrap.dedent(f"""\
package {package};

import io.grpc.Context;
import io.grpc.Contexts;
import io.grpc.Metadata;
import io.grpc.ServerCall;
import io.grpc.ServerCallHandler;
import io.grpc.ServerInterceptor;

// Auto-generated by langgraph_to_proto.py
public class AgentIdInterceptor implements ServerInterceptor {{

    public static final Metadata.Key<String> AGENT_ID_META =
            Metadata.Key.of("agent-id", Metadata.ASCII_STRING_MARSHALLER);

    public static final Metadata.Key<String> SERVER_NAME_META =
            Metadata.Key.of("server-name", Metadata.ASCII_STRING_MARSHALLER);

    public static final Context.Key<String> AGENT_ID =
            Context.key("agent-id");

    public static final Context.Key<String> SERVER_NAME =
            Context.key("server-name");

    @Override
    public <Req, Resp> ServerCall.Listener<Req> interceptCall(
            ServerCall<Req, Resp> call, Metadata headers, ServerCallHandler<Req, Resp> next) {{
        String agentId = headers.get(AGENT_ID_META);
        String serverName = headers.get(SERVER_NAME_META);
        Context ctx = Context.current()
                .withValue(AGENT_ID, agentId != null ? agentId : "unknown")
                .withValue(SERVER_NAME, serverName != null ? serverName : "unknown");
        return Contexts.interceptCall(ctx, call, headers, next);
    }}
}}
""")


def generate_mcp_logger_java(package: str) -> str:
    return textwrap.dedent(f"""\
package {package};

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;

// Auto-generated by langgraph_to_proto.py
public class MCPLogger {{

    private static final Path MCP_LOG = Path.of(System.getProperty("user.dir"), "output", "message.log");
    private static final Object LOCK = new Object();
    private static volatile boolean enabled = true;

    private final String peerName;

    public MCPLogger(String peerName) {{
        this.peerName = peerName;
    }}

    public static void setEnabled(boolean value) {{
        enabled = value;
    }}

    public static void beginRun(String label) {{
        synchronized (LOCK) {{
            try {{
                Files.createDirectories(MCP_LOG.getParent());
                String banner = String.format("%n### RUN START: %s [%s] ###%n", label, Instant.now());
                Files.writeString(MCP_LOG, banner, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
            }} catch (IOException ignored) {{}}
        }}
    }}

    public static void agentToAgent(String source, String target, String action, String detail) {{
        write(mapAgent(source), mapAgent(target), action, detail);
    }}

    public void agentToLlm(String agent, String detail) {{
        write(mapAgent(agent), "LLM", "Prompt", detail);
    }}

    public void llmToAgent(String agent, String detail) {{
        write("LLM", mapAgent(agent), "Result", detail);
    }}

    public void toolToAgentSampling(String agent, String detail) {{
        toolToAgentSampling(agent, peerName, detail);
    }}

    public void agentToToolSampling(String agent, String detail) {{
        agentToToolSampling(agent, peerName, detail);
    }}

    public void toolToAgentSampling(String agent, String peer, String detail) {{
        write(mapPeer(peer), mapAgent(agent), "Sampling", detail);
    }}

    public void agentToToolSampling(String agent, String peer, String detail) {{
        write(mapAgent(agent), mapPeer(peer), "SamplingResult", detail);
    }}

    public void agentToTool(String agent, String method, String detail) {{
        write(mapAgent(agent), mapPeer(peerName), method + "Request", detail);
    }}

    public void toolToAgent(String agent, String method, String detail) {{
        write(mapPeer(peerName), mapAgent(agent), method + "Response", detail);
    }}

    private static String mapAgent(String agent) {{
        if (agent == null) return "AGENT:unknown";
        return switch (agent) {{
            case "supervisor", "orchestrator" -> "AGENT:orchestrator";
            case "research_agent", "searcher" -> "AGENT:searcher";
            case "writer_agent", "writer" -> "AGENT:writer";
            case "integration-test-agent", "test-client" -> "AGENT:test-client";
            default -> "AGENT:" + agent;
        }};
    }}

    private String mapPeer(String peer) {{
        return switch (peer) {{
            case "web-search-mcp-server", "web_search" -> "TOOL:web_search";
            case "filesystem-mcp-server", "filesystem" -> "TOOL:filesystem";
            case "sampling-service", "llm" -> "LLM";
            default -> peer;
        }};
    }}

    private static void write(String source, String target, String action, String detail) {{
        if (!enabled) return;
        String ts = Instant.ofEpochMilli(System.currentTimeMillis()).toString();
        String entry = String.format("%-24s %-20s %-20s %-14s%n",
                ts, source, target, action);
        synchronized (LOCK) {{
            try {{
                Files.createDirectories(MCP_LOG.getParent());
                Files.writeString(MCP_LOG, entry, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            }} catch (IOException ignored) {{}}
        }}
    }}

    public void log(String msg) {{
        System.out.printf("[%s] [%s] %s%n", Instant.now(), peerName, msg);
        System.out.flush();
    }}
}}
""")


def generate_mcp_server_impl_java(package: str, srv: dict, repo_root: str) -> str:
    name        = srv["name"]
    class_name  = to_pascal(name.replace("-", "_")) + "MCPServerImpl"
    server_name = name + "-mcp-server"
    instructions = srv.get("instructions", "")
    imports     = srv.get("imports", [])
    tools       = srv.get("tools", [])
    output_dir  = srv.get("output_dir", False)
    snippet_path = Path(repo_root) / srv["snippet"]
    snippet     = snippet_path.read_text()

    import_block = "\n".join(f"import {i};" for i in imports)

    noise_words_def = ""
    if "noise_words" in srv:
        words_joined = ", ".join(f'"{w}"' for w in srv["noise_words"])
        noise_words_def = f"    public static final java.util.Set<String> NOISE_WORDS = java.util.Set.of({words_joined});\n"

    # constructor: output_dir servers get a Path baseDir arg; snippet provides the field + ctor body
    if output_dir:
        extra_imports = "import java.nio.file.Path;\n"
    else:
        extra_imports = ""

    # listTools entries
    list_tools_entries = []
    for t in tools:
        list_tools_entries.append(f"""\
                .addTools(Mcp.Tool.newBuilder()
                        .setName("{t['name']}")
                        .setDescription("{t['description']}"))""")
    list_tools_body = "\n".join(list_tools_entries)

    # callTool dispatcher: one case per tool, with optional pre-sampling for the first param
    cases = []
    for t in tools:
        params   = t.get("params", [])
        sampling = t.get("sampling")
        param_args = ", ".join(
            f'req.getArguments().getFieldsOrThrow("{p}").getStringValue()' for p in params
        )
        method_call = f'{t["name"]}({param_args})'

        if sampling:
            input_param = sampling["input_param"]
            system      = sampling["system"]
            max_tokens  = sampling["max_tokens"]
            pre = f"""\
                case "{t['name']}" -> {{
                    String _raw = {method_call};
                    if (samplingClient != null) {{
                        Mcp.CreateMessageResponse _sample = samplingClient
                                .withInterceptors(io.grpc.stub.MetadataUtils.newAttachHeadersInterceptor(serverNameHeader("{server_name}")))
                                .createMessage(Mcp.CreateMessageRequest.newBuilder()
                                        .setSystemPrompt("{system}")
                                        .addMessages(Mcp.SamplingMessage.newBuilder()
                                                .setRole(Mcp.PromptMessageRole.PROMPT_MESSAGE_ROLE_USER)
                                                .setContent(Mcp.Content.newBuilder()
                                                        .setText(Mcp.TextContent.newBuilder().setText(_raw))))
                                        .setMaxTokens({max_tokens})
                                        .build());
                        String _sampleText = _sample.getContent().getText().getText();
                        yield _sampleText;
                    }}
                    yield _raw;
                }}"""
            cases.append(pre)
        else:
            cases.append(f'                case "{t["name"]}" -> {method_call};')

    cases.append(f'                default -> "Unknown tool: " + req.getName();')
    cases_block = "\n".join(cases)

    # Resource templates — filesystem server provides a file:///{path} template
    if name == "filesystem":
        list_resource_templates = """\
    @Override
    public void listResourceTemplates(Mcp.ListResourceTemplatesRequest req, StreamObserver<Mcp.ListResourceTemplatesResponse> out) {{
        Mcp.ResourceTemplate template = Mcp.ResourceTemplate.newBuilder()
                .setUriTemplate("file:///{path}")
                .setName("File System Resource")
                .setDescription("Read any file on the server's filesystem using the file:///{path} URI template")
                .setMimeType("text/plain")
                .build();
        log.agentToTool(agent(), "ListResourceTemplates", "");
        out.onNext(Mcp.ListResourceTemplatesResponse.newBuilder()
                .addResourceTemplates(template)
                .build());
        out.onCompleted();
    }}"""
    else:
        list_resource_templates = "    @Override public void listResourceTemplates(Mcp.ListResourceTemplatesRequest r, StreamObserver<Mcp.ListResourceTemplatesResponse> o) {{ o.onNext(Mcp.ListResourceTemplatesResponse.newBuilder().build()); o.onCompleted(); }}"

    return textwrap.dedent(f"""\
// AUTO-GENERATED — DO NOT EDIT.  Modify tools/langgraph_to_proto.py instead.
// Re-run ./build.sh (or ./build-inner.sh inside Docker) to regenerate.

package {package};

import io.grpc.ManagedChannelBuilder;
import io.grpc.stub.StreamObserver;
{extra_imports}{import_block}

public class {class_name} extends MCPServerServiceGrpc.MCPServerServiceImplBase {{

    private final MCPLogger log = new MCPLogger("{server_name}");
    private String agent() {{ return AgentIdInterceptor.AGENT_ID.get(); }}
    private volatile MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient;

    public void setSamplingClient(MCPClientServiceGrpc.MCPClientServiceBlockingStub samplingClient) {{
        this.samplingClient = samplingClient;
    }}

{noise_words_def}
{snippet}
    @Override
    public void initialize(Mcp.InitializeRequest req, StreamObserver<Mcp.InitializeResponse> out) {{
        String callbackAddr = req.getClientInfo().getCallbackAddress();
        if (!callbackAddr.isEmpty()) {{
            samplingClient = MCPClientServiceGrpc.newBlockingStub(
                    ManagedChannelBuilder.forTarget(callbackAddr).usePlaintext().build());
            log.agentToTool(agent(), "Initialize", "client=" + req.getClientInfo().getName() + " callback=" + callbackAddr);
        }} else {{
            log.agentToTool(agent(), "Initialize", "client=" + req.getClientInfo().getName() + " (no callback)");
        }}
        out.onNext(Mcp.InitializeResponse.newBuilder()
                .setProtocolVersion(req.getProtocolVersion())
                .setServerInfo(Mcp.ServerInfo.newBuilder().setName("{server_name}").setVersion("1.0.0"))
                .setCapabilities(Mcp.ServerCapabilities.newBuilder()
                        .setTools(Mcp.ToolsCapability.newBuilder().build())
                        .setLogging(Mcp.LoggingCapability.newBuilder().build()))
                .setInstructions("{instructions}")
                .build());
        out.onCompleted();
    }}

    @Override
    public void ping(Mcp.PingRequest req, StreamObserver<Mcp.PingResponse> out) {{
        log.agentToTool(agent(), "Ping", "");
        out.onNext(Mcp.PingResponse.newBuilder().build());
        out.onCompleted();
    }}

    @Override
    public void listTools(Mcp.ListToolsRequest req, StreamObserver<Mcp.ListToolsResponse> out) {{
        log.agentToTool(agent(), "ListTools", "");
        out.onNext(Mcp.ListToolsResponse.newBuilder()
{list_tools_body}
                .build());
        out.onCompleted();
    }}

    @Override
    public void callTool(Mcp.CallToolRequest req, StreamObserver<Mcp.CallToolResponse> out) {{
        log.agentToTool(agent(), "CallTool", "tool=" + req.getName());
        try {{
            String result = switch (req.getName()) {{
{cases_block}
            }};
            log.toolToAgent(agent(), "CallTool",
                    "\\"" + result.replace("\\n", " ").substring(0, Math.min(120, result.length())) + "\\"");
            out.onNext(Mcp.CallToolResponse.newBuilder()
                    .addContent(Mcp.Content.newBuilder().setText(Mcp.TextContent.newBuilder().setText(result)))
                    .setIsError(false).build());
            out.onCompleted();
        }} catch (Exception e) {{
            out.onError(io.grpc.Status.INTERNAL.withDescription(e.getMessage()).asRuntimeException());
        }}
    }}

    private io.grpc.Metadata serverNameHeader(String name) {{
        io.grpc.Metadata m = new io.grpc.Metadata();
        m.put(io.grpc.Metadata.Key.of("server-name", io.grpc.Metadata.ASCII_STRING_MARSHALLER), name);
        m.put(AgentIdInterceptor.AGENT_ID_META, agent());
        return m;
    }}

    @Override
    public void notify(Mcp.NotifyRequest req, StreamObserver<Mcp.NotifyResponse> out) {{
        if (req.hasInitialized()) {{
            log.agentToTool(agent(), "Notify", "initialized");
        }}
        if (req.hasCancelled()) {{
            log.agentToTool(agent(), "Notify", "cancelled");
        }}
        if (req.hasRootsListChanged()) {{
            log.agentToTool(agent(), "Notify", "roots_list_changed");
        }}
        if (req.hasResourceListChanged()) {{
            log.agentToTool(agent(), "Notify", "resource_list_changed");
        }}
        if (req.hasToolListChanged()) {{
            log.agentToTool(agent(), "Notify", "tool_list_changed");
        }}
        if (req.hasPromptListChanged()) {{
            log.agentToTool(agent(), "Notify", "prompt_list_changed");
        }}
        out.onNext(Mcp.NotifyResponse.newBuilder().build());
        out.onCompleted();
    }}

    @Override public void listResources(Mcp.ListResourcesRequest r, StreamObserver<Mcp.ListResourcesResponse> o) {{ o.onNext(Mcp.ListResourcesResponse.newBuilder().build()); o.onCompleted(); }}
{list_resource_templates}
    @Override public void readResource(Mcp.ReadResourceRequest r, StreamObserver<Mcp.ReadResourceResponse> o) {{ o.onNext(Mcp.ReadResourceResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void subscribeResource(Mcp.SubscribeResourceRequest r, StreamObserver<Mcp.SubscribeResourceResponse> o) {{ o.onNext(Mcp.SubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void unsubscribeResource(Mcp.UnsubscribeResourceRequest r, StreamObserver<Mcp.UnsubscribeResourceResponse> o) {{ o.onNext(Mcp.UnsubscribeResourceResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void watchResources(Mcp.WatchResourcesRequest r, StreamObserver<Mcp.WatchResourcesResponse> o) {{ o.onCompleted(); }}
    @Override public void listPrompts(Mcp.ListPromptsRequest r, StreamObserver<Mcp.ListPromptsResponse> o) {{ o.onNext(Mcp.ListPromptsResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void getPrompt(Mcp.GetPromptRequest r, StreamObserver<Mcp.GetPromptResponse> o) {{ o.onNext(Mcp.GetPromptResponse.newBuilder().build()); o.onCompleted(); }}
    @Override public void streamLogs(Mcp.LoggingRequest r, StreamObserver<Mcp.LogEntry> o) {{ o.onCompleted(); }}
    @Override public void complete(Mcp.CompleteRequest r, StreamObserver<Mcp.CompleteResponse> o) {{ o.onNext(Mcp.CompleteResponse.newBuilder().build()); o.onCompleted(); }}
}}
""")


def generate_server_main_java(package: str, srv: dict) -> str:
    class_name  = to_pascal(srv["name"].replace("-", "_")) + "ServerMain"
    impl_class  = to_pascal(srv["name"].replace("-", "_")) + "MCPServerImpl"
    port        = srv["port"]
    output_dir  = srv.get("output_dir", False)
    label       = srv["name"]

    if output_dir:
        extra_imports = "import java.nio.file.Path;\n"
        dir_setup     = ('        Path outputDir = Path.of(System.getProperty("user.dir"), "output");\n'
                         '        outputDir.toFile().mkdirs();\n')
        service_arg   = "new " + impl_class + "(outputDir)"
        log_msg       = f'"{label} MCP server listening on port " + PORT + " (output: " + outputDir + ")"'
    else:
        extra_imports = ""
        dir_setup     = ""
        service_arg   = "new " + impl_class + "()"
        log_msg       = f'"{label} MCP server listening on port " + PORT'

    return textwrap.dedent(f"""\
package {package};

import io.grpc.Server;
import io.grpc.ServerBuilder;
{extra_imports}
// Auto-generated by langgraph_to_proto.py
public class {class_name} {{
    public static final int PORT = {port};

    public static void main(String[] args) throws Exception {{
{dir_setup}        Server server = ServerBuilder.forPort(PORT)
                .addService({service_arg})
                .intercept(new AgentIdInterceptor())
                .build()
                .start();
        System.out.println({log_msg});
        server.awaitTermination();
    }}
}}
""")


def generate_integration_test_java(package: str, agent_nodes: list,
                                    mcp_servers: list, tools: list) -> str:
    return textwrap.dedent(f"""\
package {package};

import io.grpc.Server;
import io.grpc.ServerBuilder;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class McpIntegrationTest {{

    private static final int TOTAL = 1;
    private static int testNumber = 0;

    private static void section(String title) {{
        testNumber++;
        System.out.println("\\n=== TEST " + testNumber + " of " + TOTAL + ": " + title + " ===");
    }}
    private static void print(String label, Object value) {{ System.out.println("[" + label + "] " + value); }}
    private static void divider() {{ System.out.println("--------------------------------------------------------------"); }}

    @Test
    public void research_orchestration_loop() throws Exception {{
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

        try {{
            GraphRunner runner = new GraphRunner(supervisorNode, researchNode, writerNode);
            AgentState state = new AgentState();
            state.setTask(researchQuestion);

            AgentState result = runner.run(state);

            print("Research results", result.getResearchResults());
            print("Written files", result.getWrittenFiles());

            assertFalse(result.getResearchResults().isEmpty(), "Research results should not be empty");
            assertFalse(result.getWrittenFiles().isEmpty(), "Written files should not be empty");
            assertEquals("research_report.txt", result.getWrittenFiles().get(0));
        }} finally {{
            supervisorServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
            researchServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
            writerServer.shutdownNow().awaitTermination(5, TimeUnit.SECONDS);
        }}
    }}
}}
""")


# ---------------------------------------------------------------------------
# Load agent module
# ---------------------------------------------------------------------------

def load_agent(path: str):
    spec = importlib.util.spec_from_file_location("agent", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    agent_path  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "example_agent.py")
    proto_path  = sys.argv[2] if len(sys.argv) > 2 else None
    test_path   = sys.argv[3] if len(sys.argv) > 3 else None

    print(f"Loading agent from: {agent_path}", file=sys.stderr)
    agent = load_agent(agent_path)

    tools        = getattr(agent, "TOOLS",        [])
    agent_name   = getattr(agent, "AGENT_NAME",   Path(agent_path).stem)
    package      = getattr(agent, "PACKAGE",      "mcp.v1")
    agent_nodes  = getattr(agent, "AGENT_NODES",  [])
    graph_edges  = getattr(agent, "GRAPH_EDGES",  [])
    state_fields = getattr(agent, "STATE_FIELDS", [])
    mcp_servers  = getattr(agent, "MCP_SERVERS",  [])
    ollama_model = getattr(agent, "OLLAMA_MODEL", "qwen2.5:14b")
    ollama_url   = getattr(agent, "OLLAMA_URL",   "http://localhost:11434/v1/chat/completions")

    if not tools:
        print("ERROR: agent module must define a TOOLS list", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(tools)} tools: {', '.join(t.name for t in tools)}", file=sys.stderr)
    if agent_nodes:
        print(f"Found {len(agent_nodes)} agent nodes: {', '.join(n['name'] for n in agent_nodes)}", file=sys.stderr)

    # Proto + proto unit test (existing)
    proto = generate_proto(tools, agent_name, package)
    if proto_path:
        Path(proto_path).parent.mkdir(parents=True, exist_ok=True)
        Path(proto_path).write_text(proto)
        print(f"Proto written to: {proto_path}", file=sys.stderr)
    else:
        print(proto)

    test_java = generate_test_java(tools, agent_name, package)
    if test_path:
        Path(test_path).parent.mkdir(parents=True, exist_ok=True)
        Path(test_path).write_text(test_java)
        print(f"Proto test written to: {test_path}", file=sys.stderr)
    else:
        print(test_java)

    # Infrastructure (always generated if package is known)
    if test_path:
        pkg_depth_infra = len(package.split("."))
        src_root_infra  = str(Path(test_path).resolve().parents[3 + pkg_depth_infra])
    else:
        src_root_infra  = os.path.join(os.path.dirname(agent_path), "..")

    infra_main_dir = Path(src_root_infra) / "src" / "main" / "java" / package.replace(".", "/")
    infra_test_dir = Path(test_path).parent if test_path else \
                     Path(src_root_infra) / "src" / "test" / "java" / package.replace(".", "/")
    infra_main_dir.mkdir(parents=True, exist_ok=True)

    for fname, content in [
        ("OllamaClient.java",       generate_ollama_client_java(package, ollama_model, ollama_url)),
        ("OllamaMCPClientImpl.java", generate_mcp_client_impl_java(package, ollama_model)),
        ("AgentIdInterceptor.java",  generate_agent_id_interceptor_java(package)),
        ("MCPLogger.java",           generate_mcp_logger_java(package)),
    ]:
        out = infra_main_dir / fname
        out.write_text(content)
        print(f"{fname} written to: {out}", file=sys.stderr)

    impl_dir = infra_main_dir / "impl"
    impl_dir.mkdir(parents=True, exist_ok=True)

    for srv in mcp_servers:
        srv_pascal = to_pascal(srv["name"].replace("-", "_"))

        main_name = srv_pascal + "ServerMain"
        out = infra_main_dir / f"{main_name}.java"
        out.write_text(generate_server_main_java(package, srv))
        print(f"{main_name}.java written to: {out}", file=sys.stderr)

        if "snippet" in srv:
            impl_name = srv_pascal + "MCPServerImpl"
            impl_out  = impl_dir / f"{impl_name}.java"
            impl_out.write_text(generate_mcp_server_impl_java(package, srv, src_root_infra))
            print(f"{impl_name}.java written to: {impl_out}", file=sys.stderr)

    if agent_nodes and mcp_servers:
        integ_java = generate_integration_test_java(package, agent_nodes, mcp_servers,
                                                     getattr(agent, "TOOLS", []))
        integ_out  = infra_test_dir / "McpIntegrationTest.java"
        integ_out.write_text(integ_java)
        print(f"McpIntegrationTest.java written to: {integ_out}", file=sys.stderr)

    if not agent_nodes:
        return

    # Read source for AST translation
    source = Path(agent_path).read_text()

    tool_map = {t.name: t for t in tools}
    pkg_path = package.replace(".", "/")

    if test_path:
        pkg_depth = len(package.split("."))
        src_root = str(Path(test_path).resolve().parents[3 + pkg_depth])
    else:
        src_root = os.path.join(os.path.dirname(agent_path), "..")

    main_dir = Path(src_root) / "src" / "main" / "java" / pkg_path
    test_dir = Path(test_path).parent if test_path else Path(src_root) / "src" / "test" / "java" / pkg_path

    # AgentState.java
    state_java = generate_agent_state_java(state_fields, package)
    state_out  = main_dir / "AgentState.java"
    state_out.parent.mkdir(parents=True, exist_ok=True)
    state_out.write_text(state_java)
    print(f"AgentState written to: {state_out}", file=sys.stderr)

    # One full node implementation per agent node (with translated body)
    for node in agent_nodes:
        class_name = to_pascal(node["name"]) + "Node"
        node_java  = generate_agent_node_java(node, package, tool_map, state_fields, source)
        node_out   = main_dir / f"{class_name}.java"
        node_out.write_text(node_java)
        print(f"Node written to: {node_out}", file=sys.stderr)

    # GraphRunner.java — pure Java agent loop driver
    runner_java = generate_graph_runner_java(agent_nodes, graph_edges, package, agent_name, source)
    runner_out  = main_dir / "GraphRunner.java"
    runner_out.write_text(runner_java)
    print(f"GraphRunner written to: {runner_out}", file=sys.stderr)

    # McpOrchestrationTest.java generation removed


if __name__ == "__main__":
    main()
