# -*- coding: utf-8 -*-
"""
ComfyUI 模型目录映射工具 (ComfyUI Models Mapper)
================================================
把多个 ComfyUI 安装目录下的 models 文件夹，统一映射（目录联接 Junction）到
一个真实的模型仓库目录，避免一份 800G+ 的模型在多个整合包里重复占用空间。

核心安全原则：
  1. 只做目录联接 (Junction /mklink /J)，不移动、不复制、不删除任何模型文件。
  2. 目标已是非空真实目录时，必须先"改名备份"（models_backup_时间戳），绝不删除。
  3. 所有写操作先做环境校验，校验不过就不动手。
  4. 提供一键还原（把链接删掉、把备份改回来）。

仅依赖 Python 标准库（tkinter）。无需 pip install。
"""

import os
import sys
import json
import time
import shutil
import hashlib
import subprocess
import threading
import ctypes

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "ComfyUI 模型目录映射工具"
APP_VER = "v1.1"
CONFIG_NAME = "mapper_config.json"

FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Windows 下隐藏 mklink 弹窗
CREATE_NO_WINDOW = 0x08000000


# ============================ 底层能力 ============================

def is_reparse_point(path: str) -> bool:
    """判断路径是否为重解析点（Junction / 符号链接 / 挂载点）。"""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def link_target(path: str):
    """读取链接指向；非链接返回 None。"""
    if not is_reparse_point(path):
        return None
    # os.readlink 对 Junction 返回 \\?\H:\xxx 形式，做下美化
    try:
        raw = os.readlink(path)
    except OSError:
        return "<无法读取>"
    cleaned = raw
    if cleaned.startswith("\\\\?\\"):
        cleaned = cleaned[4:]
    if cleaned.startswith("\\??\\"):
        cleaned = cleaned[4:]
    return cleaned


def link_kind(path: str) -> str:
    """返回 'Junction' / 'Symlink' / '' 便于界面展示。"""
    if not is_reparse_point(path):
        return ""
    try:
        st = os.lstat(path)
    except OSError:
        return "Link"
    attrs = getattr(st, "st_file_attributes", 0)
    try:
        import stat as _stat
        if attrs & getattr(_stat, "FILE_ATTRIBUTE_DEVICE", 0):
            pass
    except Exception:
        pass
    # Python 在 Windows 上对 Junction 不做单独标记，用 readlink 前缀粗略区分
    target = link_target(path) or ""
    return "Junction/链接"


def dir_stats(path: str, max_seconds: float = 6.0):
    """快速统计目录大小与文件数，超时则返回部分结果。
    返回 (bytes, files, complete)
    """
    total = 0
    files = 0
    complete = True
    start = time.time()
    stack = [path]
    while stack:
        if time.time() - start > max_seconds:
            complete = False
            break
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            # 不跟随链接，避免跨盘遍历爆炸
                            if not is_reparse_point(e.path):
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return total, files, complete


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.2f} {u}" if u != "B" else f"{int(f)} B"
        f /= 1024
    return f"{n} B"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def mklink_junction(link_path: str, target_path: str):
    """创建目录联接。普通权限即可（同一卷或用 /J 跨卷均可）。
    返回 (bool, msg)
    """
    # /J 创建目录联接，不需要管理员权限，且不要求目标已存在(但我们要它存在)
    cmd = ["cmd", "/c", "mklink", "/J", link_path, target_path]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception as e:
        return False, f"调用 mklink 失败: {e}"

    out = ""
    for enc in ("gbk", "utf-8", "mbcs"):
        try:
            out = p.stdout.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    err = ""
    try:
        err = p.stderr.decode("gbk", errors="ignore")
    except Exception:
        pass

    if p.returncode == 0 and is_reparse_point(link_path):
        return True, (out or "创建成功").strip()

    # 失败时若报权限问题，尝试用 PowerShell 兜底（New-Item -ItemType Junction）
    detail = (out + " " + err).strip()
    if "拒绝访问" in detail or "Access is denied" in detail or p.returncode != 0:
        ps_cmd = (
            "New-Item -ItemType Junction -Path "
            f"'{link_path}' -Target '{target_path}' -ErrorAction Stop | Out-Null"
        )
        try:
            p2 = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if p2.returncode == 0 and is_reparse_point(link_path):
                return True, "通过 PowerShell 创建成功"
            detail += "\nPowerShell 兜底也失败: " + p2.stderr.decode("gbk", errors="ignore")
        except Exception as e:
            detail += f"\nPowerShell 兜底异常: {e}"

    return False, detail or "未知错误"


def remove_link_only(link_path: str):
    """只删除链接本身，绝不递归删除目标内容。
    返回 (bool, msg)
    """
    if not is_reparse_point(link_path):
        return False, "该路径不是链接，拒绝删除（防止误删数据）"
    # 目录联接用 rmdir（删链接不删目标），不要用 rmtree
    try:
        os.rmdir(link_path)
        return True, "链接已删除"
    except OSError as e:
        # 兜底用 cmd rmdir
        try:
            p = subprocess.run(
                ["cmd", "/c", "rmdir", link_path],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if p.returncode == 0:
                return True, "链接已删除(rmdir)"
            return False, f"删除失败: {e} / {p.stderr.decode('gbk', errors='ignore')}"
        except Exception as e2:
            return False, f"删除失败: {e2}"


def move_dir(src: str, dst: str):
    """同盘改名；跨盘则复制+删除需要用户确认，此处只做同盘 rename，失败返回错误。"""
    try:
        os.rename(src, dst)
        return True, "已改名"
    except OSError as e:
        return False, str(e)


# ============================ 界面 ============================

class MapperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_TITLE} {APP_VER}")
        self.root.geometry("1080x760")
        self.root.minsize(940, 660)

        self.cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_NAME)
        self.targets = []          # 每个元素: {"path": str, "enabled": bool}
        self.repo_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.log_lines = []

        self._build_ui()
        self._load_config()
        self._try_autodetect()
        self.refresh_all()

    # ---------- UI 搭建 ----------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        # ---- 顶部：模型仓库（源） ----
        repo_frame = ttk.LabelFrame(self.root, text=" ① 模型仓库目录（真实存放模型的文件夹，即映射源） ")
        repo_frame.pack(fill="x", **pad)

        row = ttk.Frame(repo_frame)
        row.pack(fill="x", padx=8, pady=8)
        self.repo_entry = ttk.Entry(row, textvariable=self.repo_var)
        self.repo_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self.pick_repo).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="检测信息", command=self.inspect_repo).pack(side="left", padx=(6, 0))

        self.repo_info = ttk.Label(repo_frame, text="未选择", foreground="#666")
        self.repo_info.pack(anchor="w", padx=12, pady=(0, 8))

        # ---- 中部：目标 ComfyUI 列表 ----
        tgt_frame = ttk.LabelFrame(
            self.root,
            text=" ② 要映射的 ComfyUI 安装列表（勾选后点【开始映射】；每条指向自己的 …\\ComfyUI\\models）",
        )
        tgt_frame.pack(fill="both", expand=True, **pad)

        toolbar = ttk.Frame(tgt_frame)
        toolbar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Button(toolbar, text="＋ 添加目录", command=self.add_target).pack(side="left")
        ttk.Button(toolbar, text="✎ 修改选中", command=self.edit_target).pack(side="left", padx=4)
        ttk.Button(toolbar, text="－ 移除选中", command=self.remove_target).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="全选", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(toolbar, text="全不选", command=lambda: self.set_all(False)).pack(side="left", padx=4)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="自动扫描各盘", command=self.autoscan).pack(side="left")
        ttk.Button(toolbar, text="↻ 刷新状态", command=self.refresh_all).pack(side="left", padx=4)

        cols = ("on", "path", "state", "target")
        self.tree = ttk.Treeview(tgt_frame, columns=cols, show="headings", height=9)
        self.tree.heading("on", text="启用")
        self.tree.heading("path", text="ComfyUI 安装目录")
        self.tree.heading("state", text="models 当前状态")
        self.tree.heading("target", text="实际指向")
        self.tree.column("on", width=56, anchor="center", stretch=False)
        self.tree.column("path", width=300, anchor="w")
        self.tree.column("state", width=185, anchor="w")
        self.tree.column("target", width=470, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", lambda e: self.edit_target())

        hint = ttk.Label(
            tgt_frame,
            text="提示：单击「启用」列可快速切换勾选状态；双击整行可修改路径。",
            foreground="#888",
        )
        hint.pack(anchor="w", padx=12, pady=(0, 8))

        # ---- 操作按钮 ----
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", **pad)

        ttk.Button(btn_frame, text="▶ 开始映射（勾选项）", command=self.do_map).pack(side="left")
        ttk.Button(btn_frame, text="■ 解除映射（勾选项）", command=self.do_unmap).pack(side="left", padx=6)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="↩ 一键还原备份", command=self.do_restore).pack(side="left")
        ttk.Button(btn_frame, text="🧹 清理空目录", command=self.do_clean_empty).pack(side="left", padx=6)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="保存配置", command=self.save_config).pack(side="left")
        ttk.Button(btn_frame, text="导出日志", command=self.export_log).pack(side="left", padx=6)
        ttk.Separator(btn_frame, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(btn_frame, text="🗂 整理入库 / 查重", command=self.open_tools).pack(side="left")

        # ---- 日志 ----
        log_frame = ttk.LabelFrame(self.root, text=" 运行日志 ")
        log_frame.pack(fill="both", expand=False, **pad)

        self.log_text = tk.Text(log_frame, height=13, wrap="none", font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y", pady=8, padx=(0, 8))
        self.log_text.configure(yscrollcommand=sb.set)

        # ---- 状态栏 ----
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(
            side="left", fill="x", expand=True, padx=10, pady=4
        )
        admin_txt = "管理员权限：是" if is_admin() else "管理员权限：否（本工具用 Junction，无需管理员）"
        ttk.Label(bar, text=admin_txt, foreground="#666").pack(side="right", padx=10)

    # ---------- 日志 ----------
    def log(self, msg: str, level: str = "info"):
        ts = time.strftime("%H:%M:%S")
        prefix = {"info": "  ", "ok": "✔ ", "warn": "⚠ ", "err": "✘ ", "step": "→ "}.get(level, "  ")
        line = f"[{ts}] {prefix}{msg}"
        self.log_lines.append(line)
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.root.update_idletasks()

    def set_status(self, s: str):
        self.status_var.set(s)
        self.root.update_idletasks()

    # ---------- 配置 ----------
    def _load_config(self):
        if not os.path.exists(self.cfg_path):
            return
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.repo_var.set(cfg.get("repo", ""))
            self.targets = [
                {"path": t.get("path", ""), "enabled": bool(t.get("enabled", True))}
                for t in cfg.get("targets", [])
                if t.get("path")
            ]
            self.log(f"已载入配置：{self.cfg_path}")
        except Exception as e:
            self.log(f"读取配置失败（忽略）：{e}", "warn")

    def save_config(self, silent=False):
        cfg = {
            "repo": self.repo_var.get().strip(),
            "targets": self.targets,
        }
        try:
            with open(self.cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            if not silent:
                self.log(f"配置已保存：{self.cfg_path}", "ok")
                self.set_status("配置已保存")
        except Exception as e:
            self.log(f"保存配置失败：{e}", "err")

    # ---------- 路径推导 ----------
    @staticmethod
    def normalize_target(p: str) -> str:
        """把用户输入的路径统一成 …\\ComfyUI 这一层。
        支持输入：<root>、<root>\\ComfyUI、<root>\\ComfyUI\\models
        """
        p = os.path.normpath(p.strip().strip('"'))
        low = p.lower()
        if low.endswith(os.sep + "models"):
            p = os.path.dirname(p)
            low = p.lower()
        if not low.endswith(os.sep + "comfyui"):
            p = os.path.join(p, "ComfyUI")
        return p

    @staticmethod
    def models_of(comfy_root: str) -> str:
        return os.path.join(comfy_root, "models")

    # ---------- 目标增删改 ----------
    def _ask_dir(self, title):
        return filedialog.askdirectory(title=title)

    def pick_repo(self):
        d = self._ask_dir("选择模型仓库目录（例如 E:\\COMFYUI_dapao\\…\\models）")
        if d:
            self.repo_var.set(os.path.normpath(d))
            self.inspect_repo()

    def inspect_repo(self):
        p = self.repo_var.get().strip().strip('"')
        if not p:
            messagebox.showwarning("提示", "请先选择模型仓库目录")
            return
        if not os.path.isdir(p):
            self.repo_info.configure(text=f"目录不存在：{p}", foreground="#c00")
            self.log(f"仓库目录不存在：{p}", "err")
            return
        if is_reparse_point(p):
            self.repo_info.configure(
                text=f"⚠ 该路径本身是链接 → {link_target(p)}（建议选真实目录）", foreground="#c60"
            )
            self.log(f"仓库目录是链接：{p} -> {link_target(p)}", "warn")
            return

        self.set_status("正在统计仓库大小…")
        total, files, complete = dir_stats(p, max_seconds=8.0)
        subs = 0
        try:
            subs = sum(1 for e in os.scandir(p) if e.is_dir(follow_symlinks=False))
        except OSError:
            pass
        txt = f"子目录 {subs} 个 ｜ 文件 {files} 个 ｜ 约 {human_size(total)}"
        if not complete:
            txt += "  (统计超时，为部分结果)"
        self.repo_info.configure(text=txt, foreground="#060")
        self.log(f"仓库信息：{txt}", "ok")
        self.set_status("就绪")

    def add_target(self):
        d = self._ask_dir("选择 ComfyUI 安装目录（可含或不含末尾的 \\ComfyUI）")
        if not d:
            return
        self._add_target_path(d)

    def _add_target_path(self, d):
        norm = self.normalize_target(d)
        for t in self.targets:
            if os.path.normcase(t["path"]) == os.path.normcase(norm):
                self.log(f"已存在，跳过：{norm}", "warn")
                return False
        self.targets.append({"path": norm, "enabled": True})
        self.log(f"已添加目标：{norm}", "ok")
        self.refresh_all()
        return True

    def edit_target(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中一行")
            return
        idx = self.tree.index(sel[0])
        cur = self.targets[idx]["path"]
        d = self._ask_dir(f"修改目标目录（当前：{cur}）")
        if not d:
            return
        self.targets[idx]["path"] = self.normalize_target(d)
        self.refresh_all()

    def remove_target(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选中要移除的行")
            return
        for i in sorted((self.tree.index(s) for s in sel), reverse=True):
            self.log(f"已从列表移除（不影响磁盘）：{self.targets[i]['path']}", "warn")
            del self.targets[i]
        self.refresh_all()

    def set_all(self, val: bool):
        for t in self.targets:
            t["enabled"] = val
        self.refresh_all()

    def on_tree_click(self, event):
        """点「启用」列切换勾选。"""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        idx = self.tree.index(row)
        self.targets[idx]["enabled"] = not self.targets[idx]["enabled"]
        self.refresh_all()

    # ---------- 自动扫描 ----------
    def autoscan(self):
        self.set_status("正在扫描各盘符下的 ComfyUI …")
        self.log("开始自动扫描（跳过系统盘只读等无关目录）…", "step")
        found = []

        def worker():
            drives = []
            for c in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                root = f"{c}:\\"
                if os.path.exists(root):
                    drives.append(root)

            skip_names = {
                "$recycle.bin", "system volume information", "windows", "program files",
                "program files (x86)", "programdata", "users", "appdata", "node_modules",
                ".git", "__pycache__", "temp", "tmp", "cache",
            }

            for drive in drives:
                # 只扫两层，够用且快
                for depth1 in self._safe_listdir(drive, skip_names):
                    if not os.path.isdir(depth1):
                        continue
                    if os.path.basename(depth1).lower() == "comfyui":
                        models = os.path.join(depth1, "models")
                        if os.path.isdir(models):
                            found.append(depth1)
                            continue
                    for depth2 in self._safe_listdir(depth1, skip_names):
                        if not os.path.isdir(depth2):
                            continue
                        if os.path.basename(depth2).lower() == "comfyui":
                            models = os.path.join(depth2, "models")
                            if os.path.isdir(models):
                                found.append(depth2)
            self.root.after(0, self._autoscan_done, found)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _safe_listdir(d, skip_names):
        out = []
        try:
            with os.scandir(d) as it:
                for e in it:
                    n = e.name.lower()
                    if n in skip_names or n.startswith("$"):
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            out.append(e.path)
                    except OSError:
                        pass
        except OSError:
            pass
        return out

    def _autoscan_done(self, found):
        added = 0
        for f in sorted(set(found)):
            if self._add_target_path(f):
                added += 1
        self.log(f"扫描完成，发现 {len(set(found))} 个，新增 {added} 条", "ok")
        self.set_status(f"扫描完成，新增 {added} 条")
        self.refresh_all()

    # ---------- 状态刷新 ----------
    def refresh_all(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

        for t in self.targets:
            path = t["path"]
            m = self.models_of(path)
            if not os.path.exists(path):
                state, actual = "✘ 安装目录不存在", ""
                self.tree.insert("", "end", values=(
                    "☑" if t["enabled"] else "☐", path, state, actual))
                continue

            if not os.path.exists(m):
                state, actual = "— models 不存在", ""
            elif is_reparse_point(m):
                tgt = link_target(m)
                same = (self.repo_var.get().strip() and
                        os.path.normcase(os.path.normpath(tgt or "")) ==
                        os.path.normcase(os.path.normpath(self.repo_var.get().strip())))
                state = "✔ 已映射" + ("" if same else "（指向其它）")
                actual = tgt or ""
            else:
                try:
                    n = sum(1 for _ in os.scandir(m))
                    sz, fc, _ = dir_stats(m, max_seconds=1.5)
                    state = f"● 真实目录（{n} 项 / {human_size(sz)}）"
                except OSError:
                    state = "● 真实目录"
                actual = ""

            self.tree.insert("", "end", values=(
                "☑" if t["enabled"] else "☐", path, state, actual))

    # ---------- 校验 ----------
    def validate(self, require_repo=True):
        repo = self.repo_var.get().strip().strip('"')
        if require_repo:
            if not repo:
                messagebox.showwarning("校验失败", "请先选择「模型仓库目录」")
                return None
            if not os.path.isdir(repo):
                messagebox.showerror("校验失败", f"模型仓库目录不存在：\n{repo}")
                return None
            if is_reparse_point(repo):
                if not messagebox.askyesno(
                    "注意",
                    f"你选择的仓库目录本身是一个链接：\n{repo} → {link_target(repo)}\n\n"
                    "继续使用可能导致链式链接，建议选真实目录。仍要继续吗？",
                ):
                    return None

        chosen = [t for t in self.targets if t["enabled"]]
        if not chosen:
            messagebox.showwarning("校验失败", "请至少勾选一个 ComfyUI 安装目录")
            return None

        for t in chosen:
            root = t["path"]
            if not os.path.isdir(root):
                messagebox.showerror("校验失败", f"安装目录不存在：\n{root}")
                return None
            m = self.models_of(root)
            # 防止把自己映射到自己
            if os.path.normcase(os.path.normpath(m)) == os.path.normcase(os.path.normpath(repo)):
                messagebox.showerror(
                    "校验失败",
                    f"目标与源是同一个目录，无需映射：\n{m}",
                )
                return None
            # 防止出现互相映射成环
            if is_reparse_point(m):
                tgt = link_target(m)
                if tgt and os.path.normcase(os.path.normpath(tgt)) == os.path.normcase(os.path.normpath(repo)):
                    self.log(f"已是指向该仓库的链接，跳过：{m}", "warn")
        return repo, chosen

    # ---------- 核心：映射 ----------
    def do_map(self):
        v = self.validate()
        if not v:
            return
        repo, chosen = v

        plan = []
        for t in chosen:
            m = self.models_of(t["path"])
            if is_reparse_point(m):
                tgt = link_target(m)
                if tgt and os.path.normcase(os.path.normpath(tgt)) == os.path.normcase(os.path.normpath(repo)):
                    continue  # 已正确映射，跳过
                plan.append(("relink", m, tgt))
            elif os.path.exists(m):
                try:
                    empty = (not any(os.scandir(m)))
                except OSError:
                    empty = False
                if empty:
                    plan.append(("empty", m, None))
                else:
                    plan.append(("backup", m, None))
            else:
                plan.append(("new", m, None))

        if not plan:
            self.log("所有勾选项都已正确映射，无需操作。", "ok")
            messagebox.showinfo("完成", "所有勾选项都已经指向该仓库，无需重复操作。")
            return

        # 生成确认清单
        lines = [f"模型仓库（源）：\n  {repo}\n", "即将执行的操作：\n"]
        for kind, m, tgt in plan:
            if kind == "new":
                lines.append(f"  • [新建链接] {m}")
            elif kind == "empty":
                lines.append(f"  • [替换空目录] {m}   （空目录将被移除后建链接）")
            elif kind == "backup":
                lines.append(f"  • [改名备份后建链接] {m}\n      备份为：{m}_backup_<时间戳>")
            elif kind == "relink":
                lines.append(f"  • [改指向] {m}\n      原指向：{tgt}\n      新指向：{repo}")

        lines.append("\n说明：本操作不移动、不复制、不删除任何模型文件。")
        if not messagebox.askokcancel("请确认操作清单", "\n".join(lines), icon="question"):
            self.log("用户取消了映射操作。", "warn")
            return

        self.set_status("正在映射…")
        ok_cnt = err_cnt = 0
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.log("=" * 62, "step")
        self.log(f"开始映射 → {repo}", "step")

        for kind, m, old_tgt in plan:
            parent = os.path.dirname(m)
            self.log(f"[{kind}] {m}")

            if kind == "new":
                pass  # 直接建

            elif kind == "empty":
                try:
                    os.rmdir(m)  # 只删空目录，非空会抛错，安全
                    self.log("  已移除空目录 models", "info")
                except OSError as e:
                    self.log(f"  空目录移除失败，跳过：{e}", "warn")
                    err_cnt += 1
                    continue

            elif kind == "backup":
                bak = f"{m}_backup_{stamp}"
                if os.path.exists(bak):
                    bak = f"{m}_backup_{stamp}_{int(time.time() % 1000)}"
                good, msg = move_dir(m, bak)
                if not good:
                    # 同盘 rename 失败（极少见，可能是被占用）→ 尝试复制模式需用户确认
                    self.log(f"  改名失败：{msg}", "err")
                    if messagebox.askyesno(
                        "改名失败",
                        f"无法把\n{m}\n改名为\n{bak}\n\n原因：{msg}\n\n"
                        "是否跳过这一项，继续处理其它目录？",
                    ):
                        err_cnt += 1
                        continue
                    else:
                        err_cnt += 1
                        continue
                self.log(f"  原目录已备份为：{os.path.basename(bak)}", "info")

            elif kind == "relink":
                # 先把旧链接改名（不删指向的数据）再建新链接
                bak = f"{m}_linkbak_{stamp}"
                good, msg = move_dir(m, bak)
                if not good:
                    self.log(f"  旧链接改名失败：{msg}", "warn")
                else:
                    self.log(f"  旧链接已备份为：{os.path.basename(bak)}", "info")

            good, msg = mklink_junction(m, repo)
            if good and is_reparse_point(m):
                self.log(f"  ✔ 映射成功 → {repo}", "ok")
                ok_cnt += 1
            else:
                self.log(f"  ✘ 映射失败：{msg}", "err")
                err_cnt += 1
                # 失败则尝试把备份改回来，保持原状
                if kind in ("backup", "relink"):
                    bak_candidates = [
                        f"{m}_backup_{stamp}", f"{m}_linkbak_{stamp}",
                    ]
                    for bc in bak_candidates:
                        if os.path.exists(bc) and not os.path.exists(m):
                            g2, m2 = move_dir(bc, m)
                            self.log(
                                f"  已尝试回滚：{'成功' if g2 else '失败 ' + m2}",
                                "warn" if g2 else "err",
                            )

        self.log(f"完成：成功 {ok_cnt} 项，失败 {err_cnt} 项", "ok" if err_cnt == 0 else "warn")
        self.set_status(f"映射完成（成功 {ok_cnt} / 失败 {err_cnt}）")
        self.refresh_all()
        self.save_config(silent=True)

        if err_cnt == 0:
            messagebox.showinfo("完成", f"映射完成，成功 {ok_cnt} 项。\n请重启 ComfyUI 生效。")
        else:
            messagebox.showwarning(
                "部分完成",
                f"成功 {ok_cnt} 项，失败 {err_cnt} 项。\n详见运行日志。",
            )

    # ---------- 解除映射 ----------
    def do_unmap(self):
        chosen = [t for t in self.targets if t["enabled"]]
        if not chosen:
            messagebox.showwarning("提示", "请先勾选要解除映射的项")
            return

        links = []
        for t in chosen:
            m = self.models_of(t["path"])
            if is_reparse_point(m):
                links.append(m)
        if not links:
            messagebox.showinfo("提示", "勾选项中没有处于映射状态的目录")
            return

        if not messagebox.askokcancel(
            "确认解除映射",
            "将删除以下 models 链接（不会删除链接指向的真实模型文件）：\n\n"
            + "\n".join("  • " + x for x in links)
            + "\n\n解除后这些 ComfyUI 会失去模型。是否继续？",
            icon="warning",
        ):
            return

        self.log("=" * 62, "step")
        self.log("开始解除映射", "step")
        ok = err = 0
        for m in links:
            good, msg = remove_link_only(m)
            if good:
                self.log(f"  ✔ 已解除：{m}", "ok")
                ok += 1
            else:
                self.log(f"  ✘ 解除失败：{m} → {msg}", "err")
                err += 1
        self.log(f"解除完成：成功 {ok}，失败 {err}", "ok" if err == 0 else "warn")
        self.refresh_all()
        self.set_status(f"解除映射完成（成功 {ok}）")

    # ---------- 一键还原备份 ----------
    def do_restore(self):
        chosen = [t for t in self.targets if t["enabled"]]
        if not chosen:
            messagebox.showwarning("提示", "请先勾选要还原的项")
            return
        if not self.repo_var.get().strip():
            pass

        candidates = []
        for t in chosen:
            root = t["path"]
            if not os.path.isdir(root):
                continue
            try:
                for name in os.listdir(root):
                    if "_backup_" in name or "_linkbak_" in name:
                        full = os.path.join(root, name)
                        if os.path.isdir(full) and not is_reparse_point(full):
                            candidates.append(full)
            except OSError:
                pass

        if not candidates:
            messagebox.showinfo("提示", "没有找到可还原的备份目录（*_backup_* / *_linkbak_*）")
            return

        if not messagebox.askokcancel(
            "确认还原",
            "将执行还原：\n"
            "  1. 若当前 models 是链接 → 删除链接本身\n"
            "  2. 把备份目录改回 models\n\n"
            "待还原的备份：\n" + "\n".join("  • " + c for c in candidates),
            icon="warning",
        ):
            return

        self.log("=" * 62, "step")
        self.log("开始一键还原", "step")
        for bak in candidates:
            root = os.path.dirname(bak)
            m = os.path.join(root, "models")
            if is_reparse_point(m):
                good, msg = remove_link_only(m)
                self.log(f"  删除链接 {m}：{'成功' if good else '失败 ' + msg}",
                         "info" if good else "err")
            elif os.path.exists(m):
                self.log(f"  跳过：{m} 已存在真实目录，请手动处理", "warn")
                continue
            good, msg = move_dir(bak, m)
            if good:
                self.log(f"  ✔ 已还原：{os.path.basename(bak)} → models", "ok")
            else:
                self.log(f"  ✘ 还原失败：{msg}", "err")
        self.refresh_all()
        self.set_status("还原完成")

    # ---------- 清理空目录 ----------
    def do_clean_empty(self):
        chosen = [t for t in self.targets if t["enabled"]]
        if not chosen:
            messagebox.showwarning("提示", "请先勾选要处理的项")
            return

        # 找出所有"备份后遗留的、且内部完全为空"的目录
        empties = []
        for t in chosen:
            root = t["path"]
            if not os.path.isdir(root):
                continue
            try:
                for name in os.listdir(root):
                    full = os.path.join(root, name)
                    if not os.path.isdir(full) or is_reparse_point(full):
                        continue
                    sz, fc, complete = dir_stats(full, max_seconds=3.0)
                    if complete and fc == 0 and sz == 0:
                        empties.append(full)
            except OSError:
                pass

        if not empties:
            messagebox.showinfo("提示", "没有发现完全为空的遗留目录")
            return

        if not messagebox.askokcancel(
            "确认清理",
            "以下目录内部【完全为空】（0 文件 0 字节），将被删除：\n\n"
            + "\n".join("  • " + e for e in empties[:30])
            + ("\n  …" if len(empties) > 30 else "")
            + f"\n\n共 {len(empties)} 个。是否继续？",
            icon="warning",
        ):
            return

        for e in empties:
            try:
                shutil.rmtree(e)
                self.log(f"  ✔ 已删除空目录：{e}", "ok")
            except Exception as ex:
                self.log(f"  ✘ 删除失败 {e}：{ex}", "err")
        self.refresh_all()
        self.set_status("清理完成")

    # ---------- 自动检测常见安装 ----------
    def _try_autodetect(self):
        """首次运行且未配置时，自动填入探测到的信息。"""
        if self.repo_var.get() or self.targets:
            return
        guesses = [
            r"E:\COMFYUI_dapao\ComfyUI\models",
        ]
        for g in guesses:
            if os.path.isdir(g) and not is_reparse_point(g):
                self.repo_var.set(g)
                self.log(f"自动检测到模型仓库：{g}", "ok")
                self.inspect_repo()
                break

    # ---------- 整理入库 / 查重 ----------
    def open_tools(self):
        ToolsWindow(self, self.root)

    # ---------- 导出日志 ----------
    def export_log(self):
        if not self.log_lines:
            messagebox.showinfo("提示", "暂无日志")
            return
        p = filedialog.asksaveasfilename(
            title="导出日志",
            defaultextension=".txt",
            initialfile=f"mapper_log_{time.strftime('%Y%m%d_%H%M%S')}.txt",
            filetypes=[("文本文件", "*.txt")],
        )
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"{APP_TITLE} {APP_VER}\n")
                f.write(f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 62 + "\n")
                f.write("\n".join(self.log_lines) + "\n")
            self.log(f"日志已导出：{p}", "ok")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


# ==================== 模型扫描 / 整理入库 / 查重 ====================

# ComfyUI 常见的模型与附带文件格式
MODEL_EXTS = {
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".sft", ".gguf", ".onnx",
    ".pkl", ".th", ".npz", ".npy", ".h5", ".msgpack", ".clip", ".vae",
    ".zip", ".tar", ".7z", ".rar", ".engine", ".trt", ".om", ".param",
    ".model", ".pb", ".tflite", ".mlmodel", ".caffemodel", ".weights",
    ".yaml", ".yml", ".json", ".txt", ".md", ".toml", ".cfg",
}

SAMPLE = 1 * 1024 * 1024          # 采样块 1MB（头/中/尾各一块）
HASH_CHUNK = 8 * 1024 * 1024      # 全量哈希分块


def iter_model_files(models_dir, pack_label="", models_only=True, stop=None):
    """遍历一个 models 目录，产出文件信息。

    不跟随链接（已映射成 Junction 的目录直接跳过），避免把仓库重复算一遍；
    跳过 *_backup_* / *_linkbak_* 这些本工具自己产生的遗留目录。
    注意：传入的根目录本身如果就是链接，直接返回空——否则会把仓库遍历第二遍。
    """
    if is_reparse_point(models_dir):
        return
    base = os.path.normpath(models_dir)
    stack = [base]
    while stack:
        if stop is not None and stop.is_set():
            return
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if is_reparse_point(e.path):
                                continue
                            nm = e.name.lower()
                            if "_backup_" in nm or "_linkbak_" in nm:
                                continue
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            if models_only and os.path.splitext(e.name)[1].lower() not in MODEL_EXTS:
                                continue
                            st = e.stat(follow_symlinks=False)
                            if st.st_size <= 0:
                                continue
                            yield {
                                "path": e.path,
                                "rel": os.path.relpath(e.path, base),
                                "size": st.st_size,
                                "mtime": int(st.st_mtime),
                                "pack": pack_label or base,
                            }
                    except OSError:
                        continue
        except OSError:
            continue


def sample_fingerprint(path: str, size: int):
    """采样指纹：头 SAMPLE + 中 SAMPLE + 尾 SAMPLE；小文件直接读全文。

    相比全量 sha256（几百 GB 模型要跑几小时），每个文件只读约 3MB，
    速度快两个数量级，且几乎不会误判——内容相同的副本指纹必然相同。
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            if size <= SAMPLE * 3:
                h.update(f.read(size))
            else:
                h.update(f.read(SAMPLE))
                f.seek(size // 2)
                h.update(f.read(SAMPLE))
                f.seek(size - SAMPLE)
                h.update(f.read(SAMPLE))
    except OSError:
        return None
    return h.hexdigest()


def full_md5(path: str):
    """全量 MD5。用于对采样指纹命中的副本做最终复核（慢，但零误判）。"""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(HASH_CHUNK)
                if not b:
                    break
                h.update(b)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicate_groups(files, verify_full=False):
    """按 大小分组 → 组内采样指纹比对，返回重复分组列表。

    每个分组: {"files":[...], "keep":路径, "size":字节, "waste":可释放字节}
    """
    by_size = {}
    for it in files:
        by_size.setdefault(it["size"], []).append(it)

    groups = []
    for size, items in by_size.items():
        if len(items) < 2:
            continue
        buckets = {}
        for it in items:
            fp = sample_fingerprint(it["path"], size)
            if fp:
                it["fp"] = fp
                buckets.setdefault(fp, []).append(it)
        for fp, same in buckets.items():
            if len(same) < 2:
                continue
            if verify_full:
                # 复核：全量 MD5 全一致才算真重复
                md5s = {p: full_md5(p) for p in (x["path"] for x in same)}
                by_md5 = {}
                for x in same:
                    m = md5s.get(x["path"])
                    if m:
                        x["md5"] = m
                        by_md5.setdefault(m, []).append(x)
                same = [g for g in by_md5.values() if len(g) > 1]
                for g in same:
                    groups.append(make_group(g, size))
                continue
            groups.append(make_group(same, size))

    groups.sort(key=lambda g: -g["waste"])
    return groups


def make_group(same, size):
    """把一组同指纹文件整理成标准分组结构，并挑出建议保留的那个。"""
    # 建议保留：最近修改 > 路径最短（短路径通常更"正统"）
    same.sort(key=lambda x: (x.get("mtime") or 0, -len(x.get("path") or "")), reverse=True)
    keep = same[0]
    return {
        "files": same,
        "keep": keep["path"],
        "keep_rel": keep.get("rel") or os.path.basename(keep["path"]),
        "size": size,
        "waste": size * (len(same) - 1),
    }


def _fp_of(it):
    """取（或现算）文件指纹，避免同一个文件被反复读盘。"""
    fp = it.get("fp")
    if not fp:
        fp = sample_fingerprint(it["path"], it["size"])
        it["fp"] = fp
    return fp


def plan_consolidation(packs, repo, models_only=True, stop=None):
    """规划"整理入库"。

    packs: [(models_dir, 显示名), ...]
    返回 (moves, dups, conflicts)：
      moves      —— 仓库里没有，需要搬进去的
      dups       —— 仓库里已有一份完全相同的，整合包里的副本属于冗余
      conflicts  —— 同名但内容不同，必须人工确认，绝不动
    """
    repo = os.path.normpath(repo)
    repo_index = {}
    for it in iter_model_files(repo, models_only=models_only, stop=stop):
        repo_index.setdefault(os.path.normcase(it["rel"]), []).append(it)

    moves, dups, conflicts = [], [], []
    for models_dir, label in packs:
        for it in iter_model_files(models_dir, pack_label=label,
                                   models_only=models_only, stop=stop):
            key = os.path.normcase(it["rel"])
            dst = os.path.join(repo, it["rel"])
            existing = repo_index.get(key)
            if not existing:
                rec = dict(it)
                rec.update({"dst": dst, "action": "move"})
                moves.append(rec)
                # 登记进索引时把路径记成【目标路径】并带上指纹——这个文件马上就会被
                # 搬进仓库，后面别的整合包再出现同样内容，对照的应该是仓库里的那一份。
                repo_index.setdefault(key, []).append(
                    dict(it, path=dst, fp=_fp_of(it)))
                continue
            hit = next((e for e in existing if e["size"] == it["size"]), None)
            if hit and _fp_of(hit) and _fp_of(hit) == _fp_of(it):
                rec = dict(it)
                rec.update({"dst": dst, "action": "dup", "twin": hit["path"]})
                dups.append(rec)
            else:
                rec = dict(it)
                rec.update({"dst": dst, "action": "conflict"})
                conflicts.append(rec)
    return moves, dups, conflicts


# ==================== 整理入库 / 查重 窗口 ====================

class ToolsWindow:
    """「整理入库」+「模型查重」工具箱（从主界面打开）。"""

    def __init__(self, app, parent):
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title(f"{APP_TITLE} {APP_VER} — 整理入库 / 模型查重")
        self.win.geometry("1180x760")
        self.win.minsize(960, 620)
        self.win.transient(parent)

        self.stop_evt = threading.Event()
        self.busy = False

        self.dup_records = []      # 查重结果（可变，勾选态跟着变）
        self.move_records = []     # 整理结果

        self._build()

    # ---------- 界面 ----------
    def _build(self):
        pad = {"padx": 10, "pady": 6}

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, **pad)

        self.tab_org = ttk.Frame(nb)
        self.tab_dup = ttk.Frame(nb)
        nb.add(self.tab_org, text="  🗂 整理入库  ")
        nb.add(self.tab_dup, text="  🔍 模型查重  ")

        self._build_org(self.tab_org)
        self._build_dup(self.tab_dup)

        # 底部：进度 + 状态
        bottom = ttk.Frame(self.win)
        bottom.pack(fill="x", side="bottom", padx=10, pady=(0, 10))
        self.prog = ttk.Progressbar(bottom, mode="indeterminate", length=260)
        self.prog.pack(side="left")
        self.tools_status = tk.StringVar(value="就绪")
        ttk.Label(bottom, textvariable=self.tools_status, anchor="w").pack(
            side="left", fill="x", expand=True, padx=(10, 0))

    # ---------- Tab1：整理入库 ----------
    def _build_org(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=8)

        ttk.Label(top, text="把各整合包里「仓库还没有」的模型搬进仓库，并识别出冗余副本。",
                  foreground="#444").pack(side="left")
        ttk.Button(top, text="🔍 扫描分析", command=self.scan_organize).pack(side="right")

        opt = ttk.Frame(parent)
        opt.pack(fill="x", padx=8)
        self.var_models_only = tk.BooleanVar(value=True)
        self.var_verify = tk.BooleanVar(value=False)
        self.var_automap = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="只处理常见模型格式（.safetensors/.ckpt/…）",
                        variable=self.var_models_only).pack(side="left")
        ttk.Checkbutton(opt, text="对重复副本做全量 MD5 复核（更慢，零误判）",
                        variable=self.var_verify).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(opt, text="整理后自动把该整合包映射到仓库",
                        variable=self.var_automap).pack(side="left", padx=(14, 0))

        cols = ("on", "rel", "size", "pack", "action", "dst")
        self.org_tree = ttk.Treeview(parent, columns=cols, show="headings", height=16)
        for c, t, w in (("on", "选", 40), ("rel", "相对路径", 280),
                        ("size", "大小", 90), ("pack", "来源整合包", 210),
                        ("action", "动作", 130), ("dst", "仓库目标", 330)):
            self.org_tree.heading(c, text=t)
            self.org_tree.column(c, width=w, anchor="w",
                                 stretch=False if c != "rel" else True)
        self.org_tree.pack(fill="both", expand=True, padx=8, pady=(6, 4))
        self.org_tree.bind("<Button-1>", lambda e: self._toggle_row(self.org_tree, e, "on"))

        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="全选", command=lambda: self._select_all(self.org_tree, True)).pack(side="left")
        ttk.Button(bar, text="全不选", command=lambda: self._select_all(self.org_tree, False)).pack(side="left", padx=4)
        ttk.Button(bar, text="▶ 开始整理（勾选项）", command=self.run_organize).pack(side="left", padx=(14, 0))
        ttk.Button(bar, text="取消扫描", command=self.cancel_scan).pack(side="left", padx=4)
        self.org_summary = ttk.Label(bar, text="尚未扫描", foreground="#666")
        self.org_summary.pack(side="right")

    # ---------- Tab2：模型查重 ----------
    def _build_dup(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Label(top, text="按大小分组，再对同大小文件做头/中/尾采样指纹比对，找出完全相同的副本。",
                  foreground="#444").pack(side="left")
        ttk.Button(top, text="🔍 开始扫描", command=self.scan_dupes).pack(side="right")

        opt = ttk.Frame(parent)
        opt.pack(fill="x", padx=8)
        self.dup_models_only = tk.BooleanVar(value=True)
        self.dup_verify = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="只扫描常见模型格式", variable=self.dup_models_only).pack(side="left")
        ttk.Checkbutton(opt, text="对每组做全量 MD5 复核（慢，零误判）",
                        variable=self.dup_verify).pack(side="left", padx=(14, 0))

        cols = ("on", "grp", "name", "size", "path", "mtime", "keep")
        self.dup_tree = ttk.Treeview(parent, columns=cols, show="headings", height=16)
        for c, t, w in (("on", "选", 40), ("grp", "组", 36), ("name", "文件名", 220),
                        ("size", "大小", 90), ("path", "路径", 400),
                        ("mtime", "修改时间", 140), ("keep", "建议", 60)):
            self.dup_tree.heading(c, text=t)
            self.dup_tree.column(c, width=w, anchor="w")
        self.dup_tree.pack(fill="both", expand=True, padx=8, pady=(6, 4))
        self.dup_tree.bind("<Button-1>", lambda e: self._toggle_row(self.dup_tree, e, "on"))

        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="全选", command=lambda: self._select_all(self.dup_tree, True)).pack(side="left")
        ttk.Button(bar, text="全不选", command=lambda: self._select_all(self.dup_tree, False)).pack(side="left", padx=4)
        ttk.Button(bar, text="🗑 删除选中副本", command=self.run_delete_dupes).pack(side="left", padx=(14, 0))
        ttk.Button(bar, text="取消扫描", command=self.cancel_scan).pack(side="left", padx=4)
        self.dup_summary = ttk.Label(bar, text="尚未扫描", foreground="#666")
        self.dup_summary.pack(side="right")

    # ---------- 通用小工具 ----------
    def _toggle_row(self, tree, event, col):
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != f"#{tree['columns'].index(col) + 1}":
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        vals = list(tree.item(row, "values"))
        vals[0] = "☐" if vals[0] == "☑" else "☑"
        tree.item(row, values=vals)

    def _select_all(self, tree, val):
        for iid in tree.get_children():
            vals = list(tree.item(iid, "values"))
            vals[0] = "☑" if val else "☐"
            tree.item(iid, values=vals)

    def set_busy(self, on):
        self.busy = on
        try:
            if on:
                self.prog.start(12)
            else:
                self.prog.stop()
        except Exception:
            pass

    def cancel_scan(self):
        if self.busy:
            self.stop_evt.set()
            self.tools_status.set("已请求取消，正在停止…")

    def log(self, msg, level="info"):
        self.app.log(msg, level)

    # ---------- 扫描：整理入库 ----------
    def scan_organize(self):
        if self.busy:
            return
        repo = self.app.repo_var.get().strip().strip('"')
        if not repo or not os.path.isdir(repo):
            messagebox.showwarning("提示", "请先在主界面选择「模型仓库目录」")
            return
        if is_reparse_point(repo):
            messagebox.showerror("提示", f"仓库目录本身是链接，请改选真实目录：\n{repo}")
            return

        packs = []
        for t in self.app.targets:
            if not t.get("enabled"):
                continue
            m = self.app.models_of(t["path"])
            if not os.path.isdir(m):
                continue
            if is_reparse_point(m):
                continue          # 已经映射过的，没有可整理的内容
            packs.append((m, os.path.basename(os.path.dirname(m)) or t["path"]))
        if not packs:
            messagebox.showinfo("提示", "没有可扫描的整合包（未勾选，或它们的 models 已经映射过了）")
            return

        self.stop_evt.clear()
        self.set_busy(True)
        self.tools_status.set("正在扫描整合包…")
        models_only = self.var_models_only.get()

        def worker():
            try:
                moves, dups, conflicts = plan_consolidation(
                    packs, repo, models_only=models_only, stop=self.stop_evt)
                self.win.after(0, self._scan_organize_done, moves, dups, conflicts, len(packs))
            except Exception as e:
                self.win.after(0, self._scan_failed, e)

        threading.Thread(target=worker, daemon=True).start()

    def _scan_failed(self, e):
        self.set_busy(False)
        self.tools_status.set("扫描失败")
        messagebox.showerror("扫描失败", str(e))

    def _scan_organize_done(self, moves, dups, conflicts, npacks):
        self.set_busy(False)
        self.stop_evt.clear()
        self.move_records = moves + dups + conflicts
        for i in self.org_tree.get_children():
            self.org_tree.delete(i)

        ACTION = {"move": "→ 移动到仓库", "dup": "≡ 重复（可删副本）",
                  "conflict": "⚠ 冲突（不动）"}
        for r in self.move_records:
            mark = "☑" if r["action"] != "conflict" else "☐"
            self.org_tree.insert("", "end", values=(
                mark, r["rel"], human_size(r["size"]), r["pack"],
                ACTION[r["action"]], r["dst"]))

        total = sum(r["size"] for r in moves)
        dup_size = sum(r["size"] for r in dups)
        self.org_summary.configure(
            text=f"扫描 {npacks} 个整合包 ｜ 待移动 {len(moves)} 个（{human_size(total)}）"
                 f" ｜ 冗余副本 {len(dups)} 个（{human_size(dup_size)}）"
                 f" ｜ 冲突 {len(conflicts)} 个")
        self.tools_status.set("扫描完成")
        self.log(f"整理入库扫描：待移动 {len(moves)}、冗余副本 {len(dups)}、冲突 {len(conflicts)}", "ok")

        if conflicts:
            messagebox.showwarning(
                "发现同名不同内容的文件",
                f"有 {len(conflicts)} 个文件在仓库里存在同名但内容不同的版本，"
                "已标记为「冲突（不动）」，需要你人工确认。\n\n"
                + "\n".join("  • " + c["rel"] for c in conflicts[:10])
                + ("\n  …" if len(conflicts) > 10 else ""),
            )

    # ---------- 执行：整理入库 ----------
    def run_organize(self):
        if self.busy:
            return
        if not self.move_records:
            messagebox.showinfo("提示", "请先点「扫描分析」")
            return

        cols = list(self.org_tree["columns"])
        rel_pos, act_pos = cols.index("rel"), cols.index("action")
        chosen = {}
        for iid in self.org_tree.get_children():
            vals = self.org_tree.item(iid, "values")
            if vals[cols.index("on")] == "☑":
                chosen[vals[rel_pos]] = vals[act_pos]

        todo = [r for r in self.move_records
                if r["action"] != "conflict" and r["rel"] in chosen
                and "冲突" not in chosen[r["rel"]]]
        if not todo:
            messagebox.showinfo("提示", "没有勾选可执行的项目（冲突项默认不勾选）")
            return

        moves = [r for r in todo if r["action"] == "move"]
        dups = [r for r in todo if r["action"] == "dup"]
        move_bytes = sum(r["size"] for r in moves)
        repo = os.path.normpath(self.app.repo_var.get().strip().strip('"'))

        # 跨盘搬运前先看目标盘空间
        try:
            free = shutil.disk_usage(repo).free
        except OSError:
            free = None
        space_warn = ""
        if free is not None and move_bytes > free:
            space_warn = (f"\n\n⚠ 目标盘剩余空间不足！需要 {human_size(move_bytes)}，"
                          f"只剩 {human_size(free)}。")

        lines = [
            f"模型仓库：{repo}\n",
            "即将执行：\n",
            f"  • 移动 {len(moves)} 个文件进仓库（共 {human_size(move_bytes)}）",
            f"  • 删除 {len(dups)} 个冗余副本（仓库里已有一模一样的，共 {human_size(sum(r['size'] for r in dups))}）",
            "\n这是【会移动/删除文件】的操作，请务必确认上方清单。",
            "所有被删除的文件内容都已确认与仓库中的版本完全一致（指纹相同）。",
        ]
        if self.var_verify.get():
            lines.append("已开启全量 MD5 复核。")
        lines.append(space_warn)
        if not messagebox.askokcancel("确认整理操作", "\n".join(lines), icon="warning"):
            self.log("用户取消了整理操作。", "warn")
            return

        self.stop_evt.clear()
        self.set_busy(True)
        verify = self.var_verify.get()
        automap = self.var_automap.get()

        def worker():
            manifest = {
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "repo": repo,
                "moved": [], "deleted": [], "failed": [],
            }
            ok = err = 0
            for i, r in enumerate(todo, 1):
                if self.stop_evt.is_set():
                    break
                self.win.after(0, self.tools_status.set,
                               f"整理中 {i}/{len(todo)}：{r['rel']}")
                try:
                    os.makedirs(os.path.dirname(r["dst"]), exist_ok=True)
                    if r["action"] == "move":
                        if os.path.exists(r["dst"]):
                            raise FileExistsError(f"目标已存在：{r['dst']}")
                        shutil.move(r["path"], r["dst"])
                        manifest["moved"].append(
                            {"from": r["path"], "to": r["dst"], "size": r["size"]})
                        ok += 1
                        self.win.after(0, self.log, f"  ✔ 已入库：{r['rel']}", "ok")
                    else:  # dup
                        if verify:
                            a = full_md5(r["path"])
                            b = full_md5(r["twin"])
                            if not a or a != b:
                                raise ValueError("全量 MD5 不一致，已跳过（保护数据）")
                        if os.path.exists(r["dst"]):
                            os.remove(r["path"])
                            manifest["deleted"].append(
                                {"path": r["path"], "twin": r["twin"], "size": r["size"]})
                            ok += 1
                            self.win.after(0, self.log,
                                           f"  ✔ 已删冗余副本：{r['path']}", "ok")
                        else:
                            raise FileNotFoundError("仓库中的对应文件不见了，跳过删除")
                except Exception as e:
                    err += 1
                    manifest["failed"].append({"path": r["path"], "err": str(e)})
                    self.win.after(0, self.log, f"  ✘ 失败 {r['rel']}：{e}", "err")

            # 可选：整理完自动建立映射
            mapped = []
            if automap and not self.stop_evt.is_set():
                for m, label in self._packs_for_automap():
                    if os.path.isdir(m) and not is_reparse_point(m):
                        good, msg = mklink_junction(m, repo)
                        if good:
                            mapped.append(m)
                            self.win.after(0, self.log, f"  ✔ 已自动映射：{m}", "ok")
                        else:
                            self.win.after(0, self.log,
                                           f"  ✘ 自动映射失败 {m}：{msg}", "err")

            self._save_manifest(manifest)
            self.win.after(0, self._organize_done, ok, err, len(mapped), manifest)

        threading.Thread(target=worker, daemon=True).start()

    def _packs_for_automap(self):
        out = []
        for t in self.app.targets:
            m = self.app.models_of(t["path"])
            if os.path.isdir(m) and not is_reparse_point(m):
                out.append((m, t["path"]))
        return out

    def _save_manifest(self, manifest):
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(here, f"整理清单_{time.strftime('%Y%m%d_%H%M%S')}.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            self.win.after(0, self.log, f"整理清单已保存：{p}", "info")
        except Exception as e:
            self.win.after(0, self.log, f"保存整理清单失败：{e}", "warn")

    def _organize_done(self, ok, err, mapped_n, manifest):
        self.set_busy(False)
        self.stop_evt.clear()
        self.tools_status.set(f"整理完成（成功 {ok} / 失败 {err}）")
        self.app.refresh_all()
        self.app.save_config(silent=True)
        msg = f"整理完成：成功 {ok} 项，失败 {err} 项。"
        if mapped_n:
            msg += f"\n已自动建立映射 {mapped_n} 个，重启 ComfyUI 生效。"
        if err:
            msg += "\n失败的条目见运行日志与整理清单。"
        messagebox.showinfo("整理完成" if not err else "部分完成", msg)
        # 若还有未映射的整合包，自动重扫一次刷新状态；否则只刷主界面
        if self._packs_for_automap():
            self.scan_organize()
        else:
            self.tools_status.set("所有整合包均已映射到仓库")

    # ---------- 扫描：查重 ----------
    def scan_dupes(self):
        if self.busy:
            return
        roots = []
        repo = self.app.repo_var.get().strip().strip('"')
        if repo and os.path.isdir(repo) and not is_reparse_point(repo):
            roots.append((repo, "仓库"))
        for t in self.app.targets:
            m = self.app.models_of(t["path"])
            if os.path.isdir(m):
                roots.append((m, os.path.basename(os.path.dirname(m)) or t["path"]))
        if not roots:
            messagebox.showinfo("提示", "没有可扫描的目录")
            return

        self.stop_evt.clear()
        self.set_busy(True)
        self.tools_status.set("正在扫描模型文件…")
        models_only = self.dup_models_only.get()
        verify = self.dup_verify.get()

        def worker():
            files = []
            for m, label in roots:
                for it in iter_model_files(m, pack_label=label,
                                           models_only=models_only, stop=self.stop_evt):
                    files.append(it)
            if not self.stop_evt.is_set():
                groups = find_duplicate_groups(files, verify_full=verify)
                self.win.after(0, self._scan_dupes_done, groups, len(files), len(roots))
            else:
                self.win.after(0, lambda: (self.set_busy(False),
                                           self.tools_status.set("已取消")))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_dupes_done(self, groups, total_files, total_roots):
        self.set_busy(False)
        self.stop_evt.clear()
        self.dup_records = []
        for i in self.dup_tree.get_children():
            self.dup_tree.delete(i)

        for gi, g in enumerate(groups, 1):
            for fi, f in enumerate(g["files"]):
                keep = (f["path"] == g["keep"])
                self.dup_records.append(
                    {"grp": gi, "keep": keep, "path": f["path"],
                     "size": g["size"], "mtime": f.get("mtime", 0)})
                self.dup_tree.insert("", "end", values=(
                    "☐", gi, os.path.basename(f["path"]), human_size(g["size"]),
                    f["path"],
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(f.get("mtime") or 0)),
                    "保留" if keep else "可删"))

        waste = sum(g["waste"] for g in groups)
        self.dup_summary.configure(
            text=f"扫描 {total_roots} 个目录 / {total_files} 个文件 ｜ "
                 f"{len(groups)} 组重复 ｜ 可释放 {human_size(waste)}")
        self.tools_status.set("查重完成")
        self.log(f"查重完成：{len(groups)} 组重复，可释放 {human_size(waste)}", "ok")
        if not groups:
            messagebox.showinfo("查重完成", "没有发现完全相同的重复文件。")

    # ---------- 执行：删除重复副本 ----------
    def run_delete_dupes(self):
        if self.busy:
            return
        if not self.dup_records:
            messagebox.showinfo("提示", "请先点「开始扫描」")
            return
        cols = list(self.dup_tree["columns"])
        path_pos, keep_pos = cols.index("path"), cols.index("keep")
        victims = []
        for iid in self.dup_tree.get_children():
            vals = self.dup_tree.item(iid, "values")
            if vals[cols.index("on")] == "☑":
                if vals[keep_pos] == "保留":
                    messagebox.showwarning(
                        "提示",
                        f"「{os.path.basename(vals[path_pos])}」是本组建议保留的副本，\n"
                        "不建议删除。已取消操作，请重新勾选。")
                    return
                victims.append(vals[path_pos])
        if not victims:
            messagebox.showinfo("提示", "没有勾选任何可删副本")
            return

        total = sum(r["size"] for r in self.dup_records if r["path"] in victims)
        use_trash = self._ask_trash()
        if not messagebox.askokcancel(
            "确认删除",
            f"将删除 {len(victims)} 个重复副本，释放约 {human_size(total)}。\n\n"
            + "\n".join("  • " + v for v in victims[:15])
            + ("\n  …" if len(victims) > 15 else "")
            + f"\n\n删除方式：{'移入回收站' if use_trash else '直接删除（不可恢复）'}",
            icon="warning",
        ):
            return

        self.stop_evt.clear()
        self.set_busy(True)

        def worker():
            ok = err = 0
            for i, p in enumerate(victims, 1):
                if self.stop_evt.is_set():
                    break
                self.win.after(0, self.tools_status.set, f"删除中 {i}/{len(victims)}")
                try:
                    if use_trash:
                        self._to_trash(p)
                    else:
                        os.remove(p)
                    ok += 1
                    self.win.after(0, self.log, f"  ✔ 已删除重复副本：{p}", "ok")
                except Exception as e:
                    err += 1
                    self.win.after(0, self.log, f"  ✘ 删除失败 {p}：{e}", "err")
            self.win.after(0, self._delete_done, ok, err)

        threading.Thread(target=worker, daemon=True).start()

    def _ask_trash(self):
        try:
            import send2trash  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _to_trash(path):
        try:
            from send2trash import send2trash as s2t
            s2t(path)
            return
        except Exception:
            pass
        # 退回 PowerShell 的回收站（需要 Shell.Application）
        ps = (
            "$s=New-Object -ComObject Shell.Application;"
            f"$i=$s.NameSpace(0).ParseName('{path}');"
            "if($i){$i.InvokeVerb('delete')}else{throw 'not found'}"
        )
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", ps],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        if p.returncode != 0 or os.path.exists(path):
            raise RuntimeError("无法移入回收站，已放弃删除以保安全")

    def _delete_done(self, ok, err):
        self.set_busy(False)
        self.stop_evt.clear()
        self.tools_status.set(f"删除完成（成功 {ok} / 失败 {err}）")
        self.app.refresh_all()
        messagebox.showinfo("删除完成", f"成功 {ok} 个，失败 {err} 个。")


def report_crash(exc_text: str, show_dialog: bool = True):
    """崩溃时把信息写到文件，并尽量弹窗告知用户（pythonw 下控制台不可见）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    logp = os.path.join(here, "崩溃日志.txt")
    try:
        with open(logp, "a", encoding="utf-8") as f:
            f.write("=" * 62 + "\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"可执行文件: {sys.executable}\n")
            f.write(exc_text)
            f.write("\n")
    except Exception:
        pass

    # 同时尝试写到标准错误（若用 python.exe 启动则控制台可见）
    try:
        sys.stderr.write(exc_text + "\n")
        sys.stderr.flush()
    except Exception:
        pass

    if not show_dialog:
        return

    try:
        import ctypes as _ct
        last_line = exc_text.strip().splitlines()[-1][:300] if exc_text.strip() else "未知错误"
        msg = (
            "程序启动失败，详细信息已写入：\n\n"
            f"{logp}\n\n"
            "错误摘要：\n"
            f"{last_line}"
        )
        _ct.windll.user32.MessageBoxW(
            None, msg, "ComfyUI 模型目录映射工具 - 启动失败", 0x10
        )
    except Exception:
        pass


def guarded_main():
    """带崩溃兜底的入口。"""
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        report_crash(traceback.format_exc())


def main():
    if os.name != "nt":
        print("本工具仅支持 Windows。")
        return

    # 环境自检：tkinter 是否可用
    try:
        import tkinter as _tk  # noqa: F401
    except ImportError:
        report_crash(
            "ImportError: 当前 Python 环境缺少 tkinter 模块。\n"
            "解决办法：重装 Python 时勾选 'tcl/tk and IDLE'。\n"
            f"当前解释器：{sys.executable}",
        )
        return

    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    MapperApp(root)
    root.mainloop()


if __name__ == "__main__":
    guarded_main()
