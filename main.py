"""
main.py - 独立MCP服务器启动入口
用于在外部进程中运行MCP服务器，与UE编辑器内的转发服务器配合使用

使用方法：
    python main.py [--mcp-port 8099] [--editor-port 8100]
"""

import sys
import os

# 获取路径但不添加到sys.path，避免Content/Python中的旧版本库覆盖系统库
script_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.join(script_dir, "Content", "Python")


def main():
    """启动独立MCP服务器"""
    print("=" * 60)
    print("UE Editor MCP Standalone Server")
    print("=" * 60)
    
    try:
        # 将mcp_server目录添加到sys.path，使MCPStandalone能导入MCPCore
        mcp_server_dir = os.path.join(python_dir, "mcp_server")
        if mcp_server_dir not in sys.path:
            sys.path.insert(0, mcp_server_dir)
        
        # 直接导入MCPStandalone模块，避免通过__init__.py导入依赖unreal的模块
        import importlib.util
        standalone_path = os.path.join(python_dir, "mcp_server", "MCPStandalone.py")
        spec = importlib.util.spec_from_file_location("MCPStandalone", standalone_path)
        MCPStandalone = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(MCPStandalone)
        
        # 使用MCPStandalone的命令行入口，支持参数解析
        MCPStandalone.main()
    except ImportError as e:
        print(f"Error: Failed to import MCPStandalone module: {e}")
        print(f"Python path: {sys.path}")
        print("\nPlease ensure the following dependencies are installed:")
        print("  pip install mcp uvicorn starlette")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()