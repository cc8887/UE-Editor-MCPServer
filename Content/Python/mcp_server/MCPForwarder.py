"""
UE4 MCP Forwarder - 编辑器内转发服务器
功能：
1. 接收来自外部MCP进程的请求
2. 在编辑器主线程执行Python代码
3. 通过TCP连接状态让外部进程感知编辑器状态（连接断开=编辑器崩溃/关闭）

设计说明：
- 使用TCP连接状态来检测编辑器崩溃，正常情况下TCP连接不会主动断开
- 外部MCP进程通过检测TCP断连来判断编辑器是否崩溃
- 转发服务器完全由编辑器tick驱动，不阻塞主线程
"""

import json
import time
import socket
from typing import Optional, Dict, Any, List
from enum import Enum

# 导入通用代码执行器
try:
    from .MCPCore import CodeExecutor, ExecutionResult
except ImportError:
    from MCPCore import CodeExecutor, ExecutionResult


class ForwarderState(Enum):
    """转发器状态"""
    IDLE = "idle"
    EXECUTING = "executing"
    ERROR = "error"


class MCPForwarder:
    """
    MCP转发服务器 - 运行在UE编辑器内，由Tick驱动
    
    通信协议：
    - 使用长度前缀协议：4字节大端序长度 + JSON消息体
    - 消息类型：
      - ping/pong: 连接检测
      - execute: 执行Python代码
      - execute_file: 执行Python文件
      - result: 执行结果
    """
    
    # 默认配置
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8100
    
    def __init__(self, host: str = None, port: int = None):
        """
        初始化转发服务器
        
        Args:
            host: 监听地址，默认127.0.0.1
            port: 监听端口，默认8100
        """
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._state = ForwarderState.IDLE
        self._pending_requests: List[Dict[str, Any]] = []
        self._pending_responses: List[Dict[str, Any]] = []
        self._recv_buffer = b""
        self._is_running = False
        self._last_tick_time = time.time()
        
        # 日志函数（兼容UE4/UE5）
        self._log = self._get_log_function()
    
    def _get_log_function(self):
        """获取日志函数，兼容UE4/UE5"""
        try:
            from unreal import log
            return log
        except ImportError:
            return print
    
    def start(self):
        """
        启动转发服务器（非阻塞）
        创建监听socket，等待外部MCP进程连接
        """
        if self._is_running:
            self._log("MCPForwarder already running")
            return
        
        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # 设置为非阻塞模式
            self._server_socket.setblocking(False)
            self._server_socket.bind((self.host, self.port))
            self._server_socket.listen(1)
            self._is_running = True
            self._log(f"MCPForwarder started on {self.host}:{self.port}")
        except OSError as e:
            self._log(f"MCPForwarder start error (port may be in use): {e}")
            raise
        except Exception as e:
            self._log(f"MCPForwarder start error: {e}")
            raise
    
    def tick(self, delta_time: float):
        """
        由编辑器Tick调用的主循环
        
        处理流程：
        1. 接受新连接
        2. 接收数据
        3. 处理请求
        4. 发送响应
        
        Args:
            delta_time: 帧间隔时间（秒）
        """
        if not self._is_running:
            return
        
        self._last_tick_time = time.time()
        
        try:
            # 1. 处理新连接
            self._accept_connection()
            
            # 2. 接收数据
            self._receive_data()
            
            # 3. 处理请求队列中的请求
            self._process_requests()
            
            # 4. 发送响应
            self._send_responses()
            
        except Exception as e:
            self._log(f"MCPForwarder tick error: {e}")
    
    def _accept_connection(self):
        """
        接受新连接（非阻塞）
        只允许一个客户端连接，新连接会替换旧连接
        """
        if self._server_socket is None:
            return
        
        try:
            client, addr = self._server_socket.accept()
            
            # 如果已有连接，先关闭旧连接
            if self._client_socket is not None:
                self._log(f"MCPForwarder: Closing existing connection, new client from {addr}")
                self._close_client()
            
            # 设置新连接为非阻塞
            client.setblocking(False)
            # 启用 TCP keepalive（可选，帮助检测断连）
            client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            
            self._client_socket = client
            self._recv_buffer = b""
            self._log(f"MCPForwarder: Client connected from {addr}")
            
        except BlockingIOError:
            pass  # 没有新连接，正常情况
        except Exception as e:
            self._log(f"MCPForwarder accept error: {e}")
    
    def _receive_data(self):
        """
        接收数据（非阻塞）
        检测连接断开（外部进程可通过此机制感知编辑器状态）
        """
        if self._client_socket is None:
            return
        
        try:
            data = self._client_socket.recv(65536)
            if data:
                self._recv_buffer += data
                self._parse_messages()
            elif data == b"":
                # 连接正常关闭（对端主动断开）
                self._log("MCPForwarder: Client disconnected (normal close)")
                self._close_client()
        except BlockingIOError:
            pass  # 没有数据可读，正常情况
        except ConnectionResetError:
            # 连接被重置（对端异常断开）
            self._log("MCPForwarder: Connection reset by client")
            self._close_client()
        except ConnectionAbortedError:
            # 连接被中止
            self._log("MCPForwarder: Connection aborted")
            self._close_client()
        except OSError as e:
            self._log(f"MCPForwarder receive OS error: {e}")
            self._close_client()
        except Exception as e:
            self._log(f"MCPForwarder receive error: {e}")
            self._close_client()
    
    def _parse_messages(self):
        """
        解析消息
        协议：4字节大端序长度前缀 + JSON消息体
        """
        while len(self._recv_buffer) >= 4:
            # 读取消息长度（4字节大端序）
            msg_len = int.from_bytes(self._recv_buffer[:4], 'big')
            
            # 检查消息是否完整
            if len(self._recv_buffer) < 4 + msg_len:
                break  # 消息不完整，等待更多数据
            
            # 提取消息体
            msg_data = self._recv_buffer[4:4 + msg_len]
            self._recv_buffer = self._recv_buffer[4 + msg_len:]
            
            try:
                message = json.loads(msg_data.decode('utf-8'))
                self._pending_requests.append(message)
            except json.JSONDecodeError as e:
                self._log(f"MCPForwarder JSON decode error: {e}")
            except UnicodeDecodeError as e:
                self._log(f"MCPForwarder Unicode decode error: {e}")
    
    def _process_requests(self):
        """处理待处理的请求队列"""
        while self._pending_requests:
            request = self._pending_requests.pop(0)
            response = self._handle_request(request)
            if response is not None:
                self._pending_responses.append(response)
    
    def _handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理单个请求
        
        支持的请求类型：
        - ping: 连接检测
        - execute: 执行Python代码
        - execute_file: 执行Python文件
        - get_state: 获取当前状态
        
        Args:
            request: 请求字典
            
        Returns:
            响应字典，或None（如果不需要响应）
        """
        msg_type = request.get("type")
        request_id = request.get("id")
        
        if msg_type == "ping":
            # 连接检测响应
            return {
                "type": "pong",
                "id": request_id,
                "timestamp": time.time(),
                "state": self._state.value
            }
        
        elif msg_type == "execute":
            # 执行Python代码
            code = request.get("code", "")
            return self._execute_code(request_id, code)
        
        elif msg_type == "execute_file":
            # 执行Python文件
            file_path = request.get("file", "")
            return self._execute_file(request_id, file_path)
        
        elif msg_type == "get_state":
            # 获取当前状态
            return {
                "type": "state",
                "id": request_id,
                "state": self._state.value,
                "timestamp": time.time()
            }
        
        else:
            # 未知消息类型
            return {
                "type": "error",
                "id": request_id,
                "error": f"Unknown message type: {msg_type}"
            }
    
    def _execute_code(self, request_id: str, code: str) -> Dict[str, Any]:
        """
        在编辑器主线程执行Python代码
        
        Args:
            request_id: 请求ID
            code: 要执行的Python代码
            
        Returns:
            执行结果字典
        """
        self._state = ForwarderState.EXECUTING
        
        # 使用通用CodeExecutor执行代码
        result = CodeExecutor.execute_code(code)
        
        self._state = ForwarderState.IDLE
        
        return {
            "type": "result",
            "id": request_id,
            "success": result.success,
            "output": result.output if result.success else None,
            "error": result.error if not result.success else None,
            "logs": result.logs if result.logs else None
        }
    
    def _execute_file(self, request_id: str, file_path: str) -> Dict[str, Any]:
        """
        执行Python文件
        
        Args:
            request_id: 请求ID
            file_path: Python文件路径
            
        Returns:
            执行结果字典
        """
        self._state = ForwarderState.EXECUTING
        
        # 使用通用CodeExecutor执行文件
        result = CodeExecutor.execute_file(file_path)
        
        self._state = ForwarderState.IDLE
        
        return {
            "type": "result",
            "id": request_id,
            "success": result.success,
            "output": result.output if result.success else None,
            "error": result.error if not result.success else None,
            "logs": result.logs if result.logs else None
        }
    
    def _send_responses(self):
        """发送待发送的响应"""
        if self._client_socket is None:
            self._pending_responses.clear()
            return
        
        while self._pending_responses:
            response = self._pending_responses.pop(0)
            try:
                data = json.dumps(response, ensure_ascii=False).encode('utf-8')
                # 添加长度前缀
                length_prefix = len(data).to_bytes(4, 'big')
                self._client_socket.sendall(length_prefix + data)
            except BlockingIOError:
                # 发送缓冲区满，放回队列
                self._pending_responses.insert(0, response)
                break
            except BrokenPipeError:
                self._log("MCPForwarder: Broken pipe during send")
                self._close_client()
                break
            except ConnectionResetError:
                self._log("MCPForwarder: Connection reset during send")
                self._close_client()
                break
            except Exception as e:
                self._log(f"MCPForwarder send error: {e}")
                self._close_client()
                break
    
    def _close_client(self):
        """关闭客户端连接"""
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
            self._client_socket = None
        self._recv_buffer = b""
        self._pending_requests.clear()
        self._pending_responses.clear()
        self._state = ForwarderState.IDLE
    
    def stop(self):
        """停止转发服务器"""
        self._is_running = False
        self._close_client()
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None
        self._log("MCPForwarder stopped")
    
    def destroy(self):
        """销毁资源（别名，与Manager接口保持一致）"""
        self.stop()
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running
    
    @property
    def is_connected(self) -> bool:
        """是否有客户端连接"""
        return self._client_socket is not None
    
    @property
    def state(self) -> ForwarderState:
        """当前状态"""
        return self._state
