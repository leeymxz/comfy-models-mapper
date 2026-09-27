# -*- coding: utf-8 -*-
"""验证 bat 是否能正确启动 GUI（检查 pythonw 进程是否出现）。"""
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def pythonw_pids():
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq pythonw.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
    )
    txt = out.stdout.decode("gbk", errors="ignore")
    pids = set()
    for line in txt.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


before = pythonw_pids()
print("启动前 pythonw PIDs:", before)

# 用 detached 方式跑 bat，模拟双击
CREFATE_NEW_CONSOLE = 0x00000010
p = subprocess.Popen(
    ["cmd", "/c", "启动工具.bat"],
    cwd=ROOT,
    creationflags=CREFATE_NEW_CONSOLE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

time.sleep(8)

after = pythonw_pids()
new = after - before
print("启动后 pythonw PIDs:", after)
print("新出现的 PID:", new)

if new:
    print("\n>>> 结论: bat 成功启动了 GUI 进程 ✔")
else:
    print("\n>>> 结论: 未发现新的 GUI 进程 ✘")
    if p.poll() is not None:
        print("    bat 已退出，返回码:", p.returncode)

# 清理
for pid in new:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
try:
    p.kill()
except Exception:
    pass
print("已清理测试进程")
