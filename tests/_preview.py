# -*- coding: utf-8 -*-
"""离屏渲染界面，生成预览图（不依赖真实窗口被截图）。"""
import os
import sys
import tkinter as tk
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import comfy_models_mapper as M


def snap():
    root = tk.Tk()
    root.geometry("1080x760+60+40")

    app = M.MapperApp(root)
    app.cfg_path = os.path.join(HERE, "_preview_cfg.json")

    # 用真实存在的路径填充，展示实际效果
    app.repo_var.set(r"E:\COMFYUI_dapao\ComfyUI\models")
    app.targets = [
        {"path": r"H:\ComfyUITE_20xx_20260813\ComfyUI", "enabled": True},
        {"path": r"E:\COMFYUI_dapao\ComfyUI", "enabled": True},
        {"path": r"D:\comfyui_torch210cu130 for RTX20xx_20260526\ComfyUI", "enabled": False},
    ]
    app.refresh_all()

    # 填一些模拟日志，展示日志区效果
    app.log_text.delete("1.0", "end")
    demo = [
        "[10:50:01] ✔ 自动检测到模型仓库：E:\\COMFYUI_dapao\\ComfyUI\\models",
        "[10:50:02] ✔ 仓库信息：子目录 106 个 ｜ 文件 989 个 ｜ 约 829.28 GB",
        "[10:50:09] → 开始自动扫描各盘符下的 ComfyUI …",
        "[10:50:14] ✔ 已添加目标：H:\\ComfyUITE_20xx_20260813\\ComfyUI",
        "[10:50:14] ✔ 已添加目标：E:\\COMFYUI_dapao\\ComfyUI",
        "[10:50:15] ✔ 扫描完成，发现 3 个，新增 2 条",
        "[10:51:02] → 开始映射 → E:\\COMFYUI_dapao\\ComfyUI\\models",
        "[10:51:02] [backup] H:\\ComfyUITE_20xx_20260813\\ComfyUI\\models",
        "[10:51:02]   原目录已备份为：models_backup_20260927_105102",
        "[10:51:03]   ✔ 映射成功 → E:\\COMFYUI_dapao\\ComfyUI\\models",
        "[10:51:03] 完成：成功 1 项，失败 0 项",
    ]
    for d in demo:
        app.log_text.insert("end", d + "\n")
    app.set_status("映射完成（成功 1 / 失败 0）")

    root.update_idletasks()
    root.update()

    # 优先用系统截图；失败则改用 tk 自绘导出（不可用时提示）
    out = os.path.join(HERE, "预览界面.png")
    ok = False
    try:
        from PIL import ImageGrab
        x = root.winfo_rootx()
        y = root.winfo_rooty()
        ww = root.winfo_width()
        hh = root.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + ww, y + hh))
        if img.size[0] > 100:
            img.save(out)
            print("已用 ImageGrab 截图:", out, img.size)
            ok = True
    except Exception as e:
        print("ImageGrab 失败:", e)

    if not ok:
        print("无法截图，跳过预览图生成")
        # 退而求其次：至少输出控件布局清单，便于核对
        print("--- 控件布局 ---")
        def walk(w, ind=0):
            print("  " * ind + f"<{w.winfo_class()}> {w.winfo_name()}  {w.winfo_width()}x{w.winfo_height()}")
            for c in w.winfo_children():
                walk(c, ind + 1)
        walk(root)

    root.destroy()


if __name__ == "__main__":
    snap()
