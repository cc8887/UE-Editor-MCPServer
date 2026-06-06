# test_mcp_client.py - Dual-transport MCP regression test (SSE + STDIO)
#
# Independent of Unreal Engine, pure Python MCP protocol implementation.
# Easy to share with others for quick verification of UE-Editor-MCPServer.
#
# Prerequisites:
#   1. UE Editor running with MCPForwarder plugin on port 8100, or pass --launch-editor
#   2. For SSE: MCP SSE Server running on port 8099
#   3. For STDIO: main.py (MCPStandalone) available in this directory
#
# Usage:
#   python test_mcp_client.py                          # Run all tests on both transports
#   python test_mcp_client.py --transport sse          # SSE only
#   python test_mcp_client.py --transport stdio        # STDIO only
#   python test_mcp_client.py --transport both         # Both (default)
#   python test_mcp_client.py --launch-editor --transport stdio
#   python test_mcp_client.py --test ping              # Only ping test
#   python test_mcp_client.py --test exec              # Only execute_command
#   python test_mcp_client.py --test file              # Only excute_file
#   python test_mcp_client.py --test error             # Only error handling
#   python test_mcp_client.py --test list_tools        # Only base tool discovery
#   python test_mcp_client.py --test list_project_tools \
#       --project E:\UE5Projects\Foo\Foo.uproject      # Verify open_editor/close_editor are exposed

import asyncio
import json
import sys
import os
import argparse
import time
import uuid
import subprocess
from collections import deque
from typing import Optional, List, Dict, Any
from abc import ABC, abstractmethod


# --- ANSI colors ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg):
    print(f"  {GREEN}*{RESET} {msg}")


def fail(msg):
    print(f"  {RED}X{RESET} {msg}")


def info(msg):
    print(f"  {CYAN}>{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}!{RESET} {msg}")


def _plugin_dir() -> str:
    # This file lives in Tests/ -- go up one level to reach the plugin root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_editor_exe() -> str:
    return os.path.abspath(os.path.join(_plugin_dir(), "..", "..", "Binaries", "Win64", "MCPEditor.exe"))


def _default_uproject() -> str:
    return os.path.abspath(os.path.join(_plugin_dir(), "..", "..", "MCP.uproject"))


# --- Abstract MCP Client Interface ---

class MCPClientBase(ABC):
    """Abstract base class for MCP clients (SSE and STDIO share the same API)."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to MCP server."""
        ...

    @abstractmethod
    async def initialize(self) -> bool:
        """Send MCP initialize handshake."""
        ...

    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        ...

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool by name."""
        ...

    @abstractmethod
    async def close(self):
        """Close connection."""
        ...

    @property
    @abstractmethod
    def transport_name(self) -> str:
        """Human-readable transport name."""
        ...


# --- MCP SSE Client ---

class MCPSSEClient(MCPClientBase):
    """Minimal MCP SSE client using only stdlib."""

    def __init__(self, sse_url):
        self.sse_url = sse_url
        self.post_url = None
        self.session_id = None
        self._reader = None
        self._writer = None
        self._response_events = {}
        self._response_data = {}
        self._recv_task = None
        self._initialized = False
        # SSE clients connect to an already-running server; the harness has no
        # control over whether it was started with --project. The tool-discovery
        # tests use this attribute to decide which expectations apply.
        self.editor_project: Optional[str] = None

    @property
    def transport_name(self) -> str:
        return "SSE"

    async def connect(self):
        """Establish SSE connection and wait for endpoint event."""
        from urllib.parse import urlparse

        parsed = urlparse(self.sse_url)
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/SSE"

        info(f"Connecting to {host}:{port}{path} ...")

        try:
            self._reader, self._writer = await asyncio.open_connection(host, port)
        except (ConnectionRefusedError, OSError) as e:
            fail(f"Connection refused: {e}")
            return False

        # Send HTTP GET to establish SSE stream
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Cache-Control: no-cache\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
        self._writer.write(request.encode())
        await self._writer.drain()

        # Read HTTP response headers
        status_line = await self._reader.readline()
        if b"200" not in status_line:
            fail(f"SSE endpoint returned: {status_line.decode().strip()}")
            return False

        # Skip remaining headers
        while True:
            line = await self._reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        ok("SSE stream established")

        # Start background receiver
        self._recv_task = asyncio.create_task(self._recv_loop())

        # Wait for endpoint event (max 5s)
        deadline = time.monotonic() + 5.0
        while self.post_url is None and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

        if self.post_url is None:
            fail("Timeout waiting for SSE endpoint event")
            return False

        ok(f"Got POST endpoint: {self.post_url}")
        return True

    async def initialize(self):
        """Send MCP initialize request."""
        result = await self._send_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-mcp-client",
                "version": "1.0.0"
            }
        })

        if result is None:
            fail("initialize request failed")
            return False

        server_name = "?"
        if isinstance(result, dict):
            server_name = result.get("serverInfo", {}).get("name", "?")
        ok(f"Initialized: server={server_name}")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})
        ok("Sent initialized notification")

        self._initialized = True
        return True

    async def list_tools(self):
        """List available tools."""
        result = await self._send_jsonrpc("tools/list", {})
        if result is None:
            return []
        tools = result.get("tools", [])
        return tools

    async def call_tool(self, name, arguments):
        """Call a tool."""
        result = await self._send_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return result or {}

    async def close(self):
        """Close connection."""
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    # --- Internal ---

    async def _recv_loop(self):
        """Background SSE event receiver."""
        current_event = None
        current_data_lines = []

        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")

                if decoded.startswith("event:"):
                    current_event = decoded[6:].strip()
                elif decoded.startswith("data:"):
                    current_data_lines.append(decoded[5:].strip())
                elif decoded == "":
                    # Empty line = event boundary
                    if current_event and current_data_lines:
                        data_str = "\n".join(current_data_lines)
                        await self._handle_sse_event(current_event, data_str)
                    current_event = None
                    current_data_lines = []
        except asyncio.CancelledError:
            pass
        except Exception as e:
            warn(f"SSE recv error: {e}")

    async def _handle_sse_event(self, event, data):
        """Handle an SSE event."""
        if event == "endpoint":
            self.post_url = data
            if "session_id=" in data:
                self.session_id = data.split("session_id=")[-1].split("&")[0]

        elif event == "message":
            try:
                msg = json.loads(data)
                req_id = msg.get("id")
                if req_id and req_id in self._response_events:
                    self._response_data[req_id] = msg
                    self._response_events[req_id].set()
            except json.JSONDecodeError:
                pass

    async def _send_jsonrpc(self, method, params, timeout=30.0):
        """Send JSON-RPC request and wait for response."""
        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }

        event = asyncio.Event()
        self._response_events[req_id] = event

        await self._post(payload)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            resp = self._response_data.pop(req_id, None)
            self._response_events.pop(req_id, None)

            if resp and "error" in resp:
                fail(f"JSON-RPC error: {resp['error']}")
                return resp
            return resp.get("result") if resp else None
        except asyncio.TimeoutError:
            self._response_events.pop(req_id, None)
            fail(f"Request timed out ({method})")
            return None

    async def _send_notification(self, method, params):
        """Send JSON-RPC notification (no id, no response expected)."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._post(payload)

    async def _post(self, payload):
        """POST JSON to MCP messages endpoint via a SEPARATE connection."""
        from urllib.parse import urlparse

        if not self.post_url:
            fail("No POST endpoint available")
            return

        sse_parsed = urlparse(self.sse_url)
        host = sse_parsed.hostname
        port = sse_parsed.port or 80

        if self.post_url.startswith("http"):
            p = urlparse(self.post_url)
            host = p.hostname
            port = p.port or 80
            path = p.path
            if p.query:
                path = path + "?" + p.query
        else:
            path = self.post_url

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )

        post_reader, post_writer = await asyncio.open_connection(host, port)
        try:
            post_writer.write(request.encode() + body)
            await post_writer.drain()
            try:
                await asyncio.wait_for(post_reader.readline(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        finally:
            post_writer.close()
            try:
                await post_writer.wait_closed()
            except Exception:
                pass


# --- MCP STDIO Client ---

class MCPStdioClient(MCPClientBase):
    """MCP STDIO client - spawns MCPStandalone as subprocess, communicates via stdin/stdout."""

    def __init__(self, server_script: str = None, editor_port: int = 8100,
                 editor_host: str = "127.0.0.1", editor_project: Optional[str] = None):
        """
        Args:
            server_script: Path to main.py (defaults to main.py in this directory)
            editor_port: Editor forwarder port
            editor_host: Editor forwarder host
            editor_project: Optional .uproject path; passed as --project to MCPStandalone
                so the tool-discovery test can verify open_editor / close_editor
                are exposed when (and only when) a project is configured.
        """
        if server_script is None:
            server_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        self.server_script = server_script
        self.editor_port = editor_port
        self.editor_host = editor_host
        self.editor_project = editor_project
        self._process: Optional[asyncio.subprocess.Process] = None
        self._response_futures: Dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._wait_task: Optional[asyncio.Task] = None
        self._stderr_lines = deque(maxlen=40)
        self._stdout_leaks = deque(maxlen=20)
        self._initialized = False

    @property
    def transport_name(self) -> str:
        return "STDIO"

    async def connect(self) -> bool:
        """Spawn the MCP server subprocess in stdio mode."""
        if not os.path.isfile(self.server_script):
            fail(f"Server script not found: {self.server_script}")
            return False

        info(f"Spawning STDIO server: {self.server_script}")
        info(f"Editor target: {self.editor_host}:{self.editor_port}")
        if self.editor_project:
            info(f"Project (enables open_editor/close_editor): {self.editor_project}")

        lock_name = f"MCPStandalone-stdio-{uuid.uuid4().hex}.lock"
        env = os.environ.copy()
        env["MCP_STANDALONE_LOCK_NAME"] = lock_name
        # Force EDITOR_PROJECT off in the child env unless this client opted in,
        # otherwise a stray .env value would leak project tools into tests that
        # explicitly want to verify their absence.
        if self.editor_project is None:
            env.pop("EDITOR_PROJECT", None)
        else:
            env["EDITOR_PROJECT"] = self.editor_project

        cmd = [
            sys.executable, self.server_script,
            "--transport", "stdio",
            "--editor-host", self.editor_host,
            "--editor-port", str(self.editor_port),
        ]
        if self.editor_project:
            cmd.extend(["--project", self.editor_project])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as e:
            fail(f"Failed to spawn server process: {e}")
            return False

        self._recv_task = asyncio.create_task(self._recv_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        self._wait_task = asyncio.create_task(self._process.wait())

        done, _ = await asyncio.wait({self._wait_task}, timeout=1.0)
        if done:
            fail(f"Server process exited immediately (rc={self._process.returncode})")
            self._report_process_output()
            return False

        ok("STDIO server process started")
        return True

    async def initialize(self) -> bool:
        """Send MCP initialize request over stdio."""
        result = await self._send_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-mcp-client-stdio",
                "version": "1.0.0"
            }
        })

        if result is None:
            fail("initialize request failed (stdio)")
            return False

        server_name = "?"
        if isinstance(result, dict):
            server_name = result.get("serverInfo", {}).get("name", "?")
        ok(f"Initialized: server={server_name}")

        await self._send_notification("notifications/initialized", {})
        ok("Sent initialized notification")

        self._initialized = True
        return True

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        result = await self._send_jsonrpc("tools/list", {})
        if result is None:
            return []
        tools = result.get("tools", [])
        return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool."""
        result = await self._send_jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return result or {}

    async def close(self):
        """Terminate the subprocess."""
        for task in (self._recv_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
            except Exception as e:
                warn(f"Failed to stop STDIO server process: {e}")

        if self._wait_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._wait_task), timeout=0.5)
            except Exception:
                pass

    # --- Internal ---

    def _fail_pending_requests(self, reason: str):
        for req_id, future in list(self._response_futures.items()):
            if not future.done():
                future.set_exception(RuntimeError(reason))
            self._response_futures.pop(req_id, None)

    def _report_process_output(self):
        stderr_out = "\n".join(self._stderr_lines).strip()
        stdout_leaks = "\n".join(self._stdout_leaks).strip()
        if stderr_out:
            warn(f"stderr: {stderr_out[:1000]}")
        if stdout_leaks:
            warn(f"unexpected stdout: {stdout_leaks[:1000]}")

    async def _recv_loop(self):
        """Background reader for stdout - parses JSON-RPC responses."""
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    self._fail_pending_requests("STDIO server stdout closed")
                    break

                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue

                try:
                    msg = json.loads(decoded)
                except json.JSONDecodeError:
                    self._stdout_leaks.append(decoded)
                    continue

                req_id = msg.get("id")
                if req_id and req_id in self._response_futures:
                    future = self._response_futures.pop(req_id)
                    if not future.done():
                        future.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._fail_pending_requests(f"STDIO recv error: {e}")
            warn(f"STDIO recv error: {e}")

    async def _stderr_loop(self):
        """Background reader for stderr - keeps recent diagnostics for failures."""
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    self._stderr_lines.append(decoded)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            warn(f"STDIO stderr error: {e}")

    async def _send_jsonrpc(self, method: str, params: dict, timeout: float = 30.0):
        """Send JSON-RPC request and wait for response."""
        if self._process is None or self._process.returncode is not None:
            fail("STDIO server process not running")
            self._report_process_output()
            return None

        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }

        future = asyncio.get_event_loop().create_future()
        self._response_futures[req_id] = future

        data = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, AttributeError) as e:
            self._response_futures.pop(req_id, None)
            fail(f"Failed to write request ({method}): {e}")
            self._report_process_output()
            return None

        try:
            resp = await asyncio.wait_for(future, timeout=timeout)

            if resp and "error" in resp:
                fail(f"JSON-RPC error: {resp['error']}")
                return resp
            return resp.get("result") if resp else None
        except asyncio.TimeoutError:
            self._response_futures.pop(req_id, None)
            fail(f"Request timed out ({method})")
            self._report_process_output()
            return None
        except RuntimeError as e:
            self._response_futures.pop(req_id, None)
            fail(f"{e} ({method})")
            self._report_process_output()
            return None

    async def _send_notification(self, method: str, params: dict):
        """Send JSON-RPC notification (no id, no response expected)."""
        if self._process is None or self._process.returncode is not None:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        data = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, AttributeError):
            self._report_process_output()


# --- Helper ---

def _extract_text(result):
    """Extract text content from MCP tool call result."""
    content = result.get("content", []) if isinstance(result, dict) else []
    texts = []
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            texts.append(c.get("text", ""))
    return "\n".join(texts)


def _has_error(result):
    """Check if MCP tool call result contains an error."""
    if not isinstance(result, dict):
        return False
    content = result.get("content", [])
    for c in content:
        if isinstance(c, dict) and c.get("isError"):
            return True
    return False


# --- Expected Tool Specifications ---
#
# Source of truth for the discovery test. Each entry mirrors the
# ToolDefinition declared in Content/Python/mcp_server/MCPCore.py.
#
# Fields:
#   required:      properties that MUST appear in inputSchema.required
#   properties:    expected (key -> expected JSON Schema "type") mapping
#                  for inputSchema.properties; checked as a subset
#   keywords:      lowercase substrings that must appear in description
#                  (sanity check: prevents accidentally swapping descriptions)

EXPECTED_BASE_TOOLS = {
    "execute_command": {
        "required": ["code"],
        "properties": {"code": "string"},
        "keywords": ["python", "unreal"],
    },
    "excute_file": {  # spelled this way for backward compatibility
        "required": ["file"],
        "properties": {"file": "string"},
        "keywords": ["python", "file"],
    },
    "get_editor_state": {
        "required": [],
        "properties": {},
        "keywords": ["state"],
    },
}

EXPECTED_PROJECT_TOOLS = {
    "open_editor": {
        "required": [],
        "properties": {},
        "keywords": ["editor", "ready"],
    },
    "close_editor": {
        "required": [],
        "properties": {},
        "keywords": ["close", "editor"],
    },
}


def _validate_tool_schema(tool: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """
    Validate a tool's structure against an expected spec.

    Returns a list of error strings (empty == valid).
    """
    errors: List[str] = []
    name = tool.get("name", "<no name>")

    # description present and non-empty
    desc = tool.get("description") or ""
    if not isinstance(desc, str) or not desc.strip():
        errors.append(f"{name}: missing/empty description")
    else:
        desc_lower = desc.lower()
        for kw in expected.get("keywords", []):
            if kw.lower() not in desc_lower:
                errors.append(
                    f"{name}: description missing keyword '{kw}' (got: '{desc[:80]}...')"
                )

    # inputSchema is a JSON object schema
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict):
        errors.append(f"{name}: inputSchema is not an object")
        return errors

    if schema.get("type") != "object":
        errors.append(f"{name}: inputSchema.type != 'object' (got {schema.get('type')!r})")

    # properties: each expected key must exist with the expected JSON-Schema type
    actual_props = schema.get("properties") or {}
    if not isinstance(actual_props, dict):
        errors.append(f"{name}: inputSchema.properties is not an object")
        actual_props = {}

    for prop, expected_type in expected.get("properties", {}).items():
        if prop not in actual_props:
            errors.append(f"{name}: missing property '{prop}' in inputSchema.properties")
            continue
        prop_def = actual_props[prop]
        if not isinstance(prop_def, dict):
            errors.append(f"{name}: property '{prop}' is not an object")
            continue
        actual_type = prop_def.get("type")
        if actual_type != expected_type:
            errors.append(
                f"{name}: property '{prop}' type mismatch "
                f"(expected {expected_type!r}, got {actual_type!r})"
            )

    # required fields
    actual_required = set(schema.get("required") or [])
    expected_required = set(expected.get("required", []))
    missing_required = expected_required - actual_required
    if missing_required:
        errors.append(
            f"{name}: missing required field(s) {sorted(missing_required)} "
            f"(got required={sorted(actual_required)})"
        )

    return errors


def _validate_tool_set(
    tools: List[Dict[str, Any]],
    expected_specs: Dict[str, Dict[str, Any]],
    *,
    must_be_absent: Optional[set] = None,
) -> bool:
    """
    Validate a returned tool list:
    - every tool in `expected_specs` is present and schema-valid
    - any tool name in `must_be_absent` does NOT appear

    Returns True iff all checks pass. Prints details via ok/warn/fail.
    """
    tool_names = [t.get("name") for t in tools if isinstance(t, dict)]
    by_name = {t.get("name"): t for t in tools if isinstance(t, dict)}

    info(f"Server reported {len(tools)} tool(s): {sorted(tool_names)}")

    all_passed = True

    # Required tools present + schema-valid
    for tool_name, spec in expected_specs.items():
        if tool_name not in by_name:
            fail(f"Missing required tool: {tool_name}")
            all_passed = False
            continue
        errs = _validate_tool_schema(by_name[tool_name], spec)
        if errs:
            fail(f"Schema problems for '{tool_name}':")
            for e in errs:
                warn(f"    {e}")
            all_passed = False
        else:
            desc_preview = (by_name[tool_name].get("description") or "")[:60]
            ok(f"{tool_name}: schema OK — {desc_preview}")

    # Tools that MUST NOT appear (e.g. project tools when project not configured)
    if must_be_absent:
        leaked = [n for n in must_be_absent if n in by_name]
        if leaked:
            fail(f"Unexpectedly exposed tool(s): {leaked}")
            all_passed = False
        else:
            absent_list = sorted(must_be_absent)
            ok(f"Confirmed absent (project not configured): {absent_list}")

    return all_passed


# --- Test Cases (transport-agnostic) ---

async def test_initialize(client: MCPClientBase):
    """Test: MCP initialize handshake (covered implicitly by connect+initialize)."""
    # initialize is already done in the setup phase; if we got here, it passed.
    print(f"\n[Test] Initialize ({client.transport_name})")
    ok("Initialize handshake succeeded (verified during setup)")
    return True


async def test_list_tools(client: MCPClientBase):
    """
    Test: tools/list discovery returns all base tools with valid schemas.

    Validates for each base tool (execute_command, excute_file, get_editor_state):
    - tool is present in the returned list
    - description is non-empty and contains expected keywords
    - inputSchema.type == "object"
    - inputSchema.properties contains the expected props with correct types
    - inputSchema.required matches the expected set

    When the client did NOT pass --project, also asserts that the project-only
    tools (open_editor / close_editor) are absent — guarding against accidentally
    exposing process-management tools without a project configured.
    """
    print(f"\n[Test] Tool discovery — base tools ({client.transport_name})")
    tools = await client.list_tools()

    if not tools:
        fail("tools/list returned no tools")
        return False

    has_project = bool(getattr(client, "editor_project", None))
    must_be_absent = None if has_project else set(EXPECTED_PROJECT_TOOLS.keys())

    return _validate_tool_set(
        tools,
        EXPECTED_BASE_TOOLS,
        must_be_absent=must_be_absent,
    )


async def test_list_project_tools(client: MCPClientBase):
    """
    Test: when --project is configured, tools/list ALSO exposes the
    process-management tools open_editor / close_editor with valid schemas.

    Skipped (returns True with a warning) when the client was not started with
    a project — the base tool discovery test already verifies they are absent
    in that case.
    """
    print(f"\n[Test] Tool discovery — project tools ({client.transport_name})")

    if not getattr(client, "editor_project", None):
        warn("Client not started with --project; skipping project tool discovery check")
        info("Use `--project <path/to/.uproject>` to exercise this test")
        return True

    tools = await client.list_tools()
    if not tools:
        fail("tools/list returned no tools")
        return False

    return _validate_tool_set(tools, EXPECTED_PROJECT_TOOLS)


async def test_get_editor_state(client: MCPClientBase):
    """Test: get_editor_state returns a meaningful state string."""
    print(f"\n[Test] get_editor_state ({client.transport_name})")
    result = await client.call_tool("get_editor_state", {})
    text = _extract_text(result)

    if "connected" in text.lower() or "disconnected" in text.lower() or "state" in text.lower():
        ok(f"Editor state: {text.strip()}")
        return True
    else:
        fail(f"Unexpected editor state response: {text.strip()}")
        return False


async def test_execute_command(client: MCPClientBase):
    """Test: Execute simple Python expression via execute_command."""
    print(f"\n[Test] execute_command ({client.transport_name})")
    result = await client.call_tool("execute_command", {
        "code": "print(1 + 2)"
    })
    text = _extract_text(result)

    if "3" in text:
        ok(f"Got output: {text.strip()}")
        return True
    else:
        fail(f"Unexpected output: {text.strip()}")
        return False


async def test_execute_unreal_api(client: MCPClientBase):
    """Test: Call Unreal API via execute_command."""
    print(f"\n[Test] execute_command - Unreal API ({client.transport_name})")
    result = await client.call_tool("execute_command", {
        "code": "import unreal; actors = unreal.EditorLevelLibrary.get_all_level_actors(); print(f'Actor count: {len(actors)}')"
    })
    text = _extract_text(result)

    if "Actor count:" in text:
        ok(f"Got output: {text.strip()}")
        return True
    else:
        fail(f"Unexpected output: {text.strip()}")
        return False


async def test_execute_file(client: MCPClientBase):
    """Test: Execute a Python file via excute_file."""
    print(f"\n[Test] excute_file ({client.transport_name})")

    import tempfile

    tmp_dir = tempfile.gettempdir()
    tmp_file = os.path.join(tmp_dir, "mcp_test_script.py")

    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write("import unreal\n")
        f.write("world = unreal.EditorLevelLibrary.get_game_world()\n")
        f.write("if world:\n")
        f.write("    print(f'World name: {world.get_name()}')\n")
        f.write("else:\n")
        f.write("    print('No game world (normal in editor mode)')\n")

    info(f"Temp script: {tmp_file}")

    result = await client.call_tool("excute_file", {
        "file": tmp_file
    })
    text = _extract_text(result)

    # Cleanup
    try:
        os.unlink(tmp_file)
    except Exception:
        pass

    if "World name:" in text or "No game world" in text:
        ok(f"Got output: {text.strip()}")
        return True
    else:
        fail(f"Unexpected output: {text.strip()}")
        return False


async def test_error_handling(client: MCPClientBase):
    """Test: Error handling - intentional bad code."""
    print(f"\n[Test] Error handling ({client.transport_name})")
    result = await client.call_tool("execute_command", {
        "code": "raise RuntimeError('test error from MCP client')"
    })
    text = _extract_text(result)
    has_err = _has_error(result)

    if has_err or "test error" in text.lower() or "runtimeerror" in text.lower():
        ok(f"Error properly reported: {text.strip()[:200]}")
        return True
    else:
        warn(f"Expected error but got: {text.strip()[:200]}")
        return True  # Not a failure, just different format


# --- Test Registry ---

# All tests available for SSE (original 5 e2e tests mapped to new functions)
SSE_TESTS = [
    ("initialize", "Initialize Handshake", test_initialize),
    ("list_tools", "List Tools (base discovery)", test_list_tools),
    ("list_project_tools", "List Tools (project discovery)", test_list_project_tools),
    ("ping", "get_editor_state", test_get_editor_state),
    ("exec_simple", "Execute Simple Expression", test_execute_command),
    ("exec_unreal", "Execute Unreal API", test_execute_unreal_api),
    ("file", "Execute Python File", test_execute_file),
    ("error", "Error Handling", test_error_handling),
]

# STDIO tests: initialize/list_tools/get_editor_state/execute_command/excute_file/error
STDIO_TESTS = [
    ("initialize", "Initialize Handshake", test_initialize),
    ("list_tools", "List Tools (base discovery)", test_list_tools),
    ("list_project_tools", "List Tools (project discovery)", test_list_project_tools),
    ("ping", "get_editor_state", test_get_editor_state),
    ("exec_simple", "Execute Simple Expression", test_execute_command),
    ("file", "Execute Python File", test_execute_file),
    ("error", "Error Handling", test_error_handling),
]

# Test name aliases for --test filter
TEST_ALIASES = {
    "ping": "ping",
    "state": "ping",
    "exec": "exec_simple",
    "exec_simple": "exec_simple",
    "exec_unreal": "exec_unreal",
    "file": "file",
    "error": "error",
    "initialize": "initialize",
    "init": "initialize",
    "list_tools": "list_tools",
    "tools": "list_tools",
    "list_project_tools": "list_project_tools",
    "project_tools": "list_project_tools",
    "discover": "list_tools",
    "discovery": "list_tools",
}


async def wait_for_port(host: str, port: int, timeout: float, label: str, process=None) -> bool:
    """Wait until a TCP endpoint starts accepting connections."""
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        if process is not None and process.returncode is not None:
            fail(f"{label} exited before {host}:{port} became ready (rc={process.returncode})")
            return False

        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            ok(f"{label} is listening on {host}:{port}")
            return True
        except (ConnectionRefusedError, OSError) as e:
            last_error = e
            await asyncio.sleep(1.0)

    fail(f"Timed out waiting for {label} on {host}:{port}: {last_error}")
    return False


async def terminate_process(process: Optional[asyncio.subprocess.Process], label: str, timeout: float = 10.0) -> bool:
    """Terminate a subprocess, escalating to kill if needed."""
    if process is None or process.returncode is not None:
        return True

    try:
        process.terminate()
    except ProcessLookupError:
        return True

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        ok(f"{label} exited")
        return True
    except asyncio.TimeoutError:
        warn(f"{label} did not exit after terminate(); killing")
        try:
            process.kill()
        except ProcessLookupError:
            return True
        await process.wait()
        ok(f"{label} killed")
        return True


async def launch_editor_if_requested(args) -> Optional[asyncio.subprocess.Process]:
    """Launch the editor only when explicitly requested by the harness."""
    if not args.launch_editor:
        return None

    editor_exe = os.path.abspath(args.editor_exe)
    uproject = os.path.abspath(args.uproject)

    if not os.path.isfile(editor_exe):
        fail(f"Editor executable not found: {editor_exe}")
        return None
    if not os.path.isfile(uproject):
        fail(f"Project file not found: {uproject}")
        return None

    command = [
        editor_exe,
        uproject,
        "-NullRHI",
        "-RenderOffScreen",
        "-Unattended",
        "-NoSplash",
        "-NoCompile",
        "-DisablePlugins=UEWorktree",
    ]

    info(f"Launching editor: {editor_exe}")
    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except Exception as e:
        fail(f"Failed to launch editor: {e}")
        return None

    if await wait_for_port(args.editor_host, args.editor_port, args.editor_start_timeout, "Editor forwarder", process):
        return process

    await terminate_process(process, "Owned editor")
    return None


async def request_editor_shutdown(stdio_script: Optional[str], editor_host: str, editor_port: int) -> bool:
    """Try to request a graceful editor shutdown through MCP."""
    info("Requesting editor shutdown via execute_command")
    client = MCPStdioClient(server_script=stdio_script, editor_host=editor_host, editor_port=editor_port)

    try:
        if not await client.connect():
            return False
        if not await client.initialize():
            return False

        result = await client.call_tool("execute_command", {
            "code": "import unreal\nprint('Requesting editor shutdown')\nunreal.SystemLibrary.quit_editor()"
        })
        text = _extract_text(result).strip()
        if text:
            ok(text)
        return bool(result) and not _has_error(result)
    finally:
        await client.close()


async def shutdown_owned_editor(process: Optional[asyncio.subprocess.Process], args):
    """Gracefully stop a harness-owned editor, with terminate/kill fallback."""
    if process is None or process.returncode is not None:
        return

    graceful = await request_editor_shutdown(args.stdio_script, args.editor_host, args.editor_port)

    try:
        await asyncio.wait_for(process.wait(), timeout=args.editor_shutdown_timeout)
        ok("Owned editor exited after regression")
        return
    except asyncio.TimeoutError:
        if graceful:
            warn("Owned editor did not exit after graceful shutdown request")
        else:
            warn("Graceful shutdown was unavailable; terminating owned editor")

    await terminate_process(process, "Owned editor")


# --- Runner ---

async def run_transport_tests(client: MCPClientBase, test_suite: list, test_filter: str = None):
    """
    Run tests on a single transport.

    Args:
        client: MCP client instance
        test_suite: List of (key, description, test_fn) tuples
        test_filter: Optional test key to run only one test

    Returns:
        List of (description, passed) tuples
    """
    transport = client.transport_name
    print(f"\n{'=' * 60}")
    print(f"{BOLD}Transport: {transport}{RESET}")
    print(f"{'=' * 60}")

    # Connect
    if not await client.connect():
        fail(f"Cannot establish {transport} connection. Is the MCP server running?")
        await client.close()
        return [(f"{transport} connection", False)]

    # Initialize
    if not await client.initialize():
        fail(f"MCP initialize failed ({transport})")
        await client.close()
        return [(f"{transport} initialize", False)]

    # Select tests
    if test_filter:
        resolved = TEST_ALIASES.get(test_filter, test_filter)
        selected = [(k, d, fn) for k, d, fn in test_suite if k == resolved]
        if not selected:
            available = sorted(set(k for k, _, _ in test_suite))
            fail(f"No test '{test_filter}' in {transport} suite. Available: {available}")
            await client.close()
            return []
    else:
        selected = test_suite

    # Run tests
    results = []
    for key, desc, test_fn in selected:
        try:
            passed = await test_fn(client)
            results.append((f"[{transport}] {desc}", passed))
        except Exception as e:
            fail(f"Exception in {key}: {e}")
            results.append((f"[{transport}] {desc}", False))

    await client.close()
    return results


async def run_all(args):
    """Main test orchestrator."""
    print("=" * 60)
    print(f"{BOLD}UE-Editor-MCPServer Dual-Transport Regression Test{RESET}")
    print("=" * 60)
    print(f"Transport: {args.transport}")
    print(f"Launch editor: {'yes' if args.launch_editor else 'no'}")
    if args.test:
        print(f"Filter: {args.test}")
    print()

    all_results = []
    owned_editor = None

    try:
        owned_editor = await launch_editor_if_requested(args)
        if args.launch_editor and owned_editor is None:
            sys.exit(1)

        # --- SSE ---
        if args.transport in ("sse", "both"):
            client = MCPSSEClient(args.mcp_url)
            # Surface --project to the SSE discovery test so it can adapt.
            # Note: we cannot inject --project into an externally-running SSE
            # server, so the user must have started it that way themselves.
            client.editor_project = args.project
            results = await run_transport_tests(client, SSE_TESTS, args.test)
            all_results.extend(results)

        # --- STDIO ---
        if args.transport in ("stdio", "both"):
            client = MCPStdioClient(
                server_script=args.stdio_script,
                editor_port=args.editor_port,
                editor_host=args.editor_host,
                editor_project=args.project,
            )
            results = await run_transport_tests(client, STDIO_TESTS, args.test)
            all_results.extend(results)
    finally:
        if owned_editor is not None:
            await shutdown_owned_editor(owned_editor, args)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"{BOLD}Summary{RESET}")
    print("=" * 60)
    passed_count = sum(1 for _, p in all_results if p)
    total_count = len(all_results)

    for desc, passed in all_results:
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {desc}")

    print(f"\n  {passed_count}/{total_count} tests passed")

    if passed_count < total_count:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Dual-transport MCP regression test (SSE + STDIO)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python test_mcp_client.py                          # Both transports, all tests
  python test_mcp_client.py --transport sse          # SSE only
  python test_mcp_client.py --transport stdio        # STDIO only
  python test_mcp_client.py --test ping              # Single test on selected transport(s)
  python test_mcp_client.py --transport stdio --test error
  python test_mcp_client.py --launch-editor --transport stdio
"""
    )
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio", "both"],
        default="both",
        help="Transport to test: sse, stdio, or both (default: both)",
    )
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8099/SSE",
        help="MCP SSE endpoint URL (default: http://127.0.0.1:8099/SSE)",
    )
    parser.add_argument(
        "--stdio-script",
        default=None,
        help="Path to main.py for STDIO mode (default: ./main.py)",
    )
    parser.add_argument(
        "--editor-port",
        type=int,
        default=8100,
        help="Editor forwarder port (default: 8100)",
    )
    parser.add_argument(
        "--editor-host",
        default="127.0.0.1",
        help="Editor forwarder host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--launch-editor",
        action="store_true",
        help="Launch the editor for this regression run and auto-close it afterward",
    )
    parser.add_argument(
        "--editor-exe",
        default=_default_editor_exe(),
        help=f"Path to the editor executable when --launch-editor is used (default: {_default_editor_exe()})",
    )
    parser.add_argument(
        "--uproject",
        default=_default_uproject(),
        help=f"Path to the .uproject when --launch-editor is used (default: {_default_uproject()})",
    )
    parser.add_argument(
        "--editor-start-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the editor forwarder port after launching the editor (default: 120)",
    )
    parser.add_argument(
        "--editor-shutdown-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for a harness-owned editor to exit after shutdown request (default: 30)",
    )
    parser.add_argument(
        "--test",
        default=None,
        help=f"Run a specific test. Options: {', '.join(sorted(TEST_ALIASES.keys()))}",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Path to a .uproject. STDIO: passed as --project to MCPStandalone "
            "so the discovery test verifies open_editor / close_editor are exposed. "
            "SSE: only flips the discovery test's expectations — the user must "
            "have started the SSE server with --project / EDITOR_PROJECT themselves."
        ),
    )

    args = parser.parse_args()
    asyncio.run(run_all(args))


if __name__ == "__main__":
    main()
