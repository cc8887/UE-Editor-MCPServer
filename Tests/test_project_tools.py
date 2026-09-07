import asyncio
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Content/Python/mcp_server'))
import ProjectBuild as B
from MCPCore import CodeExecutor, COROUTINE_EXAMPLE, ExecutionResult, types
from MCPForwarder import MCPForwarder, ForwarderState
from MCPStandalone import MCPStandaloneServer
from UEProcessManager import UEProject


class Capture:
    def __init__(self):
        self.enabled = False
        self.logs = []

    def clear_captured_logs(self):
        self.logs.clear()

    def enable_log_capture(self, enabled):
        self.enabled = enabled

    def disable_log_capture(self):
        self.enabled = False

    def get_captured_logs(self):
        return '\n'.join(self.logs)


class BuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_child_success_failure_and_lines(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = SimpleNamespace(project_dir=root, uproject_path=root / 'Game.uproject',
                editor_target_name='GameEditor', compile_max_seconds=10, find_editor_pid=lambda: None)
            for code, exit_code, errors in [("print('up to date')", 0, []),
                    ("print('header'); print('file.cpp(3): error C2065: bad'); print('link: error LNK2001: bad'); raise SystemExit(6)", 6, [2, 3]),
                    ("print('unrecognized failure'); raise SystemExit(4)", 4, [])]:
                with patch.object(B, 'ubt_command', return_value=[sys.executable, '-c', code]):
                    result = await B.build_project(project)
                self.assertEqual(result['exit_code'], exit_code)
                self.assertEqual(result['error_lines'], errors)
                self.assertEqual(result['status'], 'succeeded' if exit_code == 0 else 'failed')
                self.assertTrue(Path(result['log_path']).is_file())
            excerpt = B.read_artifact(project, result['log_path'], 1, 2)
            self.assertEqual(excerpt['lines'][0]['line'], 1)

    async def test_timeout_cancel_and_project_lock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = SimpleNamespace(project_dir=root, uproject_path=root / 'Game.uproject',
                editor_target_name='GameEditor', compile_max_seconds=.1, find_editor_pid=lambda: None)
            with patch.object(B, 'ubt_command', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
                result = await B.build_project(project)
                self.assertEqual(result['status'], 'timed_out')
                project.compile_max_seconds = 30
                task = asyncio.create_task(B.build_project(project))
                await asyncio.sleep(.15)
                with self.assertRaisesRegex(RuntimeError, 'Another MCP build'):
                    await B.build_project(project)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            results = [json.loads(p.read_text()) for p in root.rglob('result.json')]
            self.assertIn('cancelled', [r['status'] for r in results])

    async def test_reject_live_editor(self):
        with self.assertRaisesRegex(RuntimeError, 'Close'):
            await B.build_project(SimpleNamespace(find_editor_pid=lambda: 123))

    def test_bounded_artifact_and_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = SimpleNamespace(project_dir=root)
            file = root / 'out.log'
            file.write_text('one\ntwo\n' + 'x' * 100000, encoding='utf-8')
            self.assertEqual(B.read_artifact(project, file, 2, 1)['lines'], [{'line': 2, 'text': 'two'}])
            self.assertTrue(B.read_artifact(project, file, 3)['truncated'])
            with self.assertRaises(ValueError):
                B.read_artifact(project, root.parent / 'outside.log')
            with self.assertRaises(ValueError):
                B.read_artifact(project, file, line_count=1000)

    def test_ubt_prefers_matching_bundled_runtime_over_apphost(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ubt = root / 'Engine/Binaries/DotNET/UnrealBuildTool'
            ubt.mkdir(parents=True)
            for name in ('UnrealBuildTool.exe', 'UnrealBuildTool.dll'):
                (ubt / name).touch()
            (ubt / 'UnrealBuildTool.runtimeconfig.json').write_text(json.dumps({
                'runtimeOptions': {'framework': {'version': '10.0.0'}}}))
            dotnet = root / 'Engine/Binaries/ThirdParty/DotNet/10.0.1/win-x64/dotnet.exe'
            dotnet.parent.mkdir(parents=True)
            dotnet.touch()
            self.assertEqual(B.ubt_command(SimpleNamespace(engine_root=root)),
                             [str(dotnet), str(ubt / 'UnrealBuildTool.dll')])


class CoroutineTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_span_await_result_and_sync_compatibility(self):
        capture = Capture()
        code = '''import asyncio
async def main():
    capture.logs.append('before')
    await asyncio.sleep(.01)
    assert capture.enabled
    capture.logs.append('after')
    return {'passed': True}
'''
        with patch.object(CodeExecutor, '_get_log_capture', return_value=capture):
            result = await CodeExecutor.execute_code_async(code, {'capture': capture})
            self.assertTrue(result.success)
            self.assertEqual(json.loads(result.output), {'passed': True})
            self.assertEqual(result.logs, 'before\nafter')
            self.assertFalse(capture.enabled)
            result = await CodeExecutor.execute_code_async('value = 1')
            self.assertTrue(result.success)

    async def test_error_timeout_cleanup_and_file(self):
        capture = Capture()
        with patch.object(CodeExecutor, '_get_log_capture', return_value=capture):
            result = await CodeExecutor.execute_code_async("async def main():\n    raise ValueError('expected')")
            self.assertFalse(result.success)
            self.assertFalse(capture.enabled)
            result = await asyncio.wait_for(CodeExecutor.execute_code_async(
                "import asyncio\nasync def main():\n    try:\n        await asyncio.sleep(10)\n    finally:\n        capture.logs.append('cleaned')", {'capture': capture}), .01)
            self.assertFalse(result.success)
            self.assertEqual(result.logs, 'cleaned')
            self.assertFalse(capture.enabled)
            with TemporaryDirectory() as directory:
                path = Path(directory) / 'test.py'
                path.write_text("async def main():\n    return {'file': __file__}", encoding='utf-8-sig')
                result = await CodeExecutor.execute_file_async(str(path))
                self.assertEqual(json.loads(result.output)['file'], str(path))

    async def test_forwarder_busy_ping_disconnect_and_recovery(self):
        forwarder = MCPForwarder()
        # Sockets are hashable and identity-based; object is sufficient for queued requests.
        class Client:
            def close(self):
                pass
        client = Client()
        forwarder._clients[client] = b''
        forwarder._pending_requests = [(client, {'type': 'execute', 'id': 'first',
            'code': 'import asyncio\nasync def main():\n    await asyncio.sleep(10)'})]
        forwarder._process_requests()
        await asyncio.sleep(.01)
        forwarder._pending_requests = [(client, {'type': 'execute', 'id': 'busy', 'code': 'pass'}),
                                       (client, {'type': 'ping', 'id': 'ping'})]
        forwarder._process_requests()
        self.assertEqual(forwarder._state, ForwarderState.EXECUTING)
        self.assertTrue(any(r.get('busy') for _, r in forwarder._pending_responses))
        self.assertTrue(any(r.get('type') == 'pong' for _, r in forwarder._pending_responses))
        task = forwarder._execution_task
        forwarder._close_client(client)
        await task
        await asyncio.sleep(0)
        self.assertEqual(forwarder._state, ForwarderState.IDLE)

    def test_long_logs_keep_result_and_example(self):
        with TemporaryDirectory() as directory:
            text = ExecutionResult(True, output='{"passed": true}', logs='x' * 1000, log_directory=directory).to_text()
            self.assertTrue(text.startswith('{"passed": true}'))
            self.assertEqual(len(list(Path(directory).glob('*.txt'))), 1)
        self.assertIn('async def main', ExecutionResult(True, output='READY\n' + COROUTINE_EXAMPLE).to_text())
        self.assertEqual(json.loads(ExecutionResult(False, data={'status': 'failed', 'exit_code': 6}).to_text()),
                         {'status': 'failed', 'exit_code': 6})


class ToolRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_preserves_success_and_structured_error(self):
        server = MCPStandaloneServer()
        app, _ = server._setup_mcp_app()
        request = types.CallToolRequest(method='tools/call', params=types.CallToolRequestParams(
            name='execute_command', arguments={'code': 'pass'}))
        for success in (True, False):
            data = {'status': 'succeeded' if success else 'failed', 'error_lines': [2]}
            with patch.object(server, '_handle_tool_call', AsyncMock(return_value=ExecutionResult(success, data=data))):
                result = (await app.request_handlers[types.CallToolRequest](request)).root
                self.assertEqual(result.isError, not success)
                self.assertEqual(json.loads(result.content[0].text), data)

    def test_engine_log_cannot_override_mcp_readiness(self):
        project = object.__new__(UEProject)
        project.open_ready_timeout = 10
        project.open_settle_seconds = 0
        with TemporaryDirectory() as directory:
            project.editor_log = Path(directory) / 'Editor.log'
            project.editor_log.write_text('LogInit: Engine is initialized.')
            checks = iter([False, True])
            with patch.object(project, 'find_editor_pid', return_value=123), \
                    patch('UEProcessManager.time.sleep'), \
                    patch('UEProcessManager.time.monotonic', side_effect=[0, 1, 2]):
                self.assertEqual(project._wait_until_ready(lambda: next(checks)), 'READY')
            self.assertEqual(list(checks), [])
            with patch.object(project, 'find_editor_pid', return_value=123), \
                    patch('UEProcessManager.time.sleep'), \
                    patch('UEProcessManager.time.monotonic', side_effect=[0, 1, 11]):
                self.assertIn('Timed out', project._wait_until_ready(lambda: False))

    async def test_build_without_editor_and_disabled_without_project(self):
        server = MCPStandaloneServer()
        self.assertNotIn('build_project', [t.name for t in server.TOOLS])
        self.assertFalse((await server._handle_tool_call('build_project', {})).success)
        server.ue_project = SimpleNamespace(project_dir=Path('.'))
        async def build(project, refresh):
            return {'status': 'succeeded', 'exit_code': 0, 'error_lines': []}
        with patch('MCPStandalone.build_project', build):
            self.assertTrue((await server._handle_tool_call('build_project', {})).success)

    def test_launch_stdin_is_isolated(self):
        project = object.__new__(UEProject)
        with TemporaryDirectory() as directory:
            project.editor_exe = Path(directory) / 'UnrealEditor.exe'
            project.editor_exe.touch()
            project.uproject_path = Path(directory) / 'Game.uproject'
            project.editor_log = Path(directory) / 'Saved/Logs/Game.log'
            with patch.object(project, 'sln_stale', return_value=False), patch.object(project, 'binaries_stale', return_value=False), \
                    patch.object(project, 'find_editor_pid', return_value=None), patch.object(project, '_wait_until_ready', return_value='READY'), \
                    patch('UEProcessManager.subprocess.Popen') as spawn:
                self.assertEqual(project.open_editor(), 'READY')
                self.assertEqual(spawn.call_args.kwargs['stdin'], B.subprocess.DEVNULL)


if __name__ == '__main__':
    unittest.main()
