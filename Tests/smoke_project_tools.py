"""Exercise the real stdio server and a configured Editor, without an LLM.

Usage: python Tests/smoke_project_tools.py --project path/Game.uproject
The project must load this checkout's Content/Python/mcp_server in the Editor.
"""
import argparse
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def text(result):
    return '\n'.join(c.text for c in result.content if c.type == 'text')


async def run(args):
    repo = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, EDITOR_PROJECT=str(Path(args.project).resolve()), EDITOR_PORT=str(args.port),
               MYPY_ENABLED='false', OPEN_SETTLE_SECONDS='2', OPEN_READY_TIMEOUT='600',
               MCP_STANDALONE_LOCK_NAME='mcp-smoke-' + str(os.getpid()) + '.lock')
    results = {}
    parameters = StdioServerParameters(command=sys.executable,
        args=[str(repo / 'Content/Python/mcp_server/MCPStandalone.py'), '--editor-port', str(args.port),
              '--project', str(Path(args.project).resolve())], env=env)
    with (output / 'server.log').open('w', encoding='utf-8') as errors:
        async with stdio_client(parameters, errlog=errors) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(minutes=15)) as session:
                await session.initialize()
                tools = await session.list_tools()
                results['tools'] = [t.name for t in tools.tools]
                assert {'build_project', 'read_artifact', 'open_editor', 'close_editor'} <= set(results['tools'])

                async def call(name, arguments):
                    started = time.monotonic()
                    response = await session.call_tool(name, arguments)
                    value = text(response)
                    results.setdefault('calls', []).append(dict(tool=name, seconds=time.monotonic() - started,
                                                               response=value, is_error=response.isError))
                    (output / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
                    return value

                build = json.loads(await call('build_project', {'refresh_makefile': True}))
                assert build['status'] == 'succeeded', build
                editor_requested = False
                try:
                    editor_requested = True
                    opened = await call('open_editor', {})
                    assert opened.startswith('READY'), opened
                    example = json.loads(opened.split('\n', 1)[1])['coroutine_example']
                    value = json.loads((await call('execute_command', example['arguments'])).split('\n\nCaptured', 1)[0])
                    assert value['completed'] and value['ticks_during_await'] > 0
                    error = await call('execute_command', {'code': "import asyncio\nasync def main():\n    await asyncio.sleep(0.1)\n    raise ValueError('MCP_SMOKE_EXPECTED')"})
                    assert 'MCP_SMOKE_EXPECTED' in error
                    assert 'Execution completed' in await call('execute_command', {'code': "import unreal\nunreal.log('MCP_SMOKE_SYNC_RECOVERED')"})
                    if args.test_script:
                        core = await call('excute_file', {'file': str(Path(args.test_script).resolve())})
                        summary = json.loads(core.split('\n\nCaptured', 1)[0])
                        assert summary['passed'] and summary['pie_stopped']
                        results['core'] = summary
                    results['passed'] = True
                finally:
                    if editor_requested:
                        closed = await call('close_editor', {})
                        assert closed.startswith('CLOSED'), closed
    (output / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'passed': results.get('passed'), 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, default=18101)
    parser.add_argument('--test-script')
    asyncio.run(run(parser.parse_args()))
