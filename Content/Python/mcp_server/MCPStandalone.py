"""
MCPStandalone - 独立进程MCP服务器
功能：
1. 运行完整的MCP服务（SSE端点）
2. 连接到UE编辑器内的转发服务器
3. 通过TCP连接状态监控编辑器健康状态（连接断开=编辑器崩溃/关闭）
4. 自动重连机制

设计说明：
- 使用TCP连接状态来检测编辑器崩溃，不依赖心跳超时
- TCP连接断开即认为编辑器已崩溃或关闭
- 支持自动重连，编辑器重启后自动恢复连接

使用方法：
    python MCPStandalone.py --mcp-port 8099 --editor-port 8100
"""

import asyncio
import json
import time
import socket
import sys
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
from dataclasses import dataclass

# 支持作为模块导入和独立脚本运行
try:
    from .MCPCore import (
        MCP_AVAILABLE, MCP_IMPORT_ERRORS,
        STARLETTE_AVAILABLE, STARLETTE_IMPORT_ERRORS,
        types, Server, SseServerTransport,
        uvicorn, Starlette, Mount, Route,
        ExecutionResult,
        ToolDefinition, TOOL_EXECUTE_COMMAND, TOOL_EXECUTE_FILE, TOOL_GET_EDITOR_STATE,
        get_mcp_tools
    )
    from .MCPConfig import load_config, get_mcp_port, get_mcp_host, get_editor_port, get_editor_host
except ImportError:
    from MCPCore import (
        MCP_AVAILABLE, MCP_IMPORT_ERRORS,
        STARLETTE_AVAILABLE, STARLETTE_IMPORT_ERRORS,
        types, Server, SseServerTransport,
        uvicorn, Starlette, Mount, Route,
        ExecutionResult,
        ToolDefinition, TOOL_EXECUTE_COMMAND, TOOL_EXECUTE_FILE, TOOL_GET_EDITOR_STATE,
        get_mcp_tools
    )
    from MCPConfig import load_config, get_mcp_port, get_mcp_host, get_editor_port, get_editor_host


class EditorState(Enum):
    """编辑器连接状态"""
    DISCONNECTED = "disconnected"  # 未连接
    CONNECTING = "connecting"      # 正在连接
    CONNECTED = "connected"        # 已连接
    EXECUTING = "executing"        # 正在执行请求


@dataclass
class ConnectionConfig:
    """连接配置"""
    reconnect_interval: float = 2.0      # 重连间隔（秒）
    connect_timeout: float = 5.0         # 连接超时（秒）
    request_timeout: float = 60.0        # 请求超时（秒）
    recv_buffer_size: int = 65536        # 接收缓冲区大小


class EditorConnection:
    """
    与UE编辑器的连接管理
    
    通过TCP连接状态检测编辑器崩溃：
    - 正常情况下TCP连接保持
    - TCP断连即认为编辑器崩溃或关闭
    - 支持自动重连
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8100, 
                 config: ConnectionConfig = None):
        """
        初始化编辑器连接
        
        Args:
            host: 编辑器转发服务器地址
            port: 编辑器转发服务器端口
            config: 连接配置
        """
        self.host = host
        self.port = port
        self.config = config or ConnectionConfig()
        
        self._socket: Optional[socket.socket] = None
        self._state = EditorState.DISCONNECTED
        self._request_counter = 0
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._recv_buffer = b""
        self._lock = asyncio.Lock()
        self._receive_task: Optional[asyncio.Task] = None
        
        # 状态变化回调
        self.on_state_change: Optional[Callable[[EditorState, EditorState], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
    
    @property
    def state(self) -> EditorState:
        """当前连接状态"""
        return self._state
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._state in (EditorState.CONNECTED, EditorState.EXECUTING)
    
    def _set_state(self, new_state: EditorState):
        """设置状态并触发回调"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            print(f"[EditorConnection] State: {old_state.value} -> {new_state.value}")
            
            if self.on_state_change:
                try:
                    self.on_state_change(old_state, new_state)
                except Exception as e:
                    print(f"[EditorConnection] State change callback error: {e}")
            
            if new_state == EditorState.DISCONNECTED and self.on_disconnected:
                try:
                    self.on_disconnected()
                except Exception as e:
                    print(f"[EditorConnection] Disconnected callback error: {e}")
    
    async def connect(self) -> bool:
        """
        连接到编辑器转发服务器
        
        Returns:
            连接是否成功
        """
        if self._socket:
            return True
        
        self._set_state(EditorState.CONNECTING)
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setblocking(False)
            
            loop = asyncio.get_event_loop()
            try:
                await asyncio.wait_for(
                    loop.sock_connect(self._socket, (self.host, self.port)),
                    timeout=self.config.connect_timeout
                )
            except asyncio.TimeoutError:
                print(f"[EditorConnection] Connection timeout to {self.host}:{self.port}")
                self._close_socket()
                self._set_state(EditorState.DISCONNECTED)
                return False
            except ConnectionRefusedError:
                print(f"[EditorConnection] Connection refused by {self.host}:{self.port}")
                self._close_socket()
                self._set_state(EditorState.DISCONNECTED)
                return False
            
            self._recv_buffer = b""
            self._set_state(EditorState.CONNECTED)
            print(f"[EditorConnection] Connected to editor at {self.host}:{self.port}")
            
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            return True
            
        except Exception as e:
            print(f"[EditorConnection] Connection failed: {e}")
            self._close_socket()
            self._set_state(EditorState.DISCONNECTED)
            return False
    
    def _close_socket(self):
        """关闭socket"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
    
    def disconnect(self):
        """主动断开连接"""
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            self._receive_task = None
        
        self._close_socket()
        
        for request_id, future in self._pending_requests.items():
            if not future.done():
                future.set_exception(ConnectionError("Disconnected from editor"))
        self._pending_requests.clear()
        
        self._recv_buffer = b""
        self._set_state(EditorState.DISCONNECTED)
    
    async def _receive_loop(self):
        """接收数据循环"""
        loop = asyncio.get_event_loop()
        
        while self._socket:
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(self._socket, self.config.recv_buffer_size),
                    timeout=1.0
                )
                
                if data:
                    self._recv_buffer += data
                    await self._parse_messages()
                elif data == b"":
                    print("[EditorConnection] TCP connection closed - Editor disconnected or crashed")
                    self.disconnect()
                    break
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except ConnectionResetError:
                print("[EditorConnection] Connection reset - Editor crashed")
                self.disconnect()
                break
            except ConnectionAbortedError:
                print("[EditorConnection] Connection aborted - Editor terminated")
                self.disconnect()
                break
            except OSError as e:
                print(f"[EditorConnection] OS error: {e}")
                self.disconnect()
                break
            except Exception as e:
                print(f"[EditorConnection] Receive error: {e}")
                self.disconnect()
                break
    
    async def _parse_messages(self):
        """解析接收到的消息"""
        while len(self._recv_buffer) >= 4:
            msg_len = int.from_bytes(self._recv_buffer[:4], 'big')
            
            if len(self._recv_buffer) < 4 + msg_len:
                break
            
            msg_data = self._recv_buffer[4:4 + msg_len]
            self._recv_buffer = self._recv_buffer[4 + msg_len:]
            
            try:
                message = json.loads(msg_data.decode('utf-8'))
                await self._handle_message(message)
            except json.JSONDecodeError as e:
                print(f"[EditorConnection] JSON decode error: {e}")
    
    async def _handle_message(self, message: Dict[str, Any]):
        """处理接收到的消息"""
        request_id = message.get("id")
        
        if request_id and request_id in self._pending_requests:
            future = self._pending_requests.pop(request_id)
            if not future.done():
                future.set_result(message)
            
            if self._state == EditorState.EXECUTING:
                self._set_state(EditorState.CONNECTED)
    
    async def send_request(self, request: Dict[str, Any], 
                          timeout: float = None) -> Dict[str, Any]:
        """
        发送请求并等待响应
        
        Args:
            request: 请求字典
            timeout: 超时时间（秒）
            
        Returns:
            响应字典
        """
        if not self._socket:
            raise ConnectionError("Not connected to editor")
        
        timeout = timeout or self.config.request_timeout
        
        async with self._lock:
            self._request_counter += 1
            request_id = f"req_{self._request_counter}_{int(time.time() * 1000)}"
            request["id"] = request_id
            
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[request_id] = future
            
            if request.get("type") in ("execute", "execute_file"):
                self._set_state(EditorState.EXECUTING)
            
            try:
                data = json.dumps(request, ensure_ascii=False).encode('utf-8')
                length_prefix = len(data).to_bytes(4, 'big')
                
                loop = asyncio.get_event_loop()
                await loop.sock_sendall(self._socket, length_prefix + data)
                
                response = await asyncio.wait_for(future, timeout=timeout)
                return response
                
            except asyncio.TimeoutError:
                self._pending_requests.pop(request_id, None)
                if self._state == EditorState.EXECUTING:
                    self._set_state(EditorState.CONNECTED)
                raise TimeoutError(f"Request {request_id} timed out after {timeout}s")
            except Exception as e:
                self._pending_requests.pop(request_id, None)
                if self._state == EditorState.EXECUTING:
                    self._set_state(EditorState.CONNECTED)
                raise
    
    async def ping(self, timeout: float = 5.0) -> bool:
        """发送ping检测连接"""
        try:
            response = await self.send_request({"type": "ping"}, timeout=timeout)
            return response.get("type") == "pong"
        except Exception:
            return False
    
    async def execute_code(self, code: str, timeout: float = None) -> Dict[str, Any]:
        """执行Python代码"""
        return await self.send_request({
            "type": "execute",
            "code": code
        }, timeout=timeout)
    
    async def execute_file(self, file_path: str, timeout: float = None) -> Dict[str, Any]:
        """执行Python文件"""
        return await self.send_request({
            "type": "execute_file",
            "file": file_path
        }, timeout=timeout)


class MCPStandaloneServer:
    """
    独立MCP服务器
    
    功能：
    1. 提供MCP SSE端点供外部客户端连接
    2. 将请求转发到UE编辑器执行
    3. 自动管理与编辑器的连接（重连机制）
    """
    
    # 支持的工具列表
    TOOLS = [TOOL_EXECUTE_COMMAND, TOOL_EXECUTE_FILE, TOOL_GET_EDITOR_STATE]
    
    def __init__(self, 
                 mcp_host: str = "127.0.0.1", 
                 mcp_port: int = 8099,
                 editor_host: str = "127.0.0.1",
                 editor_port: int = 8100):
        """
        初始化MCP服务器
        
        Args:
            mcp_host: MCP服务监听地址
            mcp_port: MCP服务监听端口
            editor_host: 编辑器转发服务器地址
            editor_port: 编辑器转发服务器端口
        """
        self.mcp_host = mcp_host
        self.mcp_port = mcp_port
        
        self.editor_connection = EditorConnection(editor_host, editor_port)
        self.editor_connection.on_state_change = self._on_editor_state_change
        self.editor_connection.on_disconnected = self._on_editor_disconnected
        
        self._tasks: List[asyncio.Task] = []
        self._running = False
        self._reconnect_event = asyncio.Event()
    
    def _on_editor_state_change(self, old_state: EditorState, new_state: EditorState):
        """编辑器状态变化回调"""
        if new_state == EditorState.DISCONNECTED:
            print("[MCPServer] WARNING: Editor disconnected (crashed or closed)")
        elif new_state == EditorState.CONNECTED:
            print("[MCPServer] Editor connected and ready")
    
    def _on_editor_disconnected(self):
        """编辑器断连回调，触发重连"""
        if self._running:
            self._reconnect_event.set()
    
    async def _reconnect_loop(self):
        """重连循环"""
        while self._running:
            try:
                await asyncio.wait_for(self._reconnect_event.wait(), timeout=1.0)
                self._reconnect_event.clear()
            except asyncio.TimeoutError:
                pass
            
            if not self.editor_connection.is_connected:
                print("[MCPServer] Attempting to connect to editor...")
                connected = await self.editor_connection.connect()
                
                if not connected:
                    print(f"[MCPServer] Connection failed, retrying in {self.editor_connection.config.reconnect_interval}s...")
                    await asyncio.sleep(self.editor_connection.config.reconnect_interval)
    
    async def _handle_tool_call(self, name: str, arguments: dict) -> ExecutionResult:
        """
        处理工具调用
        
        Args:
            name: 工具名称
            arguments: 工具参数
            
        Returns:
            ExecutionResult 执行结果
        """
        # 检查编辑器连接状态
        if not self.editor_connection.is_connected:
            return ExecutionResult(
                success=False,
                error="Editor not connected. Please ensure Unreal Editor is running with the MCP Forwarder plugin.\n\n"
                      "The editor may have crashed or been closed. The server will automatically reconnect when the editor restarts."
            )
        
        try:
            if name == "execute_command":
                code = arguments.get('code', '')
                result = await self.editor_connection.execute_code(code)
                return self._parse_editor_response(result)
                
            elif name == "excute_file":
                file_path = arguments.get('file', '')
                result = await self.editor_connection.execute_file(file_path)
                return self._parse_editor_response(result)
            
            elif name == "get_editor_state":
                state = self.editor_connection.state.value
                return ExecutionResult(
                    success=True,
                    output=f"Editor connection state: {state}"
                )
            
            else:
                return ExecutionResult(success=False, error=f"Unknown tool: {name}")
                
        except TimeoutError as e:
            return ExecutionResult(
                success=False,
                error=f"Request timed out. The editor may be busy or processing a long operation.\n\nDetails: {e}"
            )
        except ConnectionError as e:
            return ExecutionResult(
                success=False,
                error=f"Connection lost to editor. The editor may have crashed.\n\nDetails: {e}"
            )
        except Exception as e:
            return ExecutionResult(success=False, error=str(e))
    
    def _parse_editor_response(self, result: Dict[str, Any]) -> ExecutionResult:
        """解析编辑器响应"""
        if result.get('success'):
            return ExecutionResult(
                success=True,
                output=result.get('output', 'Execution completed.'),
                logs=result.get('logs', '')
            )
        else:
            return ExecutionResult(
                success=False,
                error=result.get('error', 'Unknown error'),
                logs=result.get('logs', '')
            )
    
    async def run(self):
        """运行MCP服务器"""
        if not MCP_AVAILABLE:
            print("ERROR: MCP library not available")
            print("Please install: pip install mcp")
            if MCP_IMPORT_ERRORS:
                print("\nDetailed import errors:")
                for error in MCP_IMPORT_ERRORS:
                    print(f"  - {error}")
            return
        
        if not STARLETTE_AVAILABLE:
            print("ERROR: Starlette/Uvicorn not available")
            print("Please install: pip install uvicorn starlette")
            if STARLETTE_IMPORT_ERRORS:
                print("\nDetailed import errors:")
                for error in STARLETTE_IMPORT_ERRORS:
                    print(f"  - {error}")
            return
        
        self._running = True
        
        # 初始化MCP应用
        mcp_app = Server("UE-MCP-Standalone")
        sse = SseServerTransport("/messages/")
        
        # 保存self引用供闭包使用
        server_self = self
        
        @mcp_app.call_tool()
        async def call_tools(name: str, arguments: dict) -> list:
            print(f"[MCPServer] Tool call: {name}, args: {arguments}")
            result = await server_self._handle_tool_call(name, arguments)
            return result.to_mcp_content()
        
        @mcp_app.list_tools()
        async def list_tools() -> list:
            return get_mcp_tools(self.TOOLS)
        
        async def handle_sse(request):
            print("[MCPServer] SSE connection starting")
            initialization_options = mcp_app.create_initialization_options()
            
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                print("[MCPServer] SSE connected")
                try:
                    await mcp_app.run(
                        streams[0],
                        streams[1],
                        initialization_options,
                    )
                except Exception as e:
                    print(f"[MCPServer] MCP server error: {e}")
                    raise
        
        web_app = Starlette(
            routes=[
                Route("/SSE", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )
        
        # 启动重连循环
        self._tasks.append(asyncio.create_task(self._reconnect_loop()))
        
        # 尝试初始连接
        print("[MCPServer] Attempting initial connection to editor...")
        await self.editor_connection.connect()
        
        # 启动HTTP服务器
        config = uvicorn.Config(
            web_app, 
            host=self.mcp_host, 
            port=self.mcp_port, 
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        print(f"[MCPServer] MCP Server starting on http://{self.mcp_host}:{self.mcp_port}")
        print(f"[MCPServer] SSE endpoint: http://{self.mcp_host}:{self.mcp_port}/SSE")
        
        try:
            await server.serve()
        finally:
            await self.stop()
    
    async def stop(self):
        """停止服务器"""
        print("[MCPServer] Stopping...")
        self._running = False
        
        self.editor_connection.disconnect()
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._tasks.clear()
        print("[MCPServer] Stopped")


def main():
    """主函数 - 命令行入口"""
    import argparse
    
    # 先加载配置获取默认值
    config = load_config()
    
    parser = argparse.ArgumentParser(
        description='MCP Standalone Server for Unreal Engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python MCPStandalone.py
  python MCPStandalone.py --mcp-port 8099 --editor-port 8100
  python MCPStandalone.py --mcp-host 0.0.0.0 --mcp-port 8099

Configuration:
  Port settings can be configured via:
  1. Command line arguments (highest priority)
  2. Environment variables (MCP_PORT, MCP_HOST, EDITOR_PORT, EDITOR_HOST)
  3. .env file in the plugin root directory
  4. Default values

Note:
  This server connects to a UE Editor running the MCPForwarder plugin.
  The TCP connection state is used to detect editor crashes.
  When the editor crashes or closes, the TCP connection will be dropped,
  and this server will automatically attempt to reconnect.
        """
    )
    parser.add_argument('--mcp-host', default=None, 
                        help=f'MCP server listen host (default: {config["mcp_host"]})')
    parser.add_argument('--mcp-port', type=int, default=None, 
                        help=f'MCP server listen port (default: {config["mcp_port"]})')
    parser.add_argument('--editor-host', default=None, 
                        help=f'Editor forwarder host (default: {config["editor_host"]})')
    parser.add_argument('--editor-port', type=int, default=None, 
                        help=f'Editor forwarder port (default: {config["editor_port"]})')
    
    args = parser.parse_args()
    
    # 使用命令行参数覆盖配置文件的值
    mcp_host = args.mcp_host if args.mcp_host is not None else config["mcp_host"]
    mcp_port = args.mcp_port if args.mcp_port is not None else config["mcp_port"]
    editor_host = args.editor_host if args.editor_host is not None else config["editor_host"]
    editor_port = args.editor_port if args.editor_port is not None else config["editor_port"]
    
    print("=" * 60)
    print("MCP Standalone Server for Unreal Engine")
    print("=" * 60)
    print(f"MCP Server: {mcp_host}:{mcp_port}")
    print(f"Editor Forwarder: {editor_host}:{editor_port}")
    print("=" * 60)
    print()
    print("Connection detection: TCP connection state")
    print("- TCP connected = Editor running")
    print("- TCP disconnected = Editor crashed/closed")
    print("- Automatic reconnection enabled")
    print()
    
    server = MCPStandaloneServer(
        mcp_host=mcp_host,
        mcp_port=mcp_port,
        editor_host=editor_host,
        editor_port=editor_port
    )
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\n[MCPServer] Interrupted by user")


if __name__ == "__main__":
    main()
