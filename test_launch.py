#!/usr/bin/env python3
"""启动稳定性测试：进程存活 + 是否出现 Application Error 弹窗。

用法:
    python test_launch.py <原版exe> <汉化版exe> [--runs 6] [--settle 14]

为什么要两个都测：PAST 在启动时会加载全部窗体，属性名被破坏才会在此时暴露。
必须**同时**检查"进程还在"和"没有错误弹窗"——进程活着但弹出
`Application Error` 同样是失败。

注意：必须在无残留实例的环境下测试。多个 PAST 抢同一个配置文件会产生假崩溃，
所以每次启动前先清理同族进程。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def _ps(cmd: str) -> str:
    return subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                          capture_output=True, text=True,
                          errors='replace').stdout


def pids() -> list:
    out = _ps("Get-Process | Where-Object { $_.ProcessName -like 'Past5*' "
              "-or $_.MainWindowTitle -match 'Application Error' } | "
              "ForEach-Object { $_.Id }")
    return [l.strip() for l in out.splitlines() if l.strip()]


def error_pids() -> list:
    out = _ps("Get-Process | Where-Object { $_.MainWindowTitle -match "
              "'Application Error' } | ForEach-Object { $_.Id }")
    return [l.strip() for l in out.splitlines() if l.strip()]


def clean() -> None:
    for pid in pids():
        subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
    time.sleep(1.5)


def test(path: str, runs: int, settle: int):
    ok = dialogs = exits = 0
    detail = []
    for k in range(runs):
        clean()
        pr = subprocess.Popen([path])
        time.sleep(settle)
        rc = pr.poll()
        errs = error_pids()
        if rc is None and not errs:
            ok += 1
        else:
            if rc is not None:
                exits += 1
            if errs:
                dialogs += 1
            detail.append({'run': k + 1, 'exit': rc, 'dialogs': len(errs)})
        if pr.poll() is None:
            pr.kill()
            pr.wait()
        for pid in errs:
            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
        time.sleep(0.8)
    clean()
    return ok, runs, dialogs, exits, detail


def main(argv=None):
    ap = argparse.ArgumentParser(description='启动稳定性测试')
    ap.add_argument('src', help='原版 exe')
    ap.add_argument('zh', help='汉化版 exe')
    ap.add_argument('--runs', type=int, default=6)
    ap.add_argument('--settle', type=int, default=14)
    args = ap.parse_args(argv)

    for label, path in (('原版  ', args.src), ('汉化版', args.zh)):
        name = os.path.basename(path)
        if not os.path.exists(path):
            print(f'{label}: 找不到 {path}')
            continue
        ok, tot, d, e, detail = test(path, args.runs, args.settle)
        print(f'{label} ({name}): 干净启动 {ok}/{tot}   '
              f'错误弹窗 {d} 次   提前退出 {e} 次')
        if detail:
            print('   异常明细:', detail)
    return 0


if __name__ == '__main__':
    sys.exit(main())
