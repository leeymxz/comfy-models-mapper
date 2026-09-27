# -*- coding: utf-8 -*-
"""验证崩溃兜底：故意注入异常，确认会写出崩溃日志（不弹窗）。"""
import os
import sys
import ctypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import comfy_models_mapper as M

logp = os.path.join(ROOT, "崩溃日志.txt")
if os.path.exists(logp):
    os.remove(logp)


def boom():
    raise RuntimeError("这是测试用的假异常")


# 让报告函数无法弹窗（ctypes 置空 -> 走 except 分支），但日志仍要写
M.ctypes = None

orig_main = M.main
M.main = boom
try:
    M.guarded_main()
finally:
    M.main = orig_main

ok = os.path.exists(logp)
print("崩溃日志是否生成:", ok)
if ok:
    content = open(logp, encoding="utf-8").read()
    print("--- 日志内容 ---")
    print(content)
    assert "这是测试用的假异常" in content, "日志里没有异常信息"
    os.remove(logp)
    print(">>> 崩溃兜底工作正常 OK")
else:
    print(">>> 崩溃兜底失效 FAIL")
    sys.exit(1)
