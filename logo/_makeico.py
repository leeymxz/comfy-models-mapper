"""生成多尺寸 Windows .ico（每帧内嵌 PNG，兼容 Vista+ 与所有现代浏览器）。"""
import struct, io, os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
AVAIL = [32, 64, 128, 256, 512, 1024]
SIZES = [16, 24, 32, 48, 64, 128, 256]


def pick(s):
    for a in AVAIL:
        if a >= s:
            return a
    return AVAIL[-1]


def png_bytes(s):
    im = Image.open(os.path.join(HERE, "png", "icon-%d.png" % pick(s))).convert("RGBA")
    if im.size[0] != s:
        im = im.resize((s, s), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    blobs = [(s, png_bytes(s)) for s in SIZES]
    n = len(blobs)
    out = bytearray()
    out += struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    for s, data in blobs:
        w = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in blobs:
        out += data
    p = os.path.join(HERE, "png", "icon.ico")
    with open(p, "wb") as f:
        f.write(out)
    print("写入", p, os.path.getsize(p), "字节，尺寸:", [s for s, _ in blobs])


if __name__ == "__main__":
    main()
