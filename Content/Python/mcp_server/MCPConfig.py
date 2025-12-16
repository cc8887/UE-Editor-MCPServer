"""
MCPConfig.py - MCP服务器配置管理
从.env文件和环境变量读取配置

配置优先级：
1. 环境变量 (最高优先级)
2. .env 文件
3. 默认值

支持的配置项：
- MCP_PORT: MCP服务器端口 (默认: 8099)
- MCP_HOST: MCP服务器监听地址 (默认: 127.0.0.1)
- EDITOR_PORT: 编辑器转发服务器端口 (默认: 8100)
- EDITOR_HOST: 编辑器转发服务器地址 (默认: 127.0.0.1)
"""

import os
from typing import Optional


# 默认配置值
DEFAULT_MCP_PORT = 8099
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_EDITOR_PORT = 8100
DEFAULT_EDITOR_HOST = "127.0.0.1"


def _find_env_file() -> Optional[str]:
    """
    查找.env文件
    搜索顺序：
    1. 插件根目录 (UE-Editor-MCPServer/)
    2. mcp_server目录
    3. Content/Python目录
    
    Returns:
        .env文件的完整路径，如果未找到则返回None
    """
    # 获取当前文件所在目录 (mcp_server/)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 搜索路径列表
    search_paths = [
        # 插件根目录 (向上3级: mcp_server -> Python -> Content -> 插件根目录)
        os.path.normpath(os.path.join(current_dir, "..", "..", "..")),
        # mcp_server目录
        current_dir,
        # Content/Python目录
        os.path.normpath(os.path.join(current_dir, "..")),
    ]
    
    for search_dir in search_paths:
        env_path = os.path.join(search_dir, ".env")
        if os.path.isfile(env_path):
            return env_path
    
    return None


def _parse_env_file(env_path: str) -> dict:
    """
    解析.env文件
    
    Args:
        env_path: .env文件路径
        
    Returns:
        配置字典
    """
    config = {}
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                
                # 解析 KEY=VALUE 格式
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 移除引号
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    
                    config[key] = value
    except Exception as e:
        print(f"[MCPConfig] Warning: Failed to parse .env file: {e}")
    
    return config


def _get_config_value(key: str, default: str, env_config: dict) -> str:
    """
    获取配置值
    
    优先级：环境变量 > .env文件 > 默认值
    
    Args:
        key: 配置键名
        default: 默认值
        env_config: 从.env文件解析的配置
        
    Returns:
        配置值
    """
    # 首先检查环境变量
    env_value = os.environ.get(key)
    if env_value is not None:
        return env_value
    
    # 其次检查.env文件
    if key in env_config:
        return env_config[key]
    
    # 最后使用默认值
    return default


# 全局配置缓存
_config_cache: Optional[dict] = None


def load_config(force_reload: bool = False) -> dict:
    """
    加载配置
    
    Args:
        force_reload: 是否强制重新加载
        
    Returns:
        配置字典，包含以下键：
        - mcp_port: int
        - mcp_host: str
        - editor_port: int
        - editor_host: str
    """
    global _config_cache
    
    if _config_cache is not None and not force_reload:
        return _config_cache
    
    # 查找并解析.env文件
    env_config = {}
    env_path = _find_env_file()
    
    if env_path:
        print(f"[MCPConfig] Loading config from: {env_path}")
        env_config = _parse_env_file(env_path)
    else:
        print("[MCPConfig] No .env file found, using defaults and environment variables")
    
    # 获取配置值
    mcp_port_str = _get_config_value("MCP_PORT", str(DEFAULT_MCP_PORT), env_config)
    mcp_host = _get_config_value("MCP_HOST", DEFAULT_MCP_HOST, env_config)
    editor_port_str = _get_config_value("EDITOR_PORT", str(DEFAULT_EDITOR_PORT), env_config)
    editor_host = _get_config_value("EDITOR_HOST", DEFAULT_EDITOR_HOST, env_config)
    
    # 解析端口号
    try:
        mcp_port = int(mcp_port_str)
    except ValueError:
        print(f"[MCPConfig] Warning: Invalid MCP_PORT '{mcp_port_str}', using default {DEFAULT_MCP_PORT}")
        mcp_port = DEFAULT_MCP_PORT
    
    try:
        editor_port = int(editor_port_str)
    except ValueError:
        print(f"[MCPConfig] Warning: Invalid EDITOR_PORT '{editor_port_str}', using default {DEFAULT_EDITOR_PORT}")
        editor_port = DEFAULT_EDITOR_PORT
    
    _config_cache = {
        "mcp_port": mcp_port,
        "mcp_host": mcp_host,
        "editor_port": editor_port,
        "editor_host": editor_host,
    }
    
    print(f"[MCPConfig] Configuration loaded:")
    print(f"  MCP Server: {mcp_host}:{mcp_port}")
    print(f"  Editor Forwarder: {editor_host}:{editor_port}")
    
    return _config_cache


def get_mcp_port() -> int:
    """获取MCP服务器端口"""
    return load_config()["mcp_port"]


def get_mcp_host() -> str:
    """获取MCP服务器监听地址"""
    return load_config()["mcp_host"]


def get_editor_port() -> int:
    """获取编辑器转发服务器端口"""
    return load_config()["editor_port"]


def get_editor_host() -> str:
    """获取编辑器转发服务器地址"""
    return load_config()["editor_host"]
