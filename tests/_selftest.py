# -*- coding: utf-8 -*-
"""
非界面自测：验证 Junction 创建 / 读取 / 删除 / 还原 的核心逻辑是否可用。
只在自己的临时沙箱目录里做，不碰任何真实模型目录。
"""
import os
import sys
import tempfile
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import comfy_models_mapper as M


def main():
    base = os.path.join(tempfile.gettempdir(), "mapper_selftest_" + str(int(time.time())))
    real = os.path.join(base, "real_models")
    fake = os.path.join(base, "ComfyUI", "models")
    os.makedirs(real)
    os.makedirs(fake)

    # 造点假数据
    with open(os.path.join(real, "a.safetensors"), "wb") as f:
        f.write(b"x" * 1024)
    os.makedirs(os.path.join(real, "checkpoints"))
    with open(os.path.join(fake, "old.txt"), "w", encoding="utf-8") as f:
        f.write("old")

    print("沙箱:", base)
    print("-" * 50)

    # 1. 真实目录识别
    assert not M.is_reparse_point(real), "真实目录不应被判为链接"
    print("[1] 真实目录识别           OK")

    # 2. 备份改名
    bak = fake + "_backup_20260927"
    ok, msg = M.move_dir(fake, bak)
    assert ok, f"改名失败: {msg}"
    assert not os.path.exists(fake) and os.path.isdir(bak)
    print("[2] 备份改名               OK")

    # 3. 创建 Junction
    ok, msg = M.mklink_junction(fake, real)
    assert ok, f"建链接失败: {msg}"
    assert M.is_reparse_point(fake), "应被识别为链接"
    print("[3] 创建 Junction          OK  ->", M.link_target(fake))

    # 4. 穿透读取
    names = sorted(os.listdir(fake))
    assert "a.safetensors" in names, f"穿透读取失败: {names}"
    assert os.path.isfile(os.path.join(fake, "a.safetensors"))
    print("[4] 穿透读取内容           OK  ->", names)

    # 5. 写入穿透
    with open(os.path.join(fake, "b.txt"), "w", encoding="utf-8") as f:
        f.write("hello")
    assert os.path.isfile(os.path.join(real, "b.txt")), "写入未落到源目录"
    print("[5] 写入穿透到源目录       OK")

    # 6. 计数与体积
    sz, fc, complete = M.dir_stats(real, max_seconds=5)
    assert fc >= 2, f"统计异常: {fc}"
    print(f"[6] 目录统计               OK  文件={fc} 大小={M.human_size(sz)} 完整={complete}")

    # 7. 删除链接，源数据必须完好
    ok, msg = M.remove_link_only(fake)
    assert ok, f"删链接失败: {msg}"
    assert not os.path.exists(fake), "链接应已消失"
    assert os.path.isdir(real) and os.path.isfile(os.path.join(real, "b.txt")), "源数据被误删！"
    assert not M.is_reparse_point(bak), "备份不应受影响"
    print("[7] 删链接不动源数据       OK")

    # 8. 还原备份
    ok, msg = M.move_dir(bak, fake)
    assert ok
    assert os.path.isfile(os.path.join(fake, "old.txt")), "还原后内容不对"
    print("[8] 还原备份               OK")

    # 9. 防误删：非链接拒绝删除
    ok, msg = M.remove_link_only(fake)
    assert not ok, "非链接被删除了，危险！"
    print("[9] 非链接拒绝删除(安全)   OK  ->", msg)

    # 10. 真实环境只读探测
    print("-" * 50)
    for p in [r"H:\ComfyUITE_20xx_20260813\ComfyUI\models",
              r"E:\COMFYUI_dapao\ComfyUI\models"]:
        if os.path.exists(p):
            print(f"[10] {p}")
            print(f"     真实目录={not M.is_reparse_point(p)}")

    shutil.rmtree(base, ignore_errors=True)
    print("-" * 50)
    print("全部自测通过 ✔")


if __name__ == "__main__":
    main()
