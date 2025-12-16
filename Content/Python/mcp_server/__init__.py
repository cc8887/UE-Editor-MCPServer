"""
mcp_server - UE Editor MCP Server 核心模块

包含：
- MCPCore: MCP公共核心模块（依赖导入、工具定义、执行结果）- 不依赖unreal
- CustomEventLoop: 自定义事件循环（适配UE编辑器tick）
- Manager: 事件管理器
- MCPServer: UE5完整MCP服务器（包含CodeExecutor，依赖unreal）
- MCPForwarder: UE4转发服务器
- MCPStandalone: 独立进程MCP服务器
- Start: 启动入口
"""

from .MCPCore import (
    MCP_AVAILABLE, MCP_IMPORT_ERRORS,
    STARLETTE_AVAILABLE, STARLETTE_IMPORT_ERRORS,
    types, Server, SseServerTransport,
    uvicorn, Starlette, Mount, Route,
    ToolDefinition, ExecutionResult,
    TOOL_EXECUTE_COMMAND, TOOL_EXECUTE_FILE, TOOL_GET_EDITOR_STATE,
    DEFAULT_TOOLS, get_mcp_tools,
    MCPAppBuilder, try_imports
)
from .CustomEventLoop import WinCustomEventLoop
from .Manager import Manager
from .MCPForwarder import MCPForwarder, ForwarderState
from .MCPStandalone import MCPStandaloneServer, EditorConnection, EditorState, ConnectionConfig
from .MCPServer import MCPServer, CodeExecutor
from . import Start

__all__ = [
    # MCPCore (不依赖unreal)
    'MCP_AVAILABLE', 'MCP_IMPORT_ERRORS',
    'STARLETTE_AVAILABLE', 'STARLETTE_IMPORT_ERRORS',
    'types', 'Server', 'SseServerTransport',
    'uvicorn', 'Starlette', 'Mount', 'Route',
    'ToolDefinition', 'ExecutionResult',
    'TOOL_EXECUTE_COMMAND', 'TOOL_EXECUTE_FILE', 'TOOL_GET_EDITOR_STATE',
    'DEFAULT_TOOLS', 'get_mcp_tools',
    'MCPAppBuilder', 'try_imports',
    # CustomEventLoop
    'WinCustomEventLoop',
    # Manager
    'Manager',
    # MCPForwarder
    'MCPForwarder',
    'ForwarderState',
    # MCPStandalone
    'MCPStandaloneServer',
    'EditorConnection',
    'EditorState',
    'ConnectionConfig',
    # MCPServer (依赖unreal)
    'MCPServer',
    'CodeExecutor',
    # Start
    'Start',
]
