"""
Start.py - MCP服务启动入口
统一使用转发器模式（Forwarder + MCPStandalone 双进程架构）：
- 编辑器内运行MCPForwarder（TCP转发器）
- 外部运行MCPStandalone.py（独立SSE服务）

使用方法：
    # 启动服务（统一转发器模式）
    from mcp_server import Start
    Start.start()
    
    # 显式调用（等价于start()）
    Start.start_ue4()
"""

import importlib
import sys

# 模块引用
modular_Manager = None
modular_MCPForwarder = None

# 实例引用
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


def start():
    """
    启动MCP服务（统一转发器模式）
    
    无论UE4还是UE5，统一使用 Forwarder + MCPStandalone 双进程架构：
    - 编辑器内：MCPForwarder（TCP转发器）
    - 外部进程：MCPStandalone.py（SSE服务）
    """
    global modular_Manager, modular_MCPForwarder
    global mcp_forwarder, event_manager
    
    log = _get_log_function()
    ue_version = get_ue_version()
    
    log(f"[MCP] UE Version: {ue_version}, Mode: forwarder (unified)")
    log("[MCP] Starting forwarder mode (unified for UE4/UE5)")
    log("[MCP] Please run MCPStandalone.py in a separate terminal to provide MCP service")
    start_ue4()


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
    global modular_Manager, modular_MCPForwarder
    global mcp_forwarder, event_manager
    
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
    global mcp_forwarder, event_manager
    
    log = _get_log_function()
    log("[MCP] Stopping service...")
    
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
        "mode": None,
        "running": False,
        "connected": False
    }
    
    if mcp_forwarder is not None:
        status["mode"] = "forwarder"
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
    log(f"  Mode: {status['mode'] or 'Not started'}")
    log(f"  Running: {status['running']}")
    if status['mode'] == 'forwarder':
        log(f"  Client Connected: {status['connected']}")
    log("=" * 50)
