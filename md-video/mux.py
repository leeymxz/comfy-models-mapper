# -*- coding: utf-8 -*-
"""
ffmpeg 合成最终视频。
- 帧序列 24fps -> libx264 crf18
- 音轨做响度归一化（edge-tts 原始约 -28dB，不处理会明显偏轻）
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = r"C:\Users\Administrator\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
FRAMES = os.path.join(HERE, "frames")
VOICE = os.path.join(HERE, "build", "voice.wav")
OUT_DIR = os.path.join(HERE, "out")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    name = sys.argv[1] if len(sys.argv) > 1 else "comfy-mapper-tutorial.mp4"
    out = os.path.join(OUT_DIR, name)

    cmd = [
        FFMPEG, "-y", "-v", "warning", "-stats",
        "-framerate", "24",
        "-start_number", "0",
        "-i", os.path.join(FRAMES, "f_%06d.jpg"),
        "-i", VOICE,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        out,
    ]
    print("合成中…")
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "ignore")[-3000:])
        raise SystemExit(1)

    size = os.path.getsize(out) / 1024 / 1024
    print(f"完成: {out}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
