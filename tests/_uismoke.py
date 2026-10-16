# -*- coding: utf-8 -*-
"""GUI 冒烟测试：不起 mainloop，只验证界面能建起来、各回调不炸。"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import comfy_models_mapper as M  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


def main():
    root = M.tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except M.tk.TclError:
        pass

    app = M.MapperApp(root)
    check("主界面构建成功", app.root is root)
    check("工具栏有「整理入库 / 查重」入口",
          any("整理" in str(b.cget("text")) for b in _buttons(app.root)))

    tw = M.ToolsWindow(app, root)
    check("工具箱窗口构建成功", tw.win.winfo_exists())
    root.update_idletasks()
    check("两个页签都在",
          [str(t) for t in tw.tab_org.winfo_children()] is not None
          and tw.org_tree is not None and tw.dup_tree is not None)

    # 整理入库：灌一批假数据，验证渲染路径（moves / dups / conflicts 互不重叠）
    m1 = {"path": r"X:\packA\ComfyUI\models\checkpoints\a.safetensors",
          "rel": r"checkpoints\a.safetensors", "size": 4 * 1024 ** 3, "mtime": 1,
          "pack": "packA", "dst": r"E:\repo\checkpoints\a.safetensors", "action": "move"}
    d1 = {"path": r"X:\packA\ComfyUI\models\loras\b.safetensors",
          "rel": r"loras\b.safetensors", "size": 2 * 1024 ** 3, "mtime": 1,
          "pack": "packA", "dst": r"E:\repo\loras\b.safetensors",
          "action": "dup", "twin": r"E:\repo\loras\b.safetensors"}
    c1 = {"path": r"X:\packB\ComfyUI\models\checkpoints\e.safetensors",
          "rel": r"checkpoints\e.safetensors", "size": 1024 ** 3, "mtime": 1,
          "pack": "packB", "dst": r"E:\repo\checkpoints\e.safetensors",
          "action": "conflict"}
    tw._scan_organize_done([m1], [d1], [c1], 2)
    root.update_idletasks()
    check("整理结果渲染 3 行", len(tw.org_tree.get_children()) == 3,
          str(len(tw.org_tree.get_children())))
    check("冲突行默认不勾选",
          tw.org_tree.item(tw.org_tree.get_children()[2], "values")[0] == "☐")
    check("汇总文案包含三项统计",
          all(k in tw.org_summary.cget("text") for k in ("待移动", "冗余副本", "冲突")))

    # 勾选态切换
    iid = tw.org_tree.get_children()[0]
    vals = list(tw.org_tree.item(iid, "values"))
    vals[0] = "☐"
    tw.org_tree.item(iid, values=vals)
    check("勾选列可切换", tw.org_tree.item(iid, "values")[0] == "☐")

    # 查重：灌两组假数据
    groups = [
        {"files": [
            {"path": r"E:\repo\checkpoints\a.safetensors", "rel": "a.safetensors",
             "size": 4 * 1024 ** 3, "mtime": 200},
            {"path": r"X:\packA\ComfyUI\models\checkpoints\a.safetensors",
             "rel": r"checkpoints\a.safetensors", "size": 4 * 1024 ** 3, "mtime": 100},
        ], "keep": r"E:\repo\checkpoints\a.safetensors", "size": 4 * 1024 ** 3,
            "waste": 4 * 1024 ** 3},
        {"files": [
            {"path": r"E:\repo\loras\b.safetensors", "rel": "b.safetensors",
             "size": 1024 ** 3, "mtime": 50},
            {"path": r"X:\packB\ComfyUI\models\loras\b.safetensors",
             "rel": r"loras\b.safetensors", "size": 1024 ** 3, "mtime": 60},
        ], "keep": r"X:\packB\ComfyUI\models\loras\b.safetensors", "size": 1024 ** 3,
            "waste": 1024 ** 3},
    ]
    tw._scan_dupes_done(groups, 4, 2)
    root.update_idletasks()
    check("查重渲染 4 行（2 组 × 2 份）", len(tw.dup_tree.get_children()) == 4)
    keeps = [tw.dup_tree.item(i, "values")[6] for i in tw.dup_tree.get_children()]
    check("每组恰好一个「保留」", keeps.count("保留") == 2, str(keeps))
    check("可释放空间文案正确", "5.00 GB" in tw.dup_summary.cget("text"),
          tw.dup_summary.cget("text"))

    # 删除流程：勾错保留项要拦住
    app.targets = []          # 防止 _organize_done 触发真实扫描
    tw._organize_done(2, 0, 1, {"moved": [], "deleted": [], "failed": []})
    root.update_idletasks()
    check("整理完成回调不报错", True)

    tw._delete_done(3, 0)
    root.update_idletasks()
    check("删除完成回调不报错", True)

    tw.win.destroy()
    root.destroy()
    print("\n" + "=" * 56)
    if FAIL:
        print(f"有 {len(FAIL)} 项未通过：{FAIL}")
        return 1
    print("GUI 冒烟测试全部通过 ✔")
    return 0


def _buttons(w):
    out = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, M.ttk.Button):
                out.append(c)
            walk(c)

    walk(w)
    return out


if __name__ == "__main__":
    sys.exit(main())
