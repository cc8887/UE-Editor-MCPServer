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

目前仅提供了示例版本的MCPServer，若想扩展功能请修改 `Content/Python/mcp_server/` 目录下的脚本（主要入口为 `MCPStandalone.py`、`MCPServer.py`）

> **⚠️ 重要：SSE 端点路径必须使用大写 `/SSE`**
>
> MCP 客户端配置中的 URL 路径为 **大写的 `/SSE`**（不是小写的 `/sse`）。
> 服务器端路由区分大小写，使用小写 `/sse` 将导致连接失败（404 / ECONNREFUSED）。
>
> 正确示例：`http://127.0.0.1:8099/SSE` ✅
> 错误示例：`http://127.0.0.1:8099/sse` ❌


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

- `--mcp-host`: MCP服务器监听地址（默认：127.0.0.1）
- `--mcp-port`: MCP服务器端口（默认：8099）
- `--editor-host`: 编辑器转发服务器地址（默认：127.0.0.1）
- `--editor-port`: 编辑器转发服务器端口（默认：8100）
- `--debug`: 启用调试模式，输出详细日志

示例：

```cmd
# 基础使用
python main.py --mcp-port 8099 --editor-port 8100

# 启用调试模式
python main.py --debug

# 自定义地址和端口并启用调试
python main.py --mcp-host 0.0.0.0 --mcp-port 8099 --editor-port 8100 --debug
```

#### 5. 配置MCP客户端

在你的MCP客户端(如Cursor、Claude Desktop等)中添加服务器配置,连接到 `127.0.0.1:8099`

详细配置方法请参见下方的 [MCP 客户端配置指南](#mcp-客户端配置指南)。

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

---

## MCP 客户端配置指南

本节介绍如何在主流 MCP 客户端中配置 UE-Editor-MCPServer。

### MCP 配置
```json
{
  "mcpServers": {
    "ue-editor": {
      "url": "http://127.0.0.1:8099/SSE",
      "description": "UE Editor MCP Server - Enables AI agents to automate UE4/UE5 development through Python scripting"
    }
  }
}
```

### 前置条件

确保你已经完成以下步骤：

- UE4/UE5 编辑器已启动并加载了插件
- （UE4用户）独立 MCP 服务器已运行（`python main.py`）
- 服务器正在监听 `127.0.0.1:8099`（默认端口）



### 验证连接

配置完成后，可以通过以下方式验证连接是否成功：

1. **在客户端执行简单命令**：

请 AI 助手执行以下代码：

```python
import unreal
print("UE Editor MCP Server is working!")
```

如果返回成功消息，说明连接正常。

2. **检查服务器日志**：

在运行 `python main.py` 的终端窗口中，应该能看到客户端的连接日志。

3. **测试工具调用**：

尝试调用 `get_logs` 工具，应该能获取到 UE 编辑器的日志输出。

### 故障排除

**问题 1：客户端无法连接到服务器**

- 检查 MCP 服务器是否正在运行（UE5 自动启动 / UE4 需要手动运行 `python main.py`）
- 确认端口号是否正确（默认 8099）
- 检查防火墙设置，确保允许本地连接
- 查看服务器终端输出，寻找错误信息
- **使用调试模式**：运行 `python main.py --debug` 查看详细连接日志

**问题 2：工具调用失败**

- 确认 UE 编辑器已完全加载
- （UE4）检查 Forwarder 是否正常运行（端口 8100）
- 在 UE 编辑器的 Python 控制台中手动测试代码是否能执行
- 查看编辑器的输出日志（Output Log 窗口）
- **使用调试模式**：运行 `python main.py --debug` 查看请求/响应详情

**问题 3：端口冲突**

如果默认端口被占用，修改 `.env` 文件中的端口配置：

```ini
MCP_PORT=8199  # 修改为未占用的端口
EDITOR_PORT=8200  # UE4 用户还需修改此端口
```

然后重启服务器，并更新客户端配置中的端口号。

### 进阶配置

#### 多项目支持

如果需要同时连接多个 UE 项目，为每个项目分配不同的端口：

**项目 A：**

```ini
MCP_PORT=8099
EDITOR_PORT=8100
```

**项目 B：**

```ini
MCP_PORT=8199
EDITOR_PORT=8200
```

在客户端配置中添加多个服务器：

```json
{
  "mcpServers": {
    "ue-project-a": {
      "url": "http://127.0.0.1:8099/SSE"

    },
    "ue-project-b": {
      "url": "http://127.0.0.1:8199/SSE"
    }

  }
}
```

