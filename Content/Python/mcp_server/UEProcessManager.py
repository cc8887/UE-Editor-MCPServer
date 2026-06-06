"""
UEProcessManager.py - UE 编辑器进程管理

提供 open_editor / close_editor 能力。

功能：
1. 解析 .uproject 中的 EngineAssociation 定位引擎根目录
2. 检测 .sln 与模块 DLL 是否过期，必要时执行 GenerateProjectFiles 与 Build
   - 编译过程使用 idle 心跳监控（无固定总超时），并设有绝对上限保底
3. 启动编辑器进程并等待"就绪信号"
   - 优先：调用方提供的 ready_check 回调（如 TCP ping 编辑器内 MCP Forwarder）
   - 备选：扫描日志中的 "Engine is initialized" / ModularStartUp 完成标记
   - 命中后再等待 settle_seconds 让编辑器稳定，最后返回 READY
4. 优雅关闭并等待进程退出，超时则强杀

注意：
- 仅在 Windows 下经过测试（依赖 .bat 脚本与注册表查询）
- 不包含 UE Python Remote Execution（执行能力由 MCPForwarder 提供）
- 仅供独立进程（MCPStandalone）调用，不应在编辑器内导入
- 所有超时/阈值通过 config 传入，不再暴露给 MCP 客户端
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple, List


# ──────────────────────────────────────────────────────────────────────────────
# 日志（统一输出到 stderr，避免污染 stdio 协议流）
# ──────────────────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# 日志关键字
# ──────────────────────────────────────────────────────────────────────────────

# 引擎就绪信号：UnrealEditor 启动后期会输出 "Engine is initialized"；
# 我们的插件在 ModularStartUp 阶段也会输出 "ModularStartUp" 字样的日志，
# 命中其中任意一个即视为引擎已经启动到可接受 Python 调用的阶段。
READY_PATTERN = re.compile(r"Engine is initialized|ModularStartUp", re.IGNORECASE)
CRASH_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"Fatal error",
        r"LowLevelFatalError",
        r"Assertion failed",
    )
]


# ──────────────────────────────────────────────────────────────────────────────
# 默认超时（仅作 fallback；正常情况下由调用方从 MCPConfig 注入）
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_OPEN_SETTLE_SECONDS = 20
_DEFAULT_OPEN_READY_TIMEOUT = 600
_DEFAULT_COMPILE_IDLE_TIMEOUT = 120
_DEFAULT_COMPILE_MAX_SECONDS = 7200
_DEFAULT_CLOSE_GRACEFUL_TIMEOUT = 120


# ──────────────────────────────────────────────────────────────────────────────
# Engine 根目录解析
# ──────────────────────────────────────────────────────────────────────────────

def resolve_engine_root(assoc: str, uproject_path: Path) -> Path:
    """
    解析 EngineAssociation 字段对应的引擎根目录。

    支持四种格式：
    - 空字符串：引擎与 .uproject 在同一仓库（in-tree 构建）
    - GUID（如 {ABCD-...}）：从 HKCU 注册的源码引擎读取
    - 版本号（如 "5.4"）：从 HKLM Launcher 安装路径读取
    - 绝对路径：直接使用
    """
    uproject_path = Path(uproject_path)

    def _has_engine(p: Path) -> bool:
        return (p / "Engine" / "Build" / "Build.version").exists()

    # Case A: empty -> in-tree
    if not assoc or not assoc.strip():
        candidate = uproject_path.parent.parent
        if _has_engine(candidate):
            return candidate
        raise RuntimeError(
            f"EngineAssociation is empty and no engine found at '{candidate}'"
        )

    # Case B: GUID -> HKCU registered build
    if re.match(r'^\{[0-9A-Fa-f\-]+\}$', assoc):
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"SOFTWARE\Epic Games\Unreal Engine\Builds")
            val, _ = winreg.QueryValueEx(key, assoc)
            p = Path(val)
            if _has_engine(p):
                return p
        except OSError:
            pass
        raise RuntimeError(
            f"GUID '{assoc}' not found in HKCU Unreal Engine Builds"
        )

    # Case D: absolute path stored directly (check BEFORE version string)
    looks_like_path = (
        bool(re.match(r'^[A-Za-z]:[/\\]', assoc)) or "/" in assoc or "\\" in assoc
    )
    if looks_like_path:
        p = Path(assoc.replace("/", "\\"))
        if _has_engine(p):
            return p
        raise RuntimeError(
            f"EngineAssociation is a path '{assoc}' but no engine found there"
        )

    # Case C: version string like "5.4" -> HKLM launcher install
    import winreg
    for hive, sub in [
        (winreg.HKEY_LOCAL_MACHINE,
         fr"SOFTWARE\EpicGames\Unreal Engine\{assoc}"),
        (winreg.HKEY_LOCAL_MACHINE,
         fr"SOFTWARE\WOW6432Node\EpicGames\Unreal Engine\{assoc}"),
    ]:
        try:
            key = winreg.OpenKey(hive, sub)
            val, _ = winreg.QueryValueEx(key, "InstalledDirectory")
            p = Path(val)
            if _has_engine(p):
                return p
        except OSError:
            continue
    raise RuntimeError(
        f"Launcher engine '{assoc}' not found in HKLM EpicGames registry"
    )


# ──────────────────────────────────────────────────────────────────────────────
# UEProject - 项目信息封装与编辑器进程操作
# ──────────────────────────────────────────────────────────────────────────────

class UEProject:
    """封装 .uproject 信息以及 open/close editor 操作"""

    def __init__(
        self,
        uproject_path,
        engine_root: Optional[Path] = None,
        *,
        open_settle_seconds: int = _DEFAULT_OPEN_SETTLE_SECONDS,
        open_ready_timeout: int = _DEFAULT_OPEN_READY_TIMEOUT,
        compile_idle_timeout: int = _DEFAULT_COMPILE_IDLE_TIMEOUT,
        compile_max_seconds: int = _DEFAULT_COMPILE_MAX_SECONDS,
        close_graceful_timeout: int = _DEFAULT_CLOSE_GRACEFUL_TIMEOUT,
    ):
        self.uproject_path = Path(uproject_path).resolve()
        if not self.uproject_path.exists():
            raise FileNotFoundError(f"uproject not found: {self.uproject_path}")
        self.project_dir = self.uproject_path.parent
        self.project_name = self.uproject_path.stem

        if engine_root is not None:
            self.engine_root = Path(engine_root)
        else:
            raw = json.loads(self.uproject_path.read_text(encoding="utf-8"))
            self.engine_root = resolve_engine_root(
                raw.get("EngineAssociation", ""), self.uproject_path
            )

        bf = self.engine_root / "Engine" / "Build" / "BatchFiles"
        self.gpf_bat = bf / "GenerateProjectFiles.bat"
        self.build_bat = bf / "Build.bat"

        # 优先使用项目专属 Editor exe（如 LuaToBPVMEditor.exe），避免 UnrealEditor.exe
        # 在重定向时被误判为进程死亡
        _generic_exe = self.engine_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
        self.editor_target_name = self._find_editor_target_name()
        _proj_exe = self.project_dir / "Binaries" / "Win64" / f"{self.editor_target_name}.exe"
        self.editor_exe = _proj_exe if _proj_exe.exists() else _generic_exe
        self.editor_log = self.project_dir / "Saved" / "Logs" / f"{self.project_name}.log"

        # 内部超时（不暴露给 MCP 调用方）
        self.open_settle_seconds = open_settle_seconds
        self.open_ready_timeout = open_ready_timeout
        self.compile_idle_timeout = compile_idle_timeout
        self.compile_max_seconds = compile_max_seconds
        self.close_graceful_timeout = close_graceful_timeout

    def _find_editor_target_name(self) -> str:
        """扫描 Source/*.Target.cs 寻找 TargetType.Editor 目标名，回退为 <ProjectName>Editor"""
        fallback = self.project_name + "Editor"
        src_dir = self.project_dir / "Source"
        if not src_dir.exists():
            return fallback
        for cs in src_dir.glob("*.Target.cs"):
            try:
                text = cs.read_text(encoding="utf-8", errors="replace")
                if "TargetType.Editor" in text or "TargetType .Editor" in text:
                    m = re.search(r"class (\w+)Target\s*:", text)
                    if m:
                        return m.group(1)
            except OSError:
                continue
        return fallback

    # ── stale 检测 ─────────────────────────────────────────────────────────────
    def sln_stale(self) -> bool:
        """sln 文件缺失或比 .uproject 旧 -> 需要 GenerateProjectFiles"""
        sln_files = list(self.project_dir.glob("*.sln"))
        if not sln_files:
            return True
        sln_mtime = max(f.stat().st_mtime for f in sln_files)
        return self.uproject_path.stat().st_mtime > sln_mtime

    def binaries_stale(self) -> bool:
        """模块 DLL 缺失或比任意源文件旧 -> 需要 Build"""
        dll = self.project_dir / "Binaries" / "Win64" / f"UnrealEditor-{self.project_name}.dll"
        if not dll.exists():
            return True
        dll_mtime = dll.stat().st_mtime
        src_root = self.project_dir / "Source"
        if not src_root.exists():
            return False
        for ext in ("*.h", "*.cpp", "*.cs"):
            for f in src_root.rglob(ext):
                try:
                    if f.stat().st_mtime > dll_mtime:
                        return True
                except OSError:
                    continue
        return False

    # ── 进程探测 ──────────────────────────────────────────────────────────────
    def find_editor_pid(self) -> Optional[int]:
        """返回当前项目对应的 UnrealEditor 进程 PID，找不到返回 None"""
        try:
            import psutil
        except ImportError:
            _log("[UEProcessManager] psutil not installed; cannot detect editor process")
            return None

        target = self.project_name.lower()
        uproj_lower = str(self.uproject_path).lower()
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = proc.info.get("name") or ""
                name_lower = name.lower()
                is_editor = (
                    "unrealeditor" in name_lower
                    or self.editor_target_name.lower() in name_lower
                )
                if not is_editor:
                    continue
                cmdline = proc.info.get("cmdline") or []
                joined = " ".join(cmdline).lower()
                if uproj_lower in joined or f"{target}.uproject" in joined:
                    return proc.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    # ── 子进程辅助 ────────────────────────────────────────────────────────────
    @staticmethod
    def run_subprocess(args: List[str], desc: str) -> Tuple[bool, str]:
        """同步运行子进程并流式输出，返回 (是否成功, 末尾日志)"""
        log_lines: List[str] = []
        _log(f"[UEProcessManager] {desc}")
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip()
            _log(f"  {line}")
            log_lines.append(line)
        proc.wait()
        return proc.returncode == 0, "\n".join(log_lines[-40:])

    @staticmethod
    def run_subprocess_with_heartbeat(
        args: List[str],
        desc: str,
        idle_timeout: int,
        max_seconds: int,
    ) -> Tuple[bool, str]:
        """
        运行子进程，使用 idle 心跳监控 + 绝对上限保底。

        返回 (是否成功, 末尾日志)。失败原因可能是：
        - 子进程返回非 0
        - idle_timeout 秒内无任何新日志输出（视为卡死，杀进程）
        - 总耗时超过 max_seconds（视为超时，杀进程）

        编译时长无法预估（小改 10 秒、全量数小时），因此不用固定总超时；
        以"日志活跃度"为准判断是否有进展。
        """
        log_lines: List[str] = []
        _log(f"[UEProcessManager] {desc} (idle_timeout={idle_timeout}s, max={max_seconds}s)")
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout

        # 用单独的线程把 stdout 推到队列，主循环按 idle_timeout 拉取
        line_queue: "queue.Queue[Optional[str]]" = queue.Queue()

        def _reader() -> None:
            try:
                for raw_line in proc.stdout:  # type: ignore[union-attr]
                    line_queue.put(raw_line.rstrip())
            finally:
                line_queue.put(None)  # EOF 哨兵

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        start_time = time.monotonic()
        eof = False
        try:
            while True:
                # 绝对上限保底
                elapsed = time.monotonic() - start_time
                if elapsed > max_seconds:
                    _log(
                        f"[UEProcessManager] {desc} exceeded max {max_seconds}s, killing"
                    )
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return False, "\n".join(
                        log_lines[-40:]
                        + [f"[killed] exceeded max {max_seconds}s"]
                    )

                try:
                    item = line_queue.get(timeout=idle_timeout)
                except queue.Empty:
                    # idle_timeout 秒内无新日志 → 视为卡死
                    if proc.poll() is not None:
                        # 进程已自然退出但 EOF 还没收到，再多读一轮
                        eof = True
                        break
                    _log(
                        f"[UEProcessManager] {desc} stalled: no output for "
                        f"{idle_timeout}s, killing"
                    )
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    return False, "\n".join(
                        log_lines[-40:]
                        + [f"[killed] no output for {idle_timeout}s"]
                    )

                if item is None:
                    eof = True
                    break
                _log(f"  {item}")
                log_lines.append(item)
        finally:
            if not eof:
                # 兜底：若主循环非自然退出，确保 reader 线程能结束
                try:
                    proc.kill()
                except OSError:
                    pass
            reader_thread.join(timeout=2.0)

        proc.wait()
        return proc.returncode == 0, "\n".join(log_lines[-40:])

    # ── 日志扫描 ──────────────────────────────────────────────────────────────
    @staticmethod
    def scan_log_status(lines: List[str]) -> Tuple[str, str]:
        """
        扫描日志行，返回 (状态, 详情)。
        状态：
        - "ready":   已检测到 "Engine is initialized" 且其后无崩溃
        - "crash":   崩溃关键字晚于最后一次 ready
        - "pending": 既未就绪也未崩溃
        """
        last_ready_idx = -1
        last_crash_idx = -1
        last_crash_line = ""
        for i, line in enumerate(lines):
            if READY_PATTERN.search(line):
                last_ready_idx = i
            for cp in CRASH_PATTERNS:
                if cp.search(line):
                    last_crash_idx = i
                    last_crash_line = line.strip()
                    break
        if last_crash_idx > last_ready_idx:
            return "crash", last_crash_line
        if last_ready_idx >= 0:
            return "ready", lines[last_ready_idx].strip()
        return "pending", ""

    # ── 高层操作 ──────────────────────────────────────────────────────────────
    def open_editor(
        self,
        ready_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        确保编辑器完全启动。返回 'READY' 或 'ERROR ...' 字符串。

        流程：
        1. .sln 过期 → GenerateProjectFiles
        2. 模块 DLL 过期 → Build（idle 心跳监控 + 绝对上限保底，编译时长自适应）
        3. 编辑器未运行 → 启动
        4. 等待就绪信号：
           - 优先调用 ready_check 回调（建议传入 TCP ping 编辑器内 MCP Forwarder 的函数）
           - 同时扫描日志，命中 "Engine is initialized" / "ModularStartUp" 也视为就绪
        5. 命中就绪信号后再等待 settle_seconds 秒让编辑器稳定，最后返回 READY

        Args:
            ready_check: 可选的就绪探测回调；返回 True 表示编辑器已可接收命令。
                         缺省时仅依靠日志扫描。
        """
        # step 1: GenerateProjectFiles
        if self.sln_stale():
            if not self.gpf_bat.exists():
                return f"ERROR [generate_project_files] missing: {self.gpf_bat}"
            ok, tail = self.run_subprocess_with_heartbeat(
                [str(self.gpf_bat), str(self.uproject_path), "-game", "-engine"],
                "GenerateProjectFiles",
                idle_timeout=self.compile_idle_timeout,
                max_seconds=self.compile_max_seconds,
            )
            if not ok:
                return f"ERROR [generate_project_files]\n{tail}"

        # step 2: Build（编译耗时不可预估，使用 idle 心跳）
        if self.binaries_stale():
            if not self.build_bat.exists():
                return f"ERROR [build] missing: {self.build_bat}"
            ok, tail = self.run_subprocess_with_heartbeat(
                [str(self.build_bat), self.editor_target_name, "Win64", "Development",
                 str(self.uproject_path)],
                f"Build {self.editor_target_name} Development Win64",
                idle_timeout=self.compile_idle_timeout,
                max_seconds=self.compile_max_seconds,
            )
            if not ok:
                return f"ERROR [build]\n{tail}"

        # step 3: launch if not running
        if self.find_editor_pid() is None:
            if not self.editor_exe.exists():
                return f"ERROR [launch] missing: {self.editor_exe}"
            _log(f"[UEProcessManager] Launching {self.editor_exe.name} ...")
            self.editor_log.parent.mkdir(parents=True, exist_ok=True)
            if self.editor_log.exists():
                try:
                    self.editor_log.write_text("", encoding="utf-8")
                except OSError:
                    pass
            subprocess.Popen(
                [str(self.editor_exe), str(self.uproject_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        # step 4: wait until ready
        return self._wait_until_ready(ready_check)

    def _wait_until_ready(
        self,
        ready_check: Optional[Callable[[], bool]],
    ) -> str:
        """
        轮询直到引擎就绪或超时。命中后再等 settle_seconds，返回 'READY'。

        就绪条件（任一命中即可）：
        - ready_check() 返回 True（首选；通常是 TCP ping 编辑器内 Forwarder）
        - 日志扫描状态为 "ready"

        失败条件：
        - 编辑器进程意外退出
        - 日志扫描状态为 "crash"
        - 超过 open_ready_timeout 秒仍未就绪
        """
        deadline = time.monotonic() + self.open_ready_timeout
        last_lines: List[str] = []
        _log("[UEProcessManager] Waiting for Editor to become ready ...")
        while time.monotonic() < deadline:
            time.sleep(1)

            if self.find_editor_pid() is None:
                # 进程消失：重读日志区分崩溃 vs 未知退出
                if self.editor_log.exists():
                    try:
                        last_lines = self.editor_log.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines()
                    except OSError:
                        pass
                status, detail = self.scan_log_status(last_lines)
                tail = "\n".join(last_lines[-40:])
                if status == "crash":
                    return f"ERROR [launch] Editor crashed: {detail}\n{tail}"
                return f"ERROR [launch] Editor process died unexpectedly\n{tail}"

            # 优先用调用方提供的 ready_check（更可靠：MCP 通了才算 ready）
            if ready_check is not None:
                try:
                    if ready_check():
                        _log(
                            "[UEProcessManager] Ready signal: ready_check passed; "
                            f"settling for {self.open_settle_seconds}s ..."
                        )
                        time.sleep(self.open_settle_seconds)
                        _log("[UEProcessManager] Editor is READY.")
                        return "READY"
                except Exception as e:  # noqa: BLE001 - 探测失败不应阻断流程
                    _log(f"[UEProcessManager] ready_check raised: {e}")

            # 备选：扫描日志
            if self.editor_log.exists():
                try:
                    last_lines = self.editor_log.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    continue
                status, detail = self.scan_log_status(last_lines)
                if status == "ready":
                    _log(
                        "[UEProcessManager] Ready signal: log pattern matched; "
                        f"settling for {self.open_settle_seconds}s ..."
                    )
                    time.sleep(self.open_settle_seconds)
                    _log("[UEProcessManager] Editor is READY.")
                    return "READY"
                if status == "crash":
                    tail = "\n".join(last_lines[-40:])
                    return f"ERROR [launch] Editor crashed: {detail}\n{tail}"

        tail = "\n".join(last_lines[-40:])
        return f"ERROR [launch] Timed out after {self.open_ready_timeout}s\n{tail}"

    def close_editor(self) -> str:
        """优雅关闭编辑器并等待进程退出。返回 'CLOSED' 或 'ERROR ...'。"""
        try:
            import psutil
        except ImportError:
            return "ERROR [close_editor] psutil not installed"

        pid = self.find_editor_pid()
        if pid is None:
            return "CLOSED (editor was not running)"
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            deadline = time.monotonic() + self.close_graceful_timeout
            while time.monotonic() < deadline:
                time.sleep(0.5)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    return "CLOSED"
            proc.kill()
            proc.wait(timeout=10)
            return "CLOSED (force-killed after graceful timeout)"
        except psutil.NoSuchProcess:
            return "CLOSED"
        except Exception as e:
            return f"ERROR [close_editor] {e}"
