# MCPServer - MCP Client 配置指南

插件位置：`<YOUR_ALSV_PROJECT>\Plugins\MCPServer\`
端口：MCP_PORT=8099（对外）/ EDITOR_PORT=8100（UE 内部转发）

---

## 前提条件

**每次使用前，必须先启动 ALSV 项目的 UE Editor**（插件在 PostEngineInit 阶段自动启动内部 TCP 服务器，监听 8100 端口）。

---

## 方案 A：命令行启动模式（所有客户端通用）

MCPServer 支持两种接入方式：

### 1. 直接启动（客户端托管进程）

MCP 客户端直接用 `uv run python main.py` 启动服务进程。

**优点**：客户端退出时服务自动关闭，无需手动管理进程。

### 2. SSE URL 直连（手动先启动服务）

先在终端手动运行：
```cmd
cd <YOUR_ALSV_PROJECT>\Plugins\MCPServer
uv run python main.py
```
然后客户端直连 `http://127.0.0.1:8099/sse`。

---

## 各客户端配置

### Claude Desktop

配置文件路径：`%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ue-editor-alsv": {
      "command": "<PATH_TO_UV_EXE>",
      "args": [
        "run",
        "--directory",
        "<YOUR_ALSV_PROJECT>\\Plugins\\MCPServer",
        "python",
        "main.py"
      ],
      "env": {
        "MCP_PORT": "8099",
        "MCP_HOST": "127.0.0.1",
        "EDITOR_PORT": "8100",
        "EDITOR_HOST": "127.0.0.1"
      }
    }
  }
}
```

---

### Cursor

`.cursor/mcp.json`（项目级）或 `%APPDATA%\Cursor\User\settings.json`（全局）：

```json
{
  "mcpServers": {
    "ue-editor-alsv": {
      "command": "<PATH_TO_UV_EXE>",
      "args": [
        "run",
        "--directory",
        "<YOUR_ALSV_PROJECT>\\Plugins\\MCPServer",
        "python",
        "main.py"
      ],
      "env": {
        "MCP_PORT": "8099",
        "MCP_HOST": "127.0.0.1",
        "EDITOR_PORT": "8100",
        "EDITOR_HOST": "127.0.0.1"
      }
    }
  }
}
```

---

### WorkBuddy（或其它支持 MCP 的 IDE）

参考 Claude Desktop 配置，将 `claude_desktop_config.json` 中的内容写入对应 IDE 的 MCP 配置文件。

---

### SSE 直连模式（通用）

适用于任何支持 SSE MCP transport 的客户端：

```
URL: http://127.0.0.1:8099/sse
Transport: SSE
```

---

## 调试

```cmd
cd <YOUR_ALSV_PROJECT>\Plugins\MCPServer
uv run python main.py --debug
```

---

## 端口冲突处理

编辑 `.env` 文件修改端口：

```env
MCP_PORT=8099      # 对外 SSE 端口
EDITOR_PORT=8100   # UE 内部转发端口
```

注意：修改 EDITOR_PORT 后，UE 编辑器侧的插件配置也需同步修改。
