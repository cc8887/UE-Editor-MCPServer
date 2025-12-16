"""
MCPCore - MCP公共核心模块

提供MCP Server和MCPStandalone共用的功能：
1. MCP依赖导入和检查
2. 工具定义
3. 执行结果数据类

注意：此模块不依赖unreal包，可在编辑器外独立使用
"""

from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

# ============================================================================
# 依赖导入检查
# ============================================================================

def try_imports(imports: list, install_hint: str, silent: bool = False) -> Tuple[bool, list, dict]:
    """
    尝试导入多个模块，返回 (是否全部成功, 错误列表, 导入结果字典)
    
    Args:
        imports: 导入配置列表，每项为 (模块名, 导入语句, 变量名列表)
        install_hint: 安装提示信息
        silent: 是否静默模式（不输出警告）
    
    Returns:
        (all_success, errors, modules)
    """
    errors = []
    modules = {}
    
    for module_name, import_stmt, var_names in imports:
        try:
            exec(import_stmt, modules)
        except ImportError as e:
            errors.append(f"{module_name}: {e}")
            for var_name in var_names:
                modules[var_name] = None
    
    all_success = len(errors) == 0
    
    # 仅在非静默模式下输出警告
    # 注意：UE4模式下这些库不可用是正常的
    if not all_success and not silent:
        print(f"Warning: {install_hint}")
        for error in errors:
            print(f"  - Import error: {error}")
    
    return all_success, errors, modules


# MCP 库导入（静默模式，UE4下不可用是正常的）
MCP_IMPORTS = [
    ("mcp.types", "import mcp.types as types", ["types"]),
    ("mcp.server.lowlevel", "from mcp.server.lowlevel import Server", ["Server"]),
    ("mcp.server.sse", "from mcp.server.sse import SseServerTransport", ["SseServerTransport"]),
]

MCP_AVAILABLE, MCP_IMPORT_ERRORS, _mcp_modules = try_imports(
    MCP_IMPORTS, 
    "MCP library not available. Install with: pip install mcp",
    silent=True  # 静默模式，避免UE4下输出不必要的警告
)

types = _mcp_modules.get("types")
Server = _mcp_modules.get("Server")
SseServerTransport = _mcp_modules.get("SseServerTransport")


# HTTP 服务器依赖导入（静默模式，UE4下不可用是正常的）
HTTP_IMPORTS = [
    ("uvicorn", "import uvicorn", ["uvicorn"]),
    ("starlette.applications", "from starlette.applications import Starlette", ["Starlette"]),
    ("starlette.routing", "from starlette.routing import Mount, Route", ["Mount", "Route"]),
]

STARLETTE_AVAILABLE, STARLETTE_IMPORT_ERRORS, _http_modules = try_imports(
    HTTP_IMPORTS,
    "Starlette/Uvicorn not available. Install with: pip install uvicorn starlette",
    silent=True  # 静默模式，避免UE4下输出不必要的警告
)

uvicorn = _http_modules.get("uvicorn")
Starlette = _http_modules.get("Starlette")
Mount = _http_modules.get("Mount")
Route = _http_modules.get("Route")


# ============================================================================
# 工具定义
# ============================================================================

@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    required: List[str] = None
    
    def to_mcp_tool(self):
        """转换为MCP Tool对象"""
        if types is None:
            return None
        
        schema = self.input_schema.copy()
        if self.required:
            schema["required"] = self.required
            
        return types.Tool(
            name=self.name,
            description=self.description,
            inputSchema=schema
        )


# 预定义的工具
TOOL_EXECUTE_COMMAND = ToolDefinition(
    name="execute_command",
    description="Execute Python code in Unreal Engine editor. The code runs in the editor's main thread.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute in the editor"
            }
        }
    },
    required=["code"]
)

TOOL_EXECUTE_FILE = ToolDefinition(
    name="excute_file",  # 保持原有拼写以兼容
    description="Execute a Python script file in Unreal Engine editor.",
    input_schema={
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "Absolute path to the Python script file"
            }
        }
    },
    required=["file"]
)

TOOL_GET_EDITOR_STATE = ToolDefinition(
    name="get_editor_state",
    description="Get the current connection state with Unreal Editor.",
    input_schema={
        "type": "object",
        "properties": {}
    }
)

# 默认工具列表
DEFAULT_TOOLS = [TOOL_EXECUTE_COMMAND, TOOL_EXECUTE_FILE]


def get_mcp_tools(tool_definitions: List[ToolDefinition] = None) -> list:
    """
    获取MCP Tool对象列表
    
    Args:
        tool_definitions: 工具定义列表，默认使用DEFAULT_TOOLS
        
    Returns:
        MCP Tool对象列表
    """
    if types is None:
        return []
    
    tools = tool_definitions or DEFAULT_TOOLS
    return [t.to_mcp_tool() for t in tools if t.to_mcp_tool() is not None]


# ============================================================================
# 代码执行结果
# ============================================================================

@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    logs: str = ""
    
    def to_text(self) -> str:
        """转换为文本输出"""
        if self.success:
            text = self.output or "Execution completed successfully."
        else:
            text = f"Error: {self.error}" if self.error else "Execution failed."
        
        if self.logs:
            text += f"\n\nCaptured Logs:\n{self.logs}"
        
        return text
    
    def to_mcp_content(self) -> list:
        """转换为MCP TextContent列表"""
        if types is None:
            return []
        return [types.TextContent(type="text", text=self.to_text())]


# ============================================================================
# MCP应用构建器
# ============================================================================

# ============================================================================
# 代码执行器（通用版本，支持编辑器内和独立进程）
# ============================================================================

class CodeExecutor:
    """
    代码执行器 - 执行Python代码
    
    提供日志捕获功能（仅在编辑器内可用）
    此类可在编辑器内和独立进程中使用
    """
    
    @staticmethod
    def _get_log_capture():
        """获取日志捕获模块（仅在编辑器内可用）"""
        try:
            import unreal
            if hasattr(unreal, 'MCPLogCaptureBlueprintLibrary'):
                return unreal.MCPLogCaptureBlueprintLibrary
        except (ImportError, AttributeError):
            pass
        return None
    
    @staticmethod
    def _enable_log_capture():
        """启用日志捕获"""
        log_capture = CodeExecutor._get_log_capture()
        if log_capture:
            log_capture.clear_captured_logs()
            log_capture.enable_log_capture(True)
            return True
        return False
    
    @staticmethod
    def _disable_log_capture() -> str:
        """禁用日志捕获并返回捕获的日志"""
        log_capture = CodeExecutor._get_log_capture()
        if log_capture:
            logs = log_capture.get_captured_logs()
            log_capture.disable_log_capture()
            return logs or ""
        return ""
    
    @classmethod
    def execute_code(cls, code: str, exec_globals: dict = None) -> ExecutionResult:
        """
        执行Python代码
        
        Args:
            code: Python代码字符串
            exec_globals: 执行时的全局变量字典，默认为空字典
            
        Returns:
            ExecutionResult 执行结果
        """
        log_enabled = cls._enable_log_capture()
        
        try:
            if exec_globals is None:
                exec_globals = {}
            exec(code, exec_globals)
            logs = cls._disable_log_capture() if log_enabled else ""
            return ExecutionResult(
                success=True,
                output="Execution completed successfully.",
                logs=logs
            )
        except SyntaxError as e:
            if log_enabled:
                cls._disable_log_capture()
            return ExecutionResult(
                success=False,
                error=f"Syntax error: {e}"
            )
        except Exception as e:
            logs = cls._disable_log_capture() if log_enabled else ""
            return ExecutionResult(
                success=False,
                error=str(e),
                logs=logs
            )
    
    @classmethod
    def execute_file(cls, file_path: str, exec_globals: dict = None) -> ExecutionResult:
        """
        执行Python文件
        
        Args:
            file_path: Python文件路径
            exec_globals: 执行时的全局变量字典，默认为空字典
            
        Returns:
            ExecutionResult 执行结果
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            return cls.execute_code(code, exec_globals)
        except FileNotFoundError:
            return ExecutionResult(
                success=False,
                error=f"File not found: {file_path}"
            )
        except PermissionError:
            return ExecutionResult(
                success=False,
                error=f"Permission denied: {file_path}"
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"File read error: {e}"
            )


# ============================================================================
# MCP应用构建器
# ============================================================================

class MCPAppBuilder:
    """
    MCP应用构建器
    
    简化MCP Server和SSE的创建
    """
    
    def __init__(self, name: str = "UE-MCP"):
        """
        初始化构建器
        
        Args:
            name: MCP应用名称
        """
        self.name = name
        self._mcp_app = None
        self._sse = None
        self._tool_handler = None
        self._tools = DEFAULT_TOOLS
    
    def set_tools(self, tools: List[ToolDefinition]):
        """设置工具列表"""
        self._tools = tools
        return self
    
    def set_tool_handler(self, handler):
        """
        设置工具调用处理器
        
        Args:
            handler: async def handler(name: str, arguments: dict) -> ExecutionResult
        """
        self._tool_handler = handler
        return self
    
    def build(self) -> Tuple[Any, Any]:
        """
        构建MCP应用
        
        Returns:
            (mcp_app, sse) 元组
        """
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP library not available")
        
        self._mcp_app = Server(self.name)
        self._sse = SseServerTransport("/messages/")
        
        # 注册工具列表
        @self._mcp_app.list_tools()
        async def list_tools():
            return get_mcp_tools(self._tools)
        
        # 注册工具调用处理器
        if self._tool_handler:
            handler = self._tool_handler
            
            @self._mcp_app.call_tool()
            async def call_tools(name: str, arguments: dict):
                result = await handler(name, arguments)
                if isinstance(result, ExecutionResult):
                    return result.to_mcp_content()
                return result
        
        return self._mcp_app, self._sse
    
    def build_starlette_app(self, log_func=None):
        """
        构建完整的Starlette应用
        
        Args:
            log_func: 日志函数
            
        Returns:
            Starlette应用实例
        """
        if not STARLETTE_AVAILABLE:
            raise RuntimeError("Starlette/Uvicorn not available")
        
        mcp_app, sse = self.build()
        log = log_func or print
        
        async def handle_sse(request):
            log(f"[{self.name}] SSE connection starting")
            initialization_options = mcp_app.create_initialization_options()
            
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                log(f"[{self.name}] SSE connected")
                try:
                    await mcp_app.run(
                        streams[0],
                        streams[1],
                        initialization_options,
                    )
                except Exception as e:
                    log(f"[{self.name}] MCP server error: {e}")
                    raise
        
        web_app = Starlette(
            routes=[
                Route("/SSE", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )
        
        return web_app
