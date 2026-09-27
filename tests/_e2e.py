# -*- coding: utf-8 -*-
"""
端到端演练：用假沙箱目录，走完整映射与还原流程（复用 MapperApp 的真实代码路径）。
只操作 %TEMP% 下的沙箱，绝不触碰真实模型目录。
"""
import os
import sys
import shutil
import tempfile
import time
import tkinter as tk
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_models_mapper as M


def build_sandbox():
    base = os.path.join(tempfile.gettempdir(), "mapper_e2e_" + str(int(time.time())))
    repo = os.path.join(base, "E_盤仓库", "models")
    comfy1 = os.path.join(base, "ComfyUITE_A", "ComfyUI")
    comfy2 = os.path.join(base, "ComfyUITE_B", "ComfyUI")
    comfy3 = os.path.join(base, "ComfyUITE_C", "ComfyUI")

    os.makedirs(os.path.join(repo, "checkpoints"))
    os.makedirs(os.path.join(repo, "loras"))
    for n in ("sd_xl.safetensors", "flux.safetensors"):
        with open(os.path.join(repo, "checkpoints", n), "wb") as f:
            f.write(b"0" * 2048)

    # A: 有真实非空 models（应被备份）
    os.makedirs(os.path.join(comfy1, "models", "checkpoints"))
    with open(os.path.join(comfy1, "models", "old.ckpt"), "wb") as f:
        f.write(b"1" * 100)

    # B: 空 models（应被直接移除）
    os.makedirs(os.path.join(comfy2, "models"))

    # C: models 不存在（应直接新建）
    os.makedirs(comfy3)

    return base, repo, [comfy1, comfy2, comfy3]


def main():
    base, repo, comfys = build_sandbox()
    print("沙箱:", base)
    print("仓库:", repo)
    print("=" * 64)

    root = tk.Tk()
    root.withdraw()
    app = M.MapperApp(root)

    # 屏蔽配置文件落盘到真实位置
    app.cfg_path = os.path.join(base, "cfg.json")
    app.log = lambda msg, level="info": print(f"    | {msg}")

    app.repo_var.set(repo)
    app.targets = [{"path": c, "enabled": True} for c in comfys]

    # 自动确认所有弹窗
    yes = mock.patch("tkinter.messagebox.askokcancel", return_value=True)
    yesy = mock.patch("tkinter.messagebox.askyesno", return_value=True)
    info = mock.patch("tkinter.messagebox.showinfo", return_value=None)
    warn = mock.patch("tkinter.messagebox.showwarning", return_value=None)

    with yes, yesy, info, warn:
        print("\n>>> 执行 do_map()")
        app.do_map()

    print("\n--- 映射后校验 ---")
    for c in comfys:
        m = os.path.join(c, "models")
        ok = M.is_reparse_point(m)
        tgt = M.link_target(m)
        names = sorted(os.listdir(m)) if os.path.exists(m) else []
        print(f"  {os.path.basename(os.path.dirname(c)):12s} 链接={ok}  内容={names}")
        assert ok, f"{m} 未成功建立链接"
        assert "checkpoints" in names and "loras" in names, "穿透内容不完整"

    # A 的旧数据必须还在备份里
    a_root = comfys[0]
    baks = [n for n in os.listdir(a_root) if "_backup_" in n]
    print(f"\n--- A 的备份目录: {baks} ---")
    assert baks, "未生成备份！"
    oldf = os.path.join(a_root, baks[0], "old.ckpt")
    assert os.path.isfile(oldf), "备份内原始数据丢失！"
    print("  备份内原始数据完好 ✔")

    # B 原为空目录，应被移除
    b_root = comfys[1]
    b_baks = [n for n in os.listdir(b_root) if "_backup_" in n]
    print(f"--- B 的备份目录（应为空）: {b_baks} ---")
    assert not b_baks, "空目录不该产生备份"

    print("\n>>> 执行 do_unmap() 解除映射")
    with yes, yesy, info, warn:
        app.do_unmap()
    for c in comfys:
        m = os.path.join(c, "models")
        assert not M.is_reparse_point(m), f"{m} 链接未解除"
    print("  所有链接已解除 ✔")

    print("\n>>> 执行 do_restore() 一键还原")
    app.refresh_all()
    with yes, yesy, info, warn:
        app.do_restore()

    a_models = os.path.join(comfys[0], "models")
    assert os.path.isdir(a_models) and not M.is_reparse_point(a_models), "A 未还原成真实目录"
    assert os.path.isfile(os.path.join(a_models, "old.ckpt")), "A 还原后数据不对"
    print("  A 已还原为真实目录且数据完好 ✔")

    # 源仓库必须毫发无损
    assert os.path.isfile(os.path.join(repo, "checkpoints", "sd_xl.safetensors"))
    assert os.path.isfile(os.path.join(repo, "checkpoints", "flux.safetensors"))
    print("  源仓库数据完好 ✔")

    root.destroy()
    shutil.rmtree(base, ignore_errors=True)
    print("=" * 64)
    print("端到端演练全部通过 ✔")


if __name__ == "__main__":
    main()
