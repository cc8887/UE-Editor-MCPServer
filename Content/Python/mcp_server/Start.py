"""
Start.py - MCP服务启动入口
支持UE4和UE5两种模式：
- UE5模式：直接使用MCP库在编辑器进程内运行完整MCP服务器
- UE4模式：启动转发服务器，配合外部MCPStandalone.py使用

使用方法：
    # 自动检测模式
    from mcp_server import Start
    Start.start()
    
    # 强制UE5模式
    Start.start_ue5()
    
    # 强制UE4模式（转发器）
    Start.start_ue4()
"""

import importlib
import sys

# 模块引用
modular_Manager = None
modular_MCPServer = None
modular_MCPForwarder = None

# 实例引用
mcp_server = None
mcp_forwarder = None
event_manager = None


def _get_log_function():
    """获取日志函数"""
    try:
        from unreal import log
        return log
    except ImportError:
        return print


def get_ue_version():
    """
    获取UE版本号
    
    Returns:
        int: 4 或 5
    """
    try:
        import unreal
        # 尝试使用UE5的API
        if hasattr(unreal, 'SystemLibrary'):
            try:
                version_str = str(unreal.SystemLibrary.get_engine_version())
                if version_str.startswith('5'):
                    return 5
            except Exception:
                pass
        
        # 检查UE5特有的模块/类
        if hasattr(unreal, 'EditorAssetLibrary'):
            # 进一步检查是否是UE5特有的方法
            if hasattr(unreal.EditorAssetLibrary, 'sync_browser_to_objects'):
                return 5
        
        return 4
    except Exception:
        return 4


def is_mcp_available():
    """
    检查是否可以直接使用MCP库
    
    Returns:
        bool: MCP库是否可用
    """
    try:
        import mcp
        import uvicorn
        import starlette
        return True
    except ImportError:
        return False


def start():
    """
    启动MCP服务（自动选择模式）
    
    根据UE版本和MCP库可用性自动选择：
    - UE5 + MCP可用：完整MCP服务器模式
    - UE4 或 MCP不可用：转发器模式
    """
    global modular_Manager, modular_MCPServer, modular_MCPForwarder
    global mcp_server, mcp_forwarder, event_manager
    
    log = _get_log_function()
    
    ue_version = get_ue_version()
    mcp_available = is_mcp_available()
    
    log(f"[MCP] UE Version: {ue_version}, MCP Library Available: {mcp_available}")
    
    if ue_version >= 5 and mcp_available:
        # UE5 + MCP可用：使用完整MCP服务器
        log("[MCP] Starting full MCP server mode (UE5)")
        start_ue5()
    else:
        # UE4 或 MCP不可用：使用转发模式
        log("[MCP] Starting forwarder mode (UE4 compatible)")
        log("[MCP] Please run MCPStandalone.py in a separate terminal to provide MCP service")
        start_ue4()


def start_ue5():
    """
    强制启动UE5模式（完整MCP服务器）
    
    在编辑器进程内直接运行MCP服务器，需要MCP库可用
    """
    global modular_Manager, modular_MCPServer, mcp_server, event_manager
    
    log = _get_log_function()
    log("[MCP] Starting UE5 full MCP server mode")
    
    # 导入类（__init__.py已将类导出到包级别）
    from . import Manager as ManagerClass
    from . import MCPServer as MCPServerClass
    modular_Manager = ManagerClass
    modular_MCPServer = MCPServerClass
    
    # 创建实例
    event_manager = ManagerClass()
    mcp_server = MCPServerClass()
    
    # 运行服务器
    event_manager.run_until_complete(mcp_server.run_server(), use_heart=False)


def start_ue4(host: str = None, port: int = None):
    """
    强制启动UE4模式（转发服务器）
    
    启动转发服务器，等待外部MCPStandalone.py连接
    
    Args:
        host: 监听地址，默认从.env读取或使用127.0.0.1
        port: 监听端口，默认从.env读取或使用8100
    """
    # 从配置文件加载默认值
    from . import MCPConfig
    if host is None:
        host = MCPConfig.get_editor_host()
    if port is None:
        port = MCPConfig.get_editor_port()
    global modular_Manager, modular_MCPForwarder, mcp_forwarder, event_manager
    
    log = _get_log_function()
    log(f"[MCP] Starting UE4 forwarder mode on {host}:{port}")
    
    # 导入类（__init__.py已将类导出到包级别）
    from . import Manager as ManagerClass
    from . import MCPForwarder as MCPForwarderClass
    modular_Manager = ManagerClass
    modular_MCPForwarder = MCPForwarderClass
    
    # 创建实例
    event_manager = ManagerClass()
    mcp_forwarder = MCPForwarderClass(host=host, port=port)
    
    # 启动转发服务器
    mcp_forwarder.start()
    
    # 创建异步tick循环
    async def forwarder_tick_loop():
        import asyncio
        log("[MCP] Forwarder tick loop started")
        while mcp_forwarder.is_running:
            mcp_forwarder.tick(0.016)  # 约60fps
            await asyncio.sleep(0.001)
        log("[MCP] Forwarder tick loop ended")
    
    # 运行事件循环
    event_manager.run_until_complete(forwarder_tick_loop(), use_heart=False)


def start_forwarder(host: str = None, port: int = None):
    """
    启动转发服务器的别名
    
    Args:
        host: 监听地址，默认从.env读取
        port: 监听端口，默认从.env读取
    """
    start_ue4(host=host, port=port)


def reload():
    """
    重新加载模块并重启服务
    """
    global modular_Manager, modular_MCPServer, modular_MCPForwarder
    global mcp_server, mcp_forwarder, event_manager
    
    log = _get_log_function()
    log("[MCP] Reloading...")
    
    # 停止现有服务
    stop()
    
    # 重新加载模块
    if modular_Manager is not None:
        try:
            modular_Manager = importlib.reload(modular_Manager)
        except Exception as e:
            log(f"[MCP] Failed to reload Manager: {e}")
            modular_Manager = None
    
    if modular_MCPServer is not None:
        try:
            modular_MCPServer = importlib.reload(modular_MCPServer)
        except Exception as e:
            log(f"[MCP] Failed to reload MCPServer: {e}")
            modular_MCPServer = None
    
    if modular_MCPForwarder is not None:
        try:
            modular_MCPForwarder = importlib.reload(modular_MCPForwarder)
        except Exception as e:
            log(f"[MCP] Failed to reload MCPForwarder: {e}")
            modular_MCPForwarder = None
    
    # 重新启动
    log("[MCP] Restarting service...")
    start()


def stop():
    """
    停止所有服务并清理资源
    """
    global mcp_server, mcp_forwarder, event_manager
    
    log = _get_log_function()
    log("[MCP] Stopping service...")
    
    # 停止MCP服务器
    if mcp_server is not None:
        try:
            # MCPServer.destroy 可能是异步的
            import asyncio
            if asyncio.iscoroutinefunction(mcp_server.destroy):
                # 如果是协程，需要在事件循环中执行
                pass
            else:
                mcp_server.destroy()
        except Exception as e:
            log(f"[MCP] Error stopping MCP server: {e}")
        mcp_server = None
    
    # 停止转发服务器
    if mcp_forwarder is not None:
        try:
            mcp_forwarder.destroy()
        except Exception as e:
            log(f"[MCP] Error stopping forwarder: {e}")
        mcp_forwarder = None
    
    # 停止事件管理器
    if event_manager is not None:
        try:
            event_manager.destroy()
        except Exception as e:
            log(f"[MCP] Error stopping event manager: {e}")
        event_manager = None
    
    log("[MCP] Service stopped")


def get_status():
    """
    获取当前服务状态
    
    Returns:
        dict: 状态信息
    """
    status = {
        "ue_version": get_ue_version(),
        "mcp_available": is_mcp_available(),
        "mode": None,
        "running": False,
        "connected": False
    }
    
    if mcp_server is not None:
        status["mode"] = "ue5_full"
        status["running"] = True
    elif mcp_forwarder is not None:
        status["mode"] = "ue4_forwarder"
        status["running"] = mcp_forwarder.is_running
        status["connected"] = mcp_forwarder.is_connected
    
    return status


def print_status():
    """打印当前服务状态"""
    log = _get_log_function()
    status = get_status()
    
    log("=" * 50)
    log("[MCP] Service Status")
    log("=" * 50)
    log(f"  UE Version: {status['ue_version']}")
    log(f"  MCP Library Available: {status['mcp_available']}")
    log(f"  Mode: {status['mode'] or 'Not started'}")
    log(f"  Running: {status['running']}")
    if status['mode'] == 'ue4_forwarder':
        log(f"  Client Connected: {status['connected']}")
    log("=" * 50)
