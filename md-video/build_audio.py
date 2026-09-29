# -*- coding: utf-8 -*-
"""
按时间轴把逐镜 mp3 拼成一条完整音轨 build/voice.wav（24kHz 单声道 s16）。
用 wave 模块做二进制拼接 + 静音填充，比 ffmpeg concat 稳。
"""
import json
import os
import subprocess
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = r"C:\Users\Administrator\ffmpeg\ffmpeg-9.0.1-essentials_build\bin\ffmpeg.exe"
BUILD = os.path.join(HERE, "build")
SR = 24000


def mp3_to_pcm(mp3):
    """mp3 -> 24kHz 单声道 s16 原始字节"""
    wav_tmp = mp3.replace(".mp3", ".tmp.wav")
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", mp3,
         "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", wav_tmp],
        check=True, capture_output=True,
    )
    with wave.open(wav_tmp, "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, SR), \
            f"格式不符: {mp3}"
        data = w.readframes(w.getnframes())
    os.remove(wav_tmp)
    return data


def main():
    os.makedirs(BUILD, exist_ok=True)
    with open(os.path.join(HERE, "timeline.json"), "r", encoding="utf-8") as f:
        tl = json.load(f)

    total_samples = int(tl["total"] * SR) + SR * 2   # 多留 1 秒余量
    buf = bytearray(total_samples * 2)               # s16 = 2 字节

    for s in tl["shots"]:
        mp3 = os.path.join(HERE, s["audio"])
        pcm = mp3_to_pcm(mp3)
        off = int(s["start"] * SR) * 2
        end = off + len(pcm)
        if end > len(buf):
            raise SystemExit(f"音轨超长: {s['id']} 结束于 {end/2/SR:.2f}s > 总长 {tl['total']}s")
        buf[off:end] = pcm
        print(f"  {s['id']:14s} 放置于 {s['start']:7.2f}s  ({len(pcm)/2/SR:.2f}s)")

    out = os.path.join(BUILD, "voice.wav")
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(buf))

    print(f"\n已写出 {out}  ({os.path.getsize(out)/1024/1024:.1f} MB, {len(buf)/2/SR:.2f}s)")


if __name__ == "__main__":
    main()
