# UE-Editor-MCPServer
将UE Editor封装为MCP Server供Agent使用以实现Agent自动化迭代
python新手，欢迎大佬们提各种建议

- 当前版本基于5.5开发 暂时不保证其他版本引擎下的可用性（按道理只要Pyhton版本及PythonScriptPlugin跟5.5一致即可），后续会考虑支持UE5和部分UE4版本
- 目前仅保证Win下稳定
## Setup
clone当前项目至项目或者引擎的plugin并编译，引擎启动后会自动启动MCPServer
- 需自行保证pip源连接畅通
- 需要C++版本的项目，未来会上架商店

## How To Use
目前仅提供了示例版本的MCPServer，若想添加功能在.Content/Python/MCPServer.py中修改即可

## UE4 使用指南

由于UE4内置的Python版本较低（通常为Python 2.7或3.7），无法直接运行MCP库，因此采用**转发模式**：
- UE4编辑器内运行转发服务器（Forwarder）
- 外部运行独立MCP服务器，通过Socket与编辑器通信

### 环境要求
- Python 3.11+ （用于运行独立MCP服务器）
- UE4项目需启用 PythonScriptPlugin

### 配置步骤

#### 1. 安装依赖
在插件根目录下执行：
```cmd
uv sync
```

#### 2. 配置端口（可选）
复制 `.env.example` 为 `.env`，根据需要修改端口配置：
```cmd
copy .env.example .env
```

`.env` 文件内容：
```ini
# MCP服务器端口 (MCPStandalone对外提供的SSE服务端口)
MCP_PORT=8099
MCP_HOST=127.0.0.1

# 编辑器转发服务器端口 (UE编辑器内部监听的端口)
EDITOR_PORT=8100
EDITOR_HOST=127.0.0.1
```

> 如果不创建 `.env` 文件，将使用默认端口（MCP: 8099, Editor: 8100）

#### 3. 启动UE4编辑器
启动编辑器后，插件会自动检测UE版本并启动转发服务器（端口从 `.env` 读取，默认 `127.0.0.1:8100`）

#### 4. 启动独立MCP服务器
在**单独的终端**中，进入插件根目录并运行：
```cmd
python main.py
```

服务器会自动读取 `.env` 配置。也支持命令行参数覆盖（优先级高于 `.env`）：
- `--mcp-port`: MCP服务器端口
- `--editor-port`: 编辑器转发服务器端口

示例：
```cmd
python main.py --mcp-port 8099 --editor-port 8100
```

#### 5. 配置MCP客户端
在你的MCP客户端（如Cursor、Claude Desktop等）中添加服务器配置，连接到 `127.0.0.1:8099`

### 工作原理
```
MCP Client <---> main.py (MCP Server, port 8099) <---> UE4 Editor (Forwarder, port 8100)
```

### 手动控制（可选）
在UE4编辑器的Python控制台中可以手动控制服务：
```python
from mcp_server import Start

# 查看状态
Start.print_status()

# 停止服务
Start.stop()

# 重启服务
Start.start()
```
