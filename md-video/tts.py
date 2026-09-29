# -*- coding: utf-8 -*-
"""
逐镜生成中文配音，并测出真实时长，写出 timeline.json。

用法:
    python tts.py            # 生成缺失的 mp3
    python tts.py --force    # 全部重新生成
"""
import asyncio
import json
import os
import subprocess
import sys

import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, "audio")
FFPROBE = r"C:\Users\Administrator\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\ffprobe.exe"

VOICE = "zh-CN-YunxiNeural"
RATE = "+8%"
BREATHE = 0.55   # 每镜尾部留白
LEAD = 2.2       # 片头静音，避免标题卡与第一句重叠


def probe_duration(path):
    """用 ffprobe 测音频真实时长（秒）。"""
    p = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True,
    )
    return float(p.stdout.decode().strip())


async def synth(text, out_path):
    comm = edge_tts.Communicate(text, VOICE, rate=RATE)
    await comm.save(out_path)


def main():
    force = "--force" in sys.argv
    os.makedirs(AUDIO_DIR, exist_ok=True)

    with open(os.path.join(HERE, "script.json"), "r", encoding="utf-8") as f:
        shots = json.load(f)

    print(f"共 {len(shots)} 个镜头\n")

    # 先统计字数，按 5.5 字/秒估算
    total_chars = 0
    for s in shots:
        n = len(s["narration"])
        total_chars += n
    print(f"总字数: {total_chars}  预估语音时长: {total_chars / 5.5:.1f}s")
    print(f"加留白后预估: {total_chars / 5.5 + len(shots) * BREATHE + LEAD:.1f}s\n")

    results = []
    cursor = LEAD  # 旁白从片头留白之后开始

    for idx, s in enumerate(shots, 1):
        sid = s["id"]
        mp3 = os.path.join(AUDIO_DIR, f"{sid}.mp3")

        if force or not os.path.exists(mp3):
            asyncio.run(synth(s["narration"], mp3))
            status = "生成"
        else:
            status = "复用"

        dur = probe_duration(mp3)
        start = cursor
        end = start + dur

        results.append({
            "id": sid,
            "type": s["type"],
            "label": s["label"],
            "narration": s["narration"],
            "audio": os.path.relpath(mp3, HERE).replace("\\", "/"),
            "start": round(start, 3),
            "dur": round(dur, 3),
            "end": round(end, 3),
        })

        print(f"[{idx:2d}] {status} {sid:12s} {len(s['narration']):3d}字 "
              f"dur={dur:6.2f}s  start={start:7.2f}s")

        cursor = end + BREATHE

    total = cursor
    print(f"\n成片总时长: {total:.1f}s  ({total / 60:.2f} 分钟)")

    tl = {"lead": LEAD, "breathe": BREATHE, "total": round(total, 3), "shots": results}
    with open(os.path.join(HERE, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(tl, f, ensure_ascii=False, indent=2)
    print(f"已写出 timeline.json")


if __name__ == "__main__":
    main()
