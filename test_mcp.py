#!/usr/bin/env python3
"""MCP 接入自检：以真实 MCP 客户端连接本包的 stdio 服务器并调用工具。

用法:
    python test_mcp.py [--exe Past5_zh-CN.exe]

需要 `pip install mcp`。它会启动 `python -m past5loc.mcp_server`，
列出工具，并调用 `past5_verify` 与 `past5_run_command` 验证结果。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:
    print('需要 mcp 包：pip install mcp')
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))


async def run(exe: str) -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'past5loc.mcp_server'],
        cwd=HERE,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f'[OK] MCP 服务器已连接，工具数 = {len(tools.tools)}')
            for t in tools.tools:
                print(f'   mcp__past5loc__{t.name}')

            res = await session.call_tool('past5_verify', {'exe': exe})
            print(f'\n[past5_verify]')
            print(res.content[0].text)

            res = await session.call_tool('past5_run_command',
                                          {'args': ['list', exe, '--limit', '1']})
            payload = json.loads(res.content[0].text)
            print('\n[past5_run_command list]')
            print('  exit_code =', payload['exit_code'])
            first = payload['output'].splitlines()
            print('  首行 =', first[0] if first else '')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='MCP 接入自检')
    ap.add_argument('--exe', default='Past5_zh-CN.exe',
                    help='待审计的可执行文件（默认当前目录的汉化版）')
    args = ap.parse_args(argv)
    path = args.exe if os.path.isabs(args.exe) else os.path.join(HERE, args.exe)
    return asyncio.run(run(path))


if __name__ == '__main__':
    sys.exit(main())
