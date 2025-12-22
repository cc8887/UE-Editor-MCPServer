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

### 前置条件

确保你已经完成以下步骤：

- UE4/UE5 编辑器已启动并加载了插件
- （UE4用户）独立 MCP 服务器已运行（`python main.py`）
- 服务器正在监听 `127.0.0.1:8099`（默认端口）

### 支持的客户端

#### 1. Claude Desktop

Claude Desktop 是 Anthropic 官方的桌面应用，原生支持 MCP 协议。

**配置步骤：**

1. 找到 Claude Desktop 的配置文件：
   
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. 编辑配置文件，添加 `mcpServers` 配置：

```json
{
  "mcpServers": {
    "ue-editor": {
      "url": "http://127.0.0.1:8099/sse"
    }
  }
}
```

如果需要自定义端口，修改 `url` 中的端口号：

```json
{
  "mcpServers": {
    "ue-editor": {
      "url": "http://127.0.0.1:自定义端口/sse"
    }
  }
}
```

3. 保存配置文件并重启 Claude Desktop

4. 连接成功后，在对话中可以看到 `ue-editor` 服务器及其提供的工具

**可用工具示例：**

- `execute_python` - 在 UE 编辑器中执行 Python 代码
- `execute_python_file` - 执行 Python 脚本文件
- `get_logs` - 获取编辑器日志

#### 2. Cursor

Cursor 是基于 VSCode 的 AI 编辑器，支持通过扩展连接 MCP 服务器。

**配置步骤（方法一：使用 MCP 扩展）：**

1. 在 Cursor 中安装 MCP 客户端扩展（如果可用）

2. 打开设置（`Ctrl+,` 或 `Cmd+,`），搜索 "MCP"

3. 添加服务器配置：

```json
{
  "mcp.servers": [
    {
      "name": "ue-editor",
      "url": "http://127.0.0.1:8099/sse"
    }
  ]
}
```

**配置步骤（方法二：直接使用 HTTP 请求）：**

在 Cursor 中，你也可以通过编写脚本直接向 MCP 服务器发送请求：

```typescript
// 示例：调用 execute_python 工具
const response = await fetch('http://127.0.0.1:8099/call-tool', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: 'execute_python',
    arguments: {
      code: 'import unreal; print(unreal.EditorLevelLibrary.get_all_level_actors())'
    }
  })
});

const result = await response.json();
console.log(result);
```

#### 3. Continue.dev

Continue 是一个开源的 AI 代码助手，支持自定义 MCP 服务器。

**配置步骤：**

1. 打开 Continue 配置文件（通常在 `~/.continue/config.json`）

2. 在 `mcpServers` 部分添加：

```json
{
  "mcpServers": [
    {
      "name": "ue-editor",
      "transport": {
        "type": "sse",
        "url": "http://127.0.0.1:8099/sse"
      }
    }
  ]
}
```

3. 重启 Continue 扩展

#### 4. 自定义客户端（通用配置）

如果你正在开发自己的 MCP 客户端，可以使用以下信息连接到服务器：

**连接信息：**

- **协议**: SSE (Server-Sent Events)
- **端点**: `http://127.0.0.1:8099/sse`
- **调用工具**: `POST http://127.0.0.1:8099/call-tool`

**请求格式示例：**

```http
POST /call-tool HTTP/1.1
Host: 127.0.0.1:8099
Content-Type: application/json

{
  "name": "execute_python",
  "arguments": {
    "code": "import unreal; print('Hello from UE!')"
  }
}
```

**响应格式示例：**

```json
{
  "content": [
    {
      "type": "text",
      "text": "Hello from UE!\n执行成功"
    }
  ]
}
```

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

**问题 2：工具调用失败**

- 确认 UE 编辑器已完全加载
- （UE4）检查 Forwarder 是否正常运行（端口 8100）
- 在 UE 编辑器的 Python 控制台中手动测试代码是否能执行
- 查看编辑器的输出日志（Output Log 窗口）

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
      "url": "http://127.0.0.1:8099/sse"
    },
    "ue-project-b": {
      "url": "http://127.0.0.1:8199/sse"
    }
  }
}
```

#### 远程访问（高级）

默认配置仅允许本地访问（`127.0.0.1`）。如需远程访问：

1. 修改 `.env` 中的 `MCP_HOST`：

```ini
MCP_HOST=0.0.0.0  # 监听所有网络接口
```

2. 配置防火墙规则允许外部访问

3. **安全警告**：远程访问会带来安全风险，请仅在受信任的网络环境中使用，并考虑添加身份验证机制

### 推荐客户端

- **最佳体验**: Claude Desktop（原生支持，配置简单）
- **开发者友好**: Cursor / Continue（集成开发环境）
- **自定义需求**: 自行开发客户端（使用 MCP SDK）
