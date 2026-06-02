# UE-Editor-MCPServer

将 Unreal Editor 封装为 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) Server，供 AI Agent 通过 Python 脚本驱动编辑器，实现自动化迭代。

> **状态**：UE 5.6+ 主力开发，Windows 优先稳定，Mac/Linux 基本可用。UE 4.27+ 理论兼容（需 Python 3.7+）。

---

## 架构

插件采用 **Forwarder + MCPStandalone 双进程架构**，UE4 和 UE5 统一使用：

```
MCP Client (Claude/Cursor/CodeBuddy...)
    <-> main.py (MCPStandalone, 端口 8099)
        <-> UE Editor (MCPForwarder TCP 转发器, 端口 8100)
            <-> unreal Python 脚本执行
```

- **编辑器内（C++ 模块）**：`MCPForwarder` TCP 转发器，引擎启动后自动运行，在编辑器主线程 tick 中执行 Python 代码
- **外部进程（Python）**：`MCPStandalone` 实现完整 MCP 协议（SSE / stdio 双模式），通过 TCP 转发器与编辑器通信
- **连接健康检查**：TCP 连接断开 = 编辑器崩溃或关闭，MCPStandalone 会自动检测并可选重连

---

## 快速开始

### 1. 安装 Python 依赖

插件根目录下执行（需要 [uv](https://docs.astral.sh/uv/)）：

```cmd
uv sync
```

> 不使用 uv：`pip install -r requirements.txt`

### 2. 配置端口（可选）

```cmd
copy .env.example .env
```

默认端口：MCP `8099`，Editor Forwarder `8100`。多项目需分配不同端口。

### 3. 启动 UE 编辑器

启动编辑器后，C++ 模块自动启动 Forwarder（监听 `127.0.0.1:8100`）。

### 4. 配置 MCP 客户端

#### stdio 模式（推荐）

由 MCP 客户端自动拉起 `main.py`，无需手动操作。诊断日志输出到 stderr，不干扰协议流。

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)：

```json
{
  "mcpServers": {
    "ue-editor": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\MCP\\Plugins\\UE-Editor-MCPServer", "python", "main.py"],
      "env": { "MCP_PORT": "8099", "EDITOR_PORT": "8100" }
    }
  }
}
```

**Cursor** (`.cursor/mcp.json` 或 `%APPDATA%\Cursor\User\settings.json`)：

```json
{
  "mcpServers": {
    "ue-editor": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\MCP\\Plugins\\UE-Editor-MCPServer", "python", "main.py"]
    }
  }
}
```

预置配置模板见 `mcp_client_configs/` 目录。

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

### 5. 验证

让 AI 助手执行：

```python
import unreal
print("UE Editor MCP Server is working!")
```

---

## MCPStandalone 配置方式

`MCPStandalone` 是运行在外部进程中的 MCP 服务（通过 `main.py` 启动）。配置优先级：**命令行参数 > 环境变量 > `.env` 文件 > 默认值**。

### 1. `.env` 配置文件

在插件根目录创建 `.env`（可复制 `.env.example`）：

```ini
# MCP 服务监听地址（仅 SSE 模式使用）
MCP_HOST=127.0.0.1
MCP_PORT=8099

# UE 编辑器 Forwarder 地址（TCP 转发器）
EDITOR_HOST=127.0.0.1
EDITOR_PORT=8100

# 是否启用 mypy 类型检查
MYPY_ENABLED=false

#（可选）mypy 类型检查时排除的目录（分号分隔）
# MCP_MYPY_EXCLUDE_PATHS=D:\MCP\Plugins\UE-Editor-MCPServer\Content\Python
```

### 2. 环境变量

不创建 `.env` 文件时，可直接设置环境变量（Windows）：

```cmd
set MCP_PORT=8099
set EDITOR_PORT=8100
set MYPY_ENABLED=true
```

macOS/Linux：

```bash
export MCP_PORT=8099
export EDITOR_PORT=8100
export MYPY_ENABLED=true
```

或在 MCP 客户端配置的 `env` 字段中设置（推荐，优先级高于 `.env`）：

```json
{
  "mcpServers": {
    "ue-editor": {
      "command": "uv",
      "args": ["run", "--directory", "D:\\MCP\\Plugins\\UE-Editor-MCPServer", "python", "main.py"],
      "env": {
        "MCP_PORT": "8099",
        "EDITOR_PORT": "8100",
        "MYPY_ENABLED": "true"
      }
    }
  }
}
```

### 3. 命令行参数

手动运行 `main.py` 时传入：

```cmd
# stdio 模式（默认，通常由 MCP 客户端自动拉起）
uv run python main.py --editor-port 8100 --mypy-enabled --debug

# SSE 模式（需手动启动，然后客户端直连）
uv run python main.py --transport sse --mcp-port 8099 --editor-port 8100 --debug
```

全部参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--transport` | 传输模式：`stdio`（默认）或 `sse` | `stdio` |
| `--mcp-host` | MCP 监听地址（仅 SSE 模式） | `127.0.0.1` |
| `--mcp-port` | MCP 监听端口（仅 SSE 模式） | `8099` |
| `--editor-host` | 编辑器 Forwarder 地址 | `127.0.0.1` |
| `--editor-port` | 编辑器 Forwarder 端口 | `8100` |
| `--debug` | 调试模式（输出详细日志到 stderr） | 关闭 |
| `--mypy-enabled` | 执行 Python 代码前启用 mypy 类型检查 | 关闭 |

### 4. 配置优先级

`MCPConfig.py` 按以下顺序读取配置（后面的覆盖前面的）：

1. 命令行参数（最高优先级）
2. 环境变量（`MCP_PORT`、`EDITOR_PORT` 等）
3. `.env` 文件（插件根目录）
4. 默认值（最低优先级）

### 5. 高级：`ConnectionConfig`

如需调整重连间隔、连接超时等运行时参数，修改 `Content/Python/mcp_server/MCPStandalone.py` 中的 `ConnectionConfig` 类：

```python
@dataclass
class ConnectionConfig:
    reconnect_interval: float = 2.0      # 重连间隔（秒）
    connect_timeout: float = 5.0         # 连接超时（秒）
    request_timeout: float = 86400.0     # 请求超时（秒），默认 24 小时
    recv_buffer_size: int = 65536        # 接收缓冲区大小（字节）
```

> 当前 `ConnectionConfig` 仅支持代码方式修改，未暴露为命令行参数。

---

## 可用工具

| 工具名 | 说明 |
|--------|------|
| `execute_command` | 在编辑器主线程执行任意 Python 代码，返回输出/错误 |
| `excute_file` | 执行指定的 `.py` 文件路径（拼写保持兼容） |
| `get_editor_state` | 获取与编辑器的 TCP 连接状态 |
| `get_imported_modules` | 获取编辑器 Python 环境中已导入的模块列表（用于 mypy 类型检查） |

---

## C++ 模块功能

`MCPServer` C++ 模块（`Source/MCPServer/`）提供以下编辑器内能力：

### 日志捕获

- `MCPLogCaptureDevice`：自定义 `FOutputDevice`，可捕获编辑器日志输出供 Python 侧读取
- 控制台变量 `MCP.LogCapture` 控制开关
- Python 侧通过 `unreal.MCPEditorLibrary` 获取捕获的日志

### 属性变更监听

- 通过事务系统（`GEditor->Trans`）监听 UObject 属性变更
- 记录属性变更前后的数值，供 AI Agent 理解操作效果
- 控制台变量 `MCP.PropertyChangeListener` 控制开关

### GameplayTag 管理

`UMCPEditorLibrary` 静态方法：

- `CreateGameplayTag(TagName)` — 创建新的 Gameplay Tag
- `DoesGameplayTagExist(TagName)` — 检查 Tag 是否存在

### 教学会话（Teaching Session）

- `FMCPTeachingSessionManager`：记录 Agent 操作序列，用于生成教学数据
- 控制台命令 `MCP.StartTeaching [SessionName]` / `MCP.StopTeaching`
- 记录事件通过 `RecordTeachingEvent` 写入会话

---

## 命令行参数

优先级：命令行 > 环境变量 > `.env` > 默认值

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--transport` | 传输模式：`stdio`（默认）或 `sse` | `stdio` |
| `--mcp-host` | MCP 监听地址（仅 SSE） | `127.0.0.1` |
| `--mcp-port` | MCP 端口（仅 SSE） | `8099` |
| `--editor-host` | 编辑器 Forwarder 地址 | `127.0.0.1` |
| `--editor-port` | 编辑器 Forwarder 端口 | `8100` |
| `--debug` | 调试模式（更详细日志） | 关闭 |
| `--mypy-enabled` | 执行前启用 mypy 类型检查 | 关闭 |
| `--teaching` | 启用教学会话记录 | 关闭 |

---

## mypy 类型检查（可选）

在执行 Python 代码前自动进行 [mypy](https://mypy-lang.org/) 类型检查，尽早发现类型错误。

### 启用

```ini
# .env
MYPY_ENABLED=true
```

或命令行：`python main.py --mypy-enabled`

### 原理

1. Agent 提交 Python 代码
2. 获取编辑器已导入模块，拼接为完整文件
3. 运行 mypy 检查
4. 通过后才发送到编辑器执行；失败则直接返回错误

> 需要系统 Python 安装 mypy：`pip install mypy`

---

## 回归测试

插件目录下提供 `test_mcp_client.py`，用于回归 `sse` / `stdio` / `both` 三种路径，不依赖 Unreal Engine。

### 编辑器生命周期

- 默认：脚本**不会**启动或关闭 UE 编辑器（需手动启动）
- `--launch-editor`：脚本自行拉起编辑器，测试结束后仅关闭自己启动的实例

### 示例

```cmd
python test_mcp_client.py                          # 测试两种传输模式
python test_mcp_client.py --transport stdio        # 仅 stdio
python test_mcp_client.py --transport sse          # 仅 SSE（需先手动启动 SSE 服务）
python test_mcp_client.py --launch-editor --transport stdio
python test_mcp_client.py --test ping              # 仅 ping 测试
python test_mcp_client.py --test exec              # 仅 execute_command
```

### 常用参数

- `--launch-editor`：由回归脚本启动并托管编辑器生命周期
- `--editor-exe`：指定编辑器可执行文件路径
- `--uproject`：指定 `.uproject` 路径
- `--editor-start-timeout`：启动后等待 Forwarder 端口就绪的超时（秒）
- `--editor-shutdown-timeout`：发送退出请求后等待编辑器关闭的超时（秒）

---

## 手动控制（编辑器 Python 控制台）

```python
from mcp_server import Start

Start.print_status()  # 查看 Forwarder 状态
Start.stop()          # 停止 Forwarder
Start.start()         # 启动 Forwarder
Start.reload()        # 重新加载 mcp_server 模块并重启
```

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

### 多项目支持

为每个项目分配不同端口：

```ini
# 项目 A
MCP_PORT=8099
EDITOR_PORT=8100

# 项目 B
MCP_PORT=8199
EDITOR_PORT=8200
```

---

## 扩展开发

核心 Python 代码位于 `Content/Python/mcp_server/`：

| 文件 | 说明 |
|------|------|
| `MCPCore.py` | 公共核心：依赖导入检查、工具定义、执行结果数据类（不依赖 `unreal`） |
| `MCPConfig.py` | 配置管理：`.env` / 环境变量 / 默认值三层优先级 |
| `MCPForwarder.py` | 编辑器内 TCP 转发器（由 C++ 模块 tick 驱动） |
| `MCPStandalone.py` | 外部 MCP 服务进程（SSE / stdio） |
| `MCPServer.py` | 编辑器内 MCP 服务（已弃用，保留兼容） |
| `Manager.py` | 异步事件管理器（适配 UE 编辑器 tick） |
| `CustomEventLoop.py` | Windows 自定义事件循环 |
| `Start.py` | 统一启动入口 |

添加新工具：在 `MCPCore.py` 中定义 `ToolDefinition`，在 `MCPStandalone.py` 中注册 `call_tool` 处理器。

---

## UE 侧自动化测试

当前回归测试以外部 Python harness（`test_mcp_client.py`）为主。UE 侧测试后续方向：

1. 基于 `IMPLEMENT_SIMPLE_AUTOMATION_TEST` 的插件自动化测试（参考 `BlueprintLispTests.cpp`）
2. 需要 PIE / 运行时世界时，复用 `AutoTestPIESession`
3. `AutomationDriver` 适合编辑器 UI 工作流，采用前需验证 `NullRHI` / headless 可行性

---

## 许可证

TODO：补充许可证信息。
