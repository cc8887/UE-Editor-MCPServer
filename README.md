# UE-Editor-MCPServer

将UE Editor封装为MCP Server供Agent使用以实现Agent自动化迭代
python新手，欢迎大佬们提各种建议

- 当前版本基于5.5开发 暂时不保证其他版本引擎下的可用性（按道理只要Pyhton版本及PythonScriptPlugin跟5.5一致即可），后续会考虑支持UE5和部分UE4版本
- 目前仅保证Win下稳定
- 需要C++版本的项目，未来会上架商店

## Setup

clone当前项目至项目或者引擎的plugin并编译，引擎启动后会自动启动MCPServer。

需自行保证pip源连接畅通。

## 快速开始

### 1. 安装依赖

在插件根目录下执行：

```cmd
uv sync
```

### 2. 配置端口（可选）

```cmd
copy .env.example .env
```

默认端口：MCP `8099`，Editor Forwarder `8100`。如需修改编辑 `.env` 文件。

### 3. 启动 UE 编辑器

启动编辑器后，C++ 模块自动启动转发服务器（监听 `127.0.0.1:8100`）。

### 4. 启动 MCP 服务器

**stdio 模式（推荐）**：由 MCP 客户端自动拉起，无需手动操作。诊断日志输出到 stderr，不会干扰协议流。在客户端配置中加入：

```json
{
  "mcpServers": {
    "ue-editor": {
      "command": "uv",
      "args": ["run", "--directory", "<插件路径>\\UE-Editor-MCPServer", "python", "main.py"],
      "env": { "MCP_PORT": "8099", "EDITOR_PORT": "8100" }
    }
  }
}
```

> 使用系统 Python：`"command": "python"`, `"args": ["<插件路径>\\UE-Editor-MCPServer\\main.py"]`

**SSE 模式**：在单独终端手动启动，然后客户端直连：

```cmd
python main.py --transport sse
```

```json
{
  "mcpServers": {
    "ue-editor": {
      "type": "sse",
      "url": "http://127.0.0.1:8099/SSE"
    }
  }
}
```

> **⚠️ SSE 端点路径必须大写 `/SSE`**，小写 `/sse` 会导致 404。

### 5. 验证

请 AI 助手执行：

```python
import unreal
print("UE Editor MCP Server is working!")
```

---

## 回归测试

插件目录下提供 `test_mcp_client.py`，用于回归 `SSE` / `STDIO` / `both` 三种路径。

### 编辑器归属与自动关闭

- 默认情况下，脚本**不会**启动或关闭 UE 编辑器。
- 传入 `--launch-editor` 后，脚本会自行拉起编辑器，并且只会在测试结束后关闭**这次回归脚本自己启动的编辑器**。
- 如果你是手工打开编辑器再运行回归，脚本不会去关闭该实例。

### 示例

```cmd
python test_mcp_client.py --transport stdio
python test_mcp_client.py --launch-editor --transport stdio
python test_mcp_client.py --launch-editor --transport both
```

> `--transport sse` 或 `--transport both` 仍要求你提前启动 SSE 服务，例如：`python main.py --transport sse`

### 常用参数

- `--launch-editor`：由回归脚本启动并托管编辑器生命周期
- `--editor-exe`：指定编辑器可执行文件路径
- `--uproject`：指定 `.uproject` 路径
- `--editor-start-timeout`：启动后等待 Forwarder 端口就绪的超时时间
- `--editor-shutdown-timeout`：发送退出请求后等待编辑器关闭的超时时间

---

## UE 侧自动化测试方向（本轮仅调研）

当前建议先保留外部 Python harness 作为主回归路径，UE 侧测试后续优先考虑：

1. 参考 `BlueprintLispTests.cpp` 先补基于 `IMPLEMENT_SIMPLE_AUTOMATION_TEST` 的插件自动化测试。
2. 如果需要 PIE / 运行时世界，可复用 `AutoTestPIESession`。
3. `AutomationDriver` / `AutomationDriverTests` 更适合编辑器 UI 工作流，后续采用前应先验证 `NullRHI` / headless 场景的可行性。

---

## 命令行参数

优先级：命令行 > 环境变量 > `.env` > 默认值

| 参数               | 说明                      | 默认值         |
| ---------------- | ----------------------- | ----------- |
| `--transport`    | 传输模式：`stdio`（默认）或 `sse` | `stdio`     |
| `--mcp-host`     | MCP 监听地址（仅 SSE）         | `127.0.0.1` |
| `--mcp-port`     | MCP 端口（仅 SSE）           | `8099`      |
| `--editor-host`  | 编辑器转发地址                 | `127.0.0.1` |
| `--editor-port`  | 编辑器转发端口                 | `8100`      |
| `--debug`        | 调试模式                    | 关闭          |
| `--mypy-enabled` | 启用 mypy 类型检查            | 关闭          |

---

## 架构说明

插件采用 **Forwarder + MCPStandalone 双进程架构**，UE4 和 UE5 统一使用：

```
MCP Client <---> main.py (MCP Server, port 8099) <---> UE Editor (Forwarder, port 8100)
```

- **编辑器内**：MCPForwarder（TCP 转发器），C++ 模块在引擎启动后自动运行
- **外部进程**：MCPStandalone（MCP 服务），由用户启动或客户端自动拉起

UE4 与 UE5 的区别仅在于内置 Python 版本不同（UE4 为 2.7/3.7，UE5 为 3.9+），均走相同的转发模式。

### 手动控制

在 UE 编辑器 Python 控制台中：

```python
from mcp_server import Start
Start.print_status()  # 查看状态
Start.stop()          # 停止
Start.start()         # 启动
```

---

## mypy 类型检查（可选）

在执行 Python 代码前自动进行 [mypy](https://mypy-lang.org/) 类型检查。

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

## 故障排除

**客户端无法连接**

- stdio 模式由客户端自动拉起；SSE 模式需手动运行 `python main.py --transport sse`
- 确认端口（默认 8099）
- 使用调试模式：`python main.py --transport sse --debug`

**工具调用失败**

- 确认编辑器已完全加载，Forwarder 正常运行（端口 8100）
- 在编辑器 Python 控制台手动测试代码
- 使用调试模式查看详情

**端口冲突**

修改 `.env`：

```ini
MCP_PORT=8199
EDITOR_PORT=8200
```

重启服务器并更新客户端配置。

**多项目支持**

为每个项目分配不同端口：

```ini
# 项目 A
MCP_PORT=8099
EDITOR_PORT=8100

# 项目 B
MCP_PORT=8199
EDITOR_PORT=8200
```

客户端配置：

```json
{
  "mcpServers": {
    "ue-project-a": { "type": "sse", "url": "http://127.0.0.1:8099/SSE" },
    "ue-project-b": { "type": "sse", "url": "http://127.0.0.1:8199/SSE" }
  }
}
```

---

## 扩展开发

若想扩展功能请修改 `Content/Python/mcp_server/` 目录下的脚本（主要入口为 `MCPStandalone.py`、`MCPServer.py`）。
