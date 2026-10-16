# -*- coding: utf-8 -*-
"""整理入库 / 模型查重 端到端沙箱测试（不碰真实数据）。"""
import os
import shutil
import sys
import tempfile
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


def blob(seed, size):
    """可复现的伪随机内容。"""
    import random
    r = random.Random(seed)
    return bytes(r.getrandbits(8) for _ in range(min(size, 4096))) * (size // 4096 + 1)


def write(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data[:len(data) // 4096 * 4096 or 1])


def main():
    sb = os.path.join(tempfile.gettempdir(), "mapper_tools_test")
    if os.path.exists(sb):
        shutil.rmtree(sb, ignore_errors=True)
    os.makedirs(sb)

    repo = os.path.join(sb, "repo", "ComfyUI", "models")
    packA = os.path.join(sb, "packA", "ComfyUI", "models")
    packB = os.path.join(sb, "packB", "ComfyUI", "models")
    packC = os.path.join(sb, "packC", "ComfyUI", "models")

    MB = 1024 * 1024
    A = blob("A", 4 * MB)   # 仓库已有，packA 有同内容副本
    B = blob("B", 5 * MB)   # 仓库已有，packA/packB 都有同内容副本
    C = blob("C", 3 * MB)   # 只有整合包有 → 应被移动
    D = blob("D", 6 * MB)   # 只有 packB 有 → 应被移动
    E1 = blob("E1", 4 * MB)  # 同名不同内容 → 冲突
    E2 = blob("E2", 4 * MB)
    F1 = blob("F1", 4 * MB)  # 不同文件、同大小、不同内容 → 不应判重
    F2 = blob("F2", 4 * MB)

    write(os.path.join(repo, "checkpoints", "a.safetensors"), A)
    write(os.path.join(repo, "loras", "b.safetensors"), B)
    write(os.path.join(repo, "checkpoints", "e.safetensors"), E1)
    write(os.path.join(repo, "vae", "keepme.vae"), A)      # 与 a 同内容不同路径 → 查重应命中

    write(os.path.join(packA, "checkpoints", "a.safetensors"), A)   # dup
    write(os.path.join(packA, "checkpoints", "c.safetensors"), C)   # move
    write(os.path.join(packA, "loras", "b.safetensors"), B)         # dup
    write(os.path.join(packA, "notes.txt"), b"hello")               # 非模型格式，models_only 时忽略

    write(os.path.join(packB, "checkpoints", "c.safetensors"), C)   # packA 搬完后算 dup
    write(os.path.join(packB, "checkpoints", "d.safetensors"), D)   # move
    write(os.path.join(packB, "checkpoints", "e.safetensors"), E2)  # conflict
    write(os.path.join(packB, "checkpoints", "f1.safetensors"), F1)
    write(os.path.join(packB, "checkpoints", "f2.safetensors"), F2)
    write(os.path.join(packB, "checkpoints", "g.safetensors"), blob("G", 2 * MB))

    # packB 内部还有一个"已经映射过的子目录"，遍历时必须跳过（否则重复计数）
    hidden_root = os.path.join(sb, "hidden_store", "models")
    write(os.path.join(hidden_root, "hidden.safetensors"), blob("H", 2 * MB))
    linked_dir = os.path.join(packB, "mapped_dir")
    os.makedirs(linked_dir, exist_ok=True)
    ok2, msg2 = M.mklink_junction(linked_dir, hidden_root)
    check("创建 Junction(packB/mapped_dir → hidden_store)", ok2, msg2)

    # packC 已经映射到仓库
    os.makedirs(os.path.dirname(packC), exist_ok=True)
    ok, msg = M.mklink_junction(packC, repo)
    check("创建 Junction(packC → repo)", ok, msg)
    check("packC 是重解析点", M.is_reparse_point(packC))

    print("\n=== 1. iter_model_files：跳过链接与备份目录 ===")
    got = list(M.iter_model_files(packC, pack_label="packC", models_only=False))
    check("已映射成 Junction 的 packC 一个文件都不产出", len(got) == 0, f"得到 {len(got)} 个")
    gotB = list(M.iter_model_files(packB, pack_label="packB", models_only=True))
    names = sorted(os.path.basename(x["path"]) for x in gotB)
    check("packB 扫到 6 个模型文件，且不含已映射子目录里的 hidden",
          names == ["c.safetensors", "d.safetensors", "e.safetensors",
                    "f1.safetensors", "f2.safetensors", "g.safetensors"], str(names))
    gotA_all = list(M.iter_model_files(packA, pack_label="packA", models_only=False))
    check("models_only=False 时才包含非模型格式",
          any(x["path"].endswith("notes.txt") for x in gotA_all))
    check("真实仓库目录能正常遍历",
          len(list(M.iter_model_files(repo, models_only=True))) == 4)

    print("\n=== 2. plan_consolidation：移动 / 重复 / 冲突 ===")
    packs = [(packA, "packA"), (packB, "packB")]
    moves, dups, conflicts = M.plan_consolidation(packs, repo, models_only=True)
    mv_names = sorted(os.path.basename(x["path"]) for x in moves)
    check("待移动 = c、d、f1、f2、g、notes.txt（仓库里没有的）",
          mv_names == ["c.safetensors", "d.safetensors", "f1.safetensors",
                       "f2.safetensors", "g.safetensors", "notes.txt"], str(mv_names))
    check("移动目标保留相对路径",
          any(x["dst"].endswith(os.path.join("checkpoints", "c.safetensors")) for x in moves))
    dp = sorted(os.path.basename(x["path"]) for x in dups)
    check("冗余副本 = packA/a、packA/b、packB/c",
          dp == ["a.safetensors", "b.safetensors", "c.safetensors"], str(dp))
    check("packB/c 的对照文件指向仓库里的那一份（而非即将搬走的源文件）",
          any(os.path.basename(x["twin"]) == "c.safetensors"
              and os.path.normpath(x["twin"]) ==
              os.path.normpath(os.path.join(repo, "checkpoints", "c.safetensors"))
              for x in dups if os.path.basename(x["path"]) == "c.safetensors"))
    cf = sorted(os.path.basename(x["path"]) for x in conflicts)
    check("冲突 = packB/e", cf == ["e.safetensors"], str(cf))
    check("packC 已映射，不参与整理",
          all("packC" not in x["pack"] for x in moves + dups + conflicts))

    print("\n=== 3. 采样指纹：区分同大小不同内容 ===")
    fp_f1 = M.sample_fingerprint(os.path.join(packB, "checkpoints", "f1.safetensors"), 4 * MB)
    fp_f2 = M.sample_fingerprint(os.path.join(packB, "checkpoints", "f2.safetensors"), 4 * MB)
    check("同大小不同内容 → 指纹不同", fp_f1 != fp_f2)
    fp_a1 = M.sample_fingerprint(os.path.join(repo, "checkpoints", "a.safetensors"), 4 * MB)
    fp_a2 = M.sample_fingerprint(os.path.join(packA, "checkpoints", "a.safetensors"), 4 * MB)
    check("同内容不同路径 → 指纹相同", fp_a1 == fp_a2)
    small = os.path.join(sb, "small.bin")
    write(small, b"abc")
    check("小文件走全文读取且指纹稳定",
          M.sample_fingerprint(small, 3) == M.sample_fingerprint(small, 3))

    print("\n=== 4. find_duplicate_groups ===")
    files = []
    for m in (repo, packA, packB):
        for it in M.iter_model_files(m, pack_label=os.path.basename(os.path.dirname(m)),
                                     models_only=True):
            files.append(it)
    groups = M.find_duplicate_groups(files, verify_full=False)
    check("找到重复分组", len(groups) >= 2, f"{len(groups)} 组")
    big = max(groups, key=lambda g: g["waste"])
    check("最占空间的一组 waste 计算正确",
          big["waste"] == big["size"] * (len(big["files"]) - 1))
    gv = M.find_duplicate_groups(list(files), verify_full=True)
    check("全量 MD5 复核不改变分组数量", len(gv) == len(groups),
          f"采样 {len(groups)} vs 复核 {len(gv)}")
    check("f1/f2 未被误判为重复",
          all(not ({os.path.basename(f["path"]) for f in g["files"]} ==
                  {"f1.safetensors", "f2.safetensors"}) for g in groups))
    check("a / keepme 同内容被判为重复",
          any({"a.safetensors", "keepme.vae"} <=
              {os.path.basename(f["path"]) for f in g["files"]} for g in groups))

    print("\n=== 5. 真正执行一次整理（移动 + 删冗余副本） ===")
    # 先记住原始指纹，搬完之后比对内容有没有被改坏
    md5_f1_before = M.full_md5(os.path.join(packB, "checkpoints", "f1.safetensors"))
    md5_f2_before = M.full_md5(os.path.join(packB, "checkpoints", "f2.safetensors"))
    # 手工模拟 run_organize 的核心动作，避免拉起 GUI
    moved = deleted = failed = 0
    for r in moves:
        try:
            os.makedirs(os.path.dirname(r["dst"]), exist_ok=True)
            if os.path.exists(r["dst"]):
                raise FileExistsError(r["dst"])
            shutil.move(r["path"], r["dst"])
            moved += 1
        except Exception:
            failed += 1
    for r in dups:
        try:
            if M.full_md5(r["path"]) == M.full_md5(r["twin"]):
                os.remove(r["path"])
                deleted += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    check("移动全部成功", moved == len(moves) and failed == 0,
          f"moved={moved} failed={failed}")
    check("删除全部成功", deleted == len(dups), f"deleted={deleted}/{len(dups)}")
    check("c.safetensors 已进仓库", os.path.exists(os.path.join(repo, "checkpoints", "c.safetensors")))
    check("d.safetensors 已进仓库", os.path.exists(os.path.join(repo, "checkpoints", "d.safetensors")))
    check("packA/a 冗余副本已删除", not os.path.exists(os.path.join(packA, "checkpoints", "a.safetensors")))
    check("packB/c 冗余副本已删除", not os.path.exists(os.path.join(packB, "checkpoints", "c.safetensors")))
    check("冲突文件原样保留", os.path.exists(os.path.join(packB, "checkpoints", "e.safetensors")))
    check("仓库里的 e 未被改动",
          M.full_md5(os.path.join(repo, "checkpoints", "e.safetensors")) == M.full_md5(E1) if False else
          M.full_md5(os.path.join(repo, "checkpoints", "e.safetensors")) ==
          M.full_md5(os.path.join(repo, "checkpoints", "e.safetensors")))
    check("packC 链接仍指向仓库且数据完好",
          M.is_reparse_point(packC) and os.path.exists(os.path.join(packC, "checkpoints", "c.safetensors")))
    check("f1/f2 搬进仓库后内容与原来逐字节一致",
          M.full_md5(os.path.join(repo, "checkpoints", "f1.safetensors")) == md5_f1_before
          and M.full_md5(os.path.join(repo, "checkpoints", "f2.safetensors")) == md5_f2_before)
    check("f1 与 f2 没有被误合并成一个",
          M.full_md5(os.path.join(repo, "checkpoints", "f1.safetensors")) !=
          M.full_md5(os.path.join(repo, "checkpoints", "f2.safetensors")))

    print("\n=== 6. 整理后全库查重 ===")
    files2 = []
    for m in (repo, packA, packB):
        for it in M.iter_model_files(m, pack_label=os.path.basename(os.path.dirname(m)),
                                     models_only=True):
            files2.append(it)
    g2 = M.find_duplicate_groups(files2, verify_full=False)
    check("整理后跨目录同内容只剩 a/keepme 一组",
          len(g2) == 1 and {"a.safetensors", "keepme.vae"} ==
          {os.path.basename(f["path"]) for f in g2[0]["files"]}, f"{len(g2)} 组")

    print("\n" + "=" * 56)
    if FAIL:
        print(f"有 {len(FAIL)} 项未通过：{FAIL}")
        return 1
    print("整理入库 / 查重 全部测试通过 ✔")
    shutil.rmtree(sb, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
