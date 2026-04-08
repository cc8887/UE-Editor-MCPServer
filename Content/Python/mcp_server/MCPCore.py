"""
MCPCore - MCP公共核心模块

提供MCP Server和MCPStandalone共用的功能：
1. MCP依赖导入和检查
2. 工具定义
3. 执行结果数据类

注意：此模块不依赖unreal包，可在编辑器外独立使用
"""

import os
import sys
from datetime import datetime
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

TOOL_GET_IMPORTED_MODULES = ToolDefinition(
    name="get_imported_modules",
    description="Get all imported modules in the current Unreal Editor Python environment. Returns a list of module names and generates import statements for type checking (e.g., mypy).",
    input_schema={
        "type": "object",
        "properties": {
            "include_stdlib": {
                "type": "boolean",
                "description": "Include standard library modules (default: false). If false, only returns third-party and editor-specific modules."
            },
            "format": {
                "type": "string",
                "description": "Output format: 'list' (module names only), 'imports' (import statements), or 'both' (default: 'both')",
                "enum": ["list", "imports", "both"]
            }
        }
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

# 大日志输出阈值
LOG_MAX_LINES = 20
LOG_MAX_CHARS = 400


def _get_log_dir() -> str:
    """
    获取 MCP 日志输出目录。

    搜索顺序：
    1. UE 项目级别: <ProjectDir>/Saved/Logs/MCP/
       - 通过 unreal.EditorAssetLibrary 或环境变量 UE_PROJECT_DIR 定位
    2. 插件级别: <PluginRoot>/Saved/Logs/MCP/
       - 向上追溯到插件根目录
    3. 回退: 系统临时目录

    Returns:
        日志目录的绝对路径
    """
    # 1. 尝试通过 unreal 获取 UE 项目目录
    try:
        import unreal
        project_dir = unreal.EditorAssetLibrary.get_current_level_directory()
        if project_dir:
            # get_current_level_directory 返回 /Game/xxx，取项目根目录
            project_dir = unreal.Paths.project_dir()
            if project_dir:
                log_dir = os.path.join(project_dir, "Saved", "Logs", "MCP")
                os.makedirs(log_dir, exist_ok=True)
                return log_dir
    except Exception:
        pass

    # 2. 回退：尝试通过环境变量获取项目目录
    ue_project_dir = os.environ.get("UE_PROJECT_DIR")
    if ue_project_dir and os.path.isdir(ue_project_dir):
        log_dir = os.path.join(ue_project_dir, "Saved", "Logs", "MCP")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    # 3. 回退：插件根目录下的 Saved/Logs/MCP/
    plugin_root = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )
    if os.path.isdir(plugin_root):
        log_dir = os.path.join(plugin_root, "Saved", "Logs", "MCP")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    # 4. 最终回退：系统临时目录
    import tempfile
    fallback_dir = os.path.join(tempfile.gettempdir(), "MCPLogs")
    os.makedirs(fallback_dir, exist_ok=True)
    return fallback_dir


def _save_log_to_file(full_text: str) -> str:
    """
    将长日志保存到文件，返回文件路径。

    文件保存到项目 Saved/Logs/MCP/ 目录下，命名格式: mcp_log_<时间戳>_<序号>.txt
    如果无法定位项目目录，则回退到插件目录或系统临时目录。

    Args:
        full_text: 要保存的完整日志文本

    Returns:
        保存的文件路径
    """
    log_dir = _get_log_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"mcp_log_{timestamp}"
    file_path = os.path.join(log_dir, f"{base_name}.txt")

    # 避免同秒冲突，追加序号
    counter = 0
    while os.path.exists(file_path):
        counter += 1
        file_path = os.path.join(log_dir, f"{base_name}_{counter}.txt")

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(full_text)

    return file_path


def _should_spill(full_text: str) -> bool:
    """判断文本是否超过阈值，需要输出到文件"""
    lines = full_text.split('\n')
    # 去掉尾部空行后再计数
    non_empty_lines = [l for l in lines if l.strip()]
    return len(non_empty_lines) > LOG_MAX_LINES or len(full_text) > LOG_MAX_CHARS


@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    output: str = ""
    error: str = ""
    logs: str = ""
    
    def to_text(self) -> str:
        """转换为文本输出。如果日志超过阈值，保存到文件并返回文件路径。"""
        if self.success:
            text = self.output or "Execution completed successfully."
        else:
            text = f"Error: {self.error}" if self.error else "Execution failed."
        
        if self.logs:
            full_text = text + f"\n\nCaptured Logs:\n{self.logs}"
        else:
            full_text = text
        
        if _should_spill(full_text):
            file_path = _save_log_to_file(full_text)
            return f"[Output exceeded threshold. Full output saved to: {file_path}]"
        
        return full_text
    
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
    def get_imported_modules(include_stdlib: bool = False, output_format: str = "imports") -> ExecutionResult:
        """
        获取当前Python环境中已导入的所有模块
        
        Args:
            include_stdlib: 是否包含标准库模块（默认False，只返回第三方和编辑器特定模块）
            output_format: 输出格式 - 'list'（模块名列表）, 'imports'（import语句）, 'both'（两者）
            
        Returns:
            ExecutionResult 包含模块信息的执行结果
        """
        import sys
        import os
        
        try:
            # 获取所有已导入的模块
            all_modules = list(sys.modules.keys())
            
            # 如果不包含标准库，过滤掉标准库模块
            if not include_stdlib:
                # 获取标准库路径
                stdlib_paths = set()
                try:
                    import sysconfig
                    stdlib_paths.add(os.path.normcase(sysconfig.get_path('stdlib')))
                    stdlib_paths.add(os.path.normcase(sysconfig.get_path('platstdlib')))
                except:
                    pass
                
                # 过滤模块
                filtered_modules = []
                for module_name in all_modules:
                    module = sys.modules.get(module_name)
                    if module is None:
                        continue
                    
                    # 跳过内置模块
                    if not hasattr(module, '__file__') or module.__file__ is None:
                        continue
                    
                    # 检查是否为标准库模块
                    try:
                        module_path = os.path.normcase(os.path.dirname(module.__file__))
                        is_stdlib = any(module_path.startswith(stdlib_path) for stdlib_path in stdlib_paths)
                        if not is_stdlib:
                            # 只保留顶层模块名
                            top_level = module_name.split('.')[0]
                            if top_level not in filtered_modules:
                                filtered_modules.append(top_level)
                    except:
                        pass
                
                modules = sorted(filtered_modules)
            else:
                # 提取顶层模块名并去重
                top_level_modules = set()
                for module_name in all_modules:
                    top_level = module_name.split('.')[0]
                    top_level_modules.add(top_level)
                modules = sorted(top_level_modules)
            
            # 生成输出
            if output_format == "list":
                # 只返回模块名列表
                output_text = "\n".join(modules)
            elif output_format == "imports":
                # 只返回纯净的import语句
                import_statements = [f"import {module}" for module in modules]
                output_text = "\n".join(import_statements)
            elif output_format == "both":
                # 返回格式化的完整信息（保留标题用于展示）
                output_parts = []
                output_parts.append("=== Imported Modules ===")
                output_parts.append(f"Total: {len(modules)} modules")
                output_parts.append("\n".join(modules))
                output_parts.append("\n=== Import Statements ===")
                import_statements = [f"import {module}" for module in modules]
                output_parts.append("\n".join(import_statements))
                output_text = "\n\n".join(output_parts)
            else:
                # 默认返回模块列表
                output_text = "\n".join(modules)
            
            return ExecutionResult(
                success=True,
                output=output_text
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=f"Failed to get imported modules: {e}"
            )
    
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
