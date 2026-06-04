# UE-Editor-MCPServer

将 Unreal Editor 封装为 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) Server，供 AI Agent 通过 Python 脚本驱动编辑器，实现自动化迭代。

---

## 快速开始

### 1. 安装 Python 依赖

插件根目录下执行（需要 [uv](https://docs.astral.sh/uv/)）：

```cmd
uv sync
```

> 不使用 uv：`pip install -r requirements.txt`

### 2. 启动 UE 编辑器

启动编辑器后，C++ 模块自动启动 Forwarder（监听 `127.0.0.1:8100`）。

### 3. 配置 MCP 客户端

#### stdio 模式（推荐）

由 MCP 客户端自动拉起 `main.py`，无需手动操作。

```json
{
  "mcpServers": {
    "ue-editor": {
      "command": "uv",
      "args": [
        "run", "--directory", "D:\\MCP\\Plugins\\UE-Editor-MCPServer",
        "python", "main.py",
        "--project", "D:\\MCP\\YourProj.uproject"
      ]
    }
  }
}
```

> `--project` 指向 `.uproject` 路径，用于额外暴露 `open_editor` / `close_editor` 工具（自动 GPF/Build/启动/关闭编辑器）。省略则只暴露 `execute_command` / `excute_file` / `get_editor_state` 三个工具。

#### SSE 模式

手动启动 MCPStandalone：

```cmd
python main.py --transport sse
```

客户端配置：

```json
{
  "mcpServers": {
    "ue-editor": {
      "url": "http://127.0.0.1:8099/SSE"
    }
  }
}
```

> SSE 端点路径大小写不敏感：`/SSE`、`/sse`、`/Sse` 均可。

---

## 配置说明

配置优先级：**命令行参数 > 环境变量 > `.env` 文件 > 默认值**。

### `.env` 配置文件

在插件根目录创建 `.env`（可复制 `.env.example`）：

```ini
# MCP 服务监听地址（仅 SSE 模式使用）
MCP_HOST=127.0.0.1
MCP_PORT=8099

# UE 编辑器 Forwarder 地址（TCP 转发器）
EDITOR_HOST=127.0.0.1
EDITOR_PORT=8100
```

默认端口：MCP `8099`，Editor Forwarder `8100`。多项目需分配不同端口。

| 参数               | 说明                        | 默认值         |
| ---------------- | ------------------------- | ----------- |
| `--transport`    | 传输模式：`stdio`（默认）或 `sse`   | `stdio`     |
| `--mcp-host`     | MCP 监听地址（仅 SSE 模式）        | `127.0.0.1` |
| `--mcp-port`     | MCP 监听端口（仅 SSE 模式）        | `8099`      |
| `--editor-host`  | 编辑器 Forwarder 地址          | `127.0.0.1` |
| `--editor-port`  | 编辑器 Forwarder 端口          | `8100`      |
| `--project`      | `.uproject` 绝对路径，启用 `open_editor` / `close_editor` | 无 |
| `--debug`        | 调试模式（输出详细日志到 stderr）      | 关闭          |
| `--mypy-enabled` | 执行 Python 代码前启用 mypy 类型检查 | 关闭          |

---

## mypy 类型检查（可选）

在 Python 代码执行前自动进行 [mypy](https://mypy-lang.org/) 类型检查，尽早发现类型错误。

### 启用

```ini
# .env
MYPY_ENABLED=true
```

或命令行：`python main.py --mypy-enabled`

> 需要系统 Python 安装 mypy：`pip install mypy`

---

## 故障排除

### 客户端无法连接

- stdio 模式：检查客户端配置中的 `command` 和 `args` 路径是否正确
- SSE 模式：确认已手动运行 `python main.py --transport sse`
- 确认端口未被占用（默认 8099/8100）
- 使用调试模式：`python main.py --transport sse --debug`

### 工具调用失败 / `execute_command` 无返回

- 确认编辑器已完全加载（底部状态栏无"Loading"）
- 确认 Forwarder 正常运行：在编辑器 Python 控制台执行 `from mcp_server import Start; Start.print_status()`
- 检查 `8099` 和 `8100` 端口是否都可访问
- 查看 MCPStandalone 的 stderr 输出（stdio 模式在客户端日志中）

### 端口冲突

修改 `.env`：

```ini
MCP_PORT=8199
EDITOR_PORT=8200
```

重启编辑器并更新客户端配置。

---
