"""Minimal stdlib PNG reader/writer for slide screenshots (8-bit RGB/RGBA, non-interlaced: what
headless Chrome writes). No third-party packages: the playbook venv is stdlib-only.

    img = read(path)   -> Image(width, height, channels, rows: list[bytearray])
    write(path, img)   -> RGB PNG
"""
import struct, zlib


class Image:
    def __init__(self, width, height, channels, rows):
        self.width, self.height, self.channels, self.rows = width, height, channels, rows

    def gray_extrema(self, x0, y0, x1, y1):
        """(min, max) of the luma approximation (R+G+B)//3 over the box [x0,x1) x [y0,y1)."""
        c, lo, hi = self.channels, 255, 0
        for y in range(y0, y1):
            row = self.rows[y]
            for x in range(x0, x1):
                i = x * c
                v = (row[i] + row[i + 1] + row[i + 2]) // 3
                if v < lo:
                    lo = v
                if v > hi:
                    hi = v
        return lo, hi

    def pixel(self, x, y):
        i = x * self.channels
        r = self.rows[y]
        return r[i], r[i + 1], r[i + 2]

    def rect(self, x0, y0, x1, y1, rgb, width=4):
        """Draw an outline rectangle, clipped to the image."""
        c = self.channels
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.width - 1, int(x1)), min(self.height - 1, int(y1))
        for t in range(width):
            for x in range(x0, x1 + 1):
                for y in (y0 + t, y1 - t):
                    if 0 <= y < self.height:
                        self.rows[y][x * c:x * c + 3] = bytes(rgb)
            for y in range(y0, y1 + 1):
                for x in (x0 + t, x1 - t):
                    if 0 <= x < self.width:
                        self.rows[y][x * c:x * c + 3] = bytes(rgb)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def read(path):
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, w = 8, [], None
    while pos < len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (2, 6) or interlace:
                raise ValueError(f"{path}: unsupported PNG (depth {depth}, colour type {ctype}, interlace {interlace})")
            ch = 3 if ctype == 2 else 4
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
        pos += 12 + n
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        if f == 1:
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                left = line[x - ch] if x >= ch else 0
                ul = prev[x - ch] if x >= ch else 0
                line[x] = (line[x] + _paeth(left, prev[x], ul)) & 255
        rows.append(line)
        prev = line
    return Image(w, h, ch, rows)


def write(path, img):
    c = img.channels
    raw = b"".join(b"\x00" + bytes(r if c == 3 else bytes(r[j] for j in range(len(r)) if j % 4 != 3))
                   for r in img.rows)

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", img.width, img.height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
