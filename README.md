# UE-Editor-MCPServer

将 Unreal Editor 封装为 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) Server，供 AI Agent 通过 Python 脚本驱动编辑器，实现自动化迭代。

---

## 快速开始

### 构建与协程工具

配置 `EDITOR_PROJECT` 后，独立 MCP 服务提供 `build_project` 和 `read_artifact`，
无需先启动 Editor。`build_project` 等待完整 Win64 Development Editor 目标构建结束，
返回 JSON：`status`、`exit_code`、`log_path`、`error_lines`。失败会设置 MCP `isError`。
错误行号是构建日志的 1 基行号；退出失败但没有匹配错误行时仍返回 `failed`。
完整日志保存在项目 `Saved/Logs/MCPBuild/<id>/`，成功无需再次读日志。

`read_artifact(path, start_line=1, line_count=40)` 仅读取配置项目内部的文件，最多
200 行、16000 字符。按 `error_lines` 定位诊断。新增/删除源码被目标缓存遗漏时可调用
`build_project(refresh_makefile=true)`：只备份该目标的项目本地 Makefile.bin，保留
对象文件和 DDC。构建前必须关闭该项目 Editor；它不替代插件产物版本审计。

`open_editor` 成功返回以 `READY` 开头，下一行 JSON 附带可直接提交的最小协程示例。
启动进程隔离 stdin，避免继承 MCP stdio 输入造成 Python 初始化等待。
READY 要求实际 MCP ping 成功，引擎初始化日志不会提前结束 MCP 就绪等待。
`execute_command` 和 `excute_file` 支持顶层 `async def main()`：等待期间由 Editor
Tick 推进，结束后返回 JSON 可序列化的结果。同步脚本继续按原有方式执行。

```python
import asyncio
import unreal

async def main():
    await asyncio.sleep(0.5)
    return {"pie_running": unreal.EditorLevelLibrary.get_game_world() is not None}
```

原生日志捕获持续到协程结束。长日志落盘，但结果摘要仍直接返回；通过日志路径按需
读取小范围。调用方断开或执行超时会取消任务，清理应放在 `finally` 中，不要启动
脱离当前请求的后台任务后立即报告完成。`MCP_EXECUTION_TIMEOUT` 是 Editor 侧环境变量，
默认 86400 秒；它不能中断阻塞主线程的同步代码，脚本必须使用条件式异步等待。
客户端请求超时、宿主外层提前返回阈值和 Editor 执行超时是独立设置。

无引擎单元测试：`python Tests/test_project_tools.py`、`python Tests/test_ue_process_manager.py`。
真实验证：`python Tests/smoke_project_tools.py --project <Game.uproject> --output <new-directory>`。
项目应加载本仓库 Python 模块；该测试通过实际 stdio MCP 构建、启动、验证协程、检查
错误恢复并关闭 Editor。可用 `--test-script` 指定返回 `passed`、`pie_stopped` 摘要的核心测试。

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
