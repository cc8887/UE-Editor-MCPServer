"""Host-side Editor builds and bounded artifact reads; no Editor connection needed."""
import asyncio
import json
import msvcrt
from pathlib import Path
import re
import subprocess
import time
import uuid

ERROR = re.compile(r'\b(?:fatal\s+)?error(?:\s+(?:C|CS|LNK|MSB|UHT)\d+)?\s*:', re.I)
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def analyze_log(path, exit_code):
    errors = []
    count = 0
    with Path(path).open(encoding='utf-8-sig', errors='replace') as stream:
        for count, line in enumerate(stream, 1):
            if ERROR.search(ANSI.sub('', line)):
                errors.append(count)
    return dict(status='succeeded' if exit_code == 0 else 'failed', exit_code=exit_code,
                error_lines=errors, line_number_base=1, log_line_count=count,
                diagnostic_status='found' if errors else ('not_needed' if exit_code == 0 else 'no_recognized_error_line'))


def ubt_command(project):
    engine = project.engine_root / 'Engine'
    executables = [engine / 'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.exe',
                   engine / 'Binaries/DotNET/UnrealBuildTool.exe']
    dll = engine / 'Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll'
    runtime = dll.with_name('UnrealBuildTool.runtimeconfig.json')
    if not dll.is_file() or not runtime.is_file():
        for executable in executables:
            if executable.is_file():
                return [str(executable)]
        raise FileNotFoundError('UnrealBuildTool executable or runtime configuration not found')
    options = json.loads(runtime.read_text(encoding='utf-8-sig'))['runtimeOptions']
    framework = options.get('framework') or options.get('frameworks', [{}])[0]
    major = framework['version'].split('.')[0]
    candidates = []
    for executable in (engine / 'Binaries/ThirdParty/DotNet').rglob('dotnet.exe'):
        if 'win-x64' in str(executable).lower() and any(
                re.match(r'^' + re.escape(major) + r'\.\d+', part) for part in executable.parts):
            candidates.append(executable)
    if not candidates:
        for executable in executables:
            if executable.is_file():
                return [str(executable)]
        raise FileNotFoundError('No bundled win-x64 dotnet matching UBT runtime ' + major)
    return [str(sorted(candidates)[-1]), str(dll)]


def stop_process_tree(process):
    import psutil
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for item in children + [parent]:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(children + [parent], timeout=10)
    except psutil.NoSuchProcess:
        pass


async def build_project(project, refresh_makefile=False):
    if project.find_editor_pid() is not None:
        raise RuntimeError('Close the configured project Editor before building')
    saved = project.project_dir / 'Saved/Logs/MCPBuild'
    saved.mkdir(parents=True, exist_ok=True)
    # The OS releases this project lock even if the MCP host exits unexpectedly.
    lock = (saved / 'build.lock').open('a+b')
    try:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('Another MCP build is running for this project') from error
        directory = saved / uuid.uuid4().hex
        directory.mkdir()
        log = directory / 'stdout.log'
        command = ubt_command(project) + [project.editor_target_name, 'Win64', 'Development',
            '-Project=' + str(project.uproject_path), '-WaitMutex', '-NoHotReloadFromIDE',
            '-Log=' + str(directory / 'ubt.log')]
        if refresh_makefile:
            for architecture in ('x64', ''):
                cache = project.project_dir / 'Intermediate/Build/Win64' / architecture / project.editor_target_name / 'Development/Makefile.bin'
                if cache.is_file():
                    if project.project_dir.resolve() not in cache.resolve().parents:
                        raise RuntimeError('Refusing to move a build cache outside the project')
                    cache.replace(directory / ('previous-' + (architecture or 'default') + '-Makefile.bin'))
        started = time.monotonic()
        timed_out = False
        with log.open('wb') as output:
            process = await asyncio.create_subprocess_exec(*command, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                await asyncio.wait_for(process.wait(), timeout=project.compile_max_seconds)
            except asyncio.TimeoutError:
                timed_out = True
                await asyncio.to_thread(stop_process_tree, process)
                await process.wait()
            except asyncio.CancelledError:
                await asyncio.to_thread(stop_process_tree, process)
                await process.wait()
                (directory / 'result.json').write_text(json.dumps(dict(status='cancelled',
                    exit_code=process.returncode, log_path=str(log))), encoding='utf-8')
                raise
        result = await asyncio.to_thread(analyze_log, log, process.returncode)
        if timed_out:
            result['status'] = 'timed_out'
        result.update(log_path=str(log), duration_seconds=time.monotonic() - started)
        (directory / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result
    finally:
        lock.close()


def read_artifact(project, path, start_line=1, line_count=40):
    if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
        raise ValueError('start_line must be a positive 1-based integer')
    if not isinstance(line_count, int) or isinstance(line_count, bool) or not 1 <= line_count <= 200:
        raise ValueError('line_count must be between 1 and 200')
    file = Path(path).resolve()
    if project.project_dir.resolve() not in file.parents:
        raise ValueError('Artifact must be inside the configured project')
    rows, characters, truncated = [], 0, False
    with file.open(encoding='utf-8-sig', errors='replace') as stream:
        # Bound individual reads as well as the response, including enormous lines.
        number = 1
        while number < start_line:
            part = stream.readline(16001)
            if not part:
                break
            if part.endswith('\n'):
                number += 1
        while number >= start_line and len(rows) < line_count:
            part = stream.readline(16001 - characters)
            if not part:
                break
            remaining = 16000 - characters
            text = part[:remaining].rstrip('\r\n')
            rows.append(dict(line=number, text=text))
            characters += len(part)
            if characters >= 16000:
                truncated = True
                break
            number += 1
    return dict(path=str(file), start_line=start_line, lines=rows, truncated=truncated)
