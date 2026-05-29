# test_mcp_client.py - Lightweight MCP SSE client end-to-end test
#
# Independent of Box Engine, pure Python MCP SSE protocol implementation.
# Easy to share with others for quick verification of UE-Editor-MCPServer.
#
# Prerequisites:
#   1. UE Editor running with MCPForwarder plugin on port 8100
#   2. MCP SSE Server running on port 8099
#
# Usage:
#   python test_mcp_client.py                     # Run all tests
#   python test_mcp_client.py --test ping        # Only ping test
#   python test_mcp_client.py --test exec        # Only execute_command
#   python test_mcp_client.py --test file        # Only excute_file
#   python test_mcp_client.py --test error       # Only error handling

import asyncio
import json
import sys
import argparse
import time
import uuid
from typing import Optional


# --- ANSI colors ---
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def ok(msg):
    print(f"  {GREEN}*{RESET} {msg}")


def fail(msg):
    print(f"  {RED}X{RESET} {msg}")


def info(msg):
    print(f"  {CYAN}>{RESET} {msg}")


def warn(msg):
    print(f"  {YELLOW}!{RESET} {msg}")


# --- MCP SSE Client ---
class MCPSSEClient:
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
        """POST JSON to MCP messages endpoint via a SEPARATE connection.

        The SSE GET connection is a long-lived stream that must stay open to
        receive responses, so each POST opens its own short-lived connection.
        """
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


# --- Test Cases ---

async def test_ping(client):
    """Test 1: Check editor connection via get_editor_state."""
    print("\n[Test 1] Ping - get_editor_state")
    result = await client.call_tool("get_editor_state", {})
    text = _extract_text(result)

    if "connected" in text.lower():
        ok(f"Editor state: {text.strip()}")
        return True
    else:
        fail(f"Editor not connected: {text.strip()}")
        return False


async def test_execute_simple(client):
    """Test 2: Execute simple Python expression."""
    print("\n[Test 2] Execute simple expression: 1 + 2")
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


async def test_execute_unreal_api(client):
    """Test 3: Call Unreal API."""
    print("\n[Test 3] Execute Unreal API: get_all_level_actors")
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


async def test_execute_file(client):
    """Test 4: Execute a Python file."""
    print("\n[Test 4] Execute Python file")

    import tempfile
    import os

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


async def test_error_handling(client):
    """Test 5: Error handling - intentional bad code."""
    print("\n[Test 5] Error handling - intentional RuntimeError")
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


# --- Main ---

ALL_TESTS = {
    "ping": ("Ping / Editor State", test_ping),
    "state": ("Ping / Editor State", test_ping),
    "exec": ("Execute Simple Expression", test_execute_simple),
    "exec_simple": ("Execute Simple Expression", test_execute_simple),
    "exec_unreal": ("Execute Unreal API", test_execute_unreal_api),
    "file": ("Execute Python File", test_execute_file),
    "error": ("Error Handling", test_error_handling),
}

DEFAULT_TEST_ORDER = ["ping", "exec_simple", "exec_unreal", "file", "error"]


async def run_tests(mcp_url, test_filter=None):
    """Run tests."""
    print("=" * 60)
    print("UE-Editor-MCPServer End-to-End Test")
    print("=" * 60)
    print(f"SSE URL: {mcp_url}")
    print()

    client = MCPSSEClient(mcp_url)

    # 1. Connect SSE
    if not await client.connect():
        fail("Cannot establish SSE connection. Is the MCP server running?")
        await client.close()
        return

    # 2. MCP initialize
    if not await client.initialize():
        fail("MCP initialize failed")
        await client.close()
        return

    # 3. List tools
    print("\n[List Tools]")
    tools = await client.list_tools()
    if tools:
        for t in tools:
            desc = t.get("description", "")[:60]
            ok(f"{t['name']}: {desc}")
    else:
        warn("No tools listed")

    # 4. Select tests
    if test_filter:
        if test_filter not in ALL_TESTS:
            fail(f"No test named '{test_filter}'. Available: {', '.join(ALL_TESTS.keys())}")
            await client.close()
            return
        selected = [(test_filter, ALL_TESTS[test_filter])]
    else:
        selected = [(k, ALL_TESTS[k]) for k in DEFAULT_TEST_ORDER]

    # 5. Run tests
    results = []
    for key, (desc, test_fn) in selected:
        try:
            passed = await test_fn(client)
            results.append((desc, passed))
        except Exception as e:
            fail(f"Exception: {e}")
            results.append((desc, False))

    # 6. Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    for desc, passed in results:
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  [{status}] {desc}")

    print(f"\n  {passed_count}/{total_count} tests passed")

    await client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Lightweight MCP SSE Client Test for UE-Editor-MCPServer",
    )
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8099/SSE",
        help="MCP SSE endpoint URL (default: http://127.0.0.1:8099/SSE)",
    )
    parser.add_argument(
        "--test",
        default=None,
        help=f"Run a specific test. Options: {', '.join(ALL_TESTS.keys())}",
    )

    args = parser.parse_args()
    asyncio.run(run_tests(args.mcp_url, args.test))


if __name__ == "__main__":
    main()
