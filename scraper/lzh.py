"""公式データファイル（.lzh, -lh5-）の展開。外部ライブラリ不要の純 Python 実装。"""
from __future__ import annotations

import struct


class _Bits:
    __slots__ = ("data", "pos", "buf", "n")

    def __init__(self, data: bytes, pos: int):
        self.data, self.pos, self.buf, self.n = data, pos, 0, 0

    def _fill(self, need: int):
        while self.n < need:
            b = self.data[self.pos] if self.pos < len(self.data) else 0
            self.pos += 1
            self.buf = (self.buf << 8) | b
            self.n += 8

    def get(self, k: int) -> int:
        if k == 0:
            return 0
        self._fill(k)
        self.n -= k
        v = (self.buf >> self.n) & ((1 << k) - 1)
        self.buf &= (1 << self.n) - 1
        return v

    def peek16(self) -> int:
        self._fill(16)
        return (self.buf >> (self.n - 16)) & 0xFFFF

    def skip(self, k: int):
        self._fill(k)
        self.n -= k
        self.buf &= (1 << self.n) - 1


class _Table:
    """canonical Huffman。16bit を先読みして (記号, 長さ) を引く。"""

    def __init__(self, lens: list[int] | None = None, single: int | None = None):
        self.single = single
        if single is not None:
            return
        maxlen = max(lens)
        self.maxlen = maxlen
        table = [None] * (1 << maxlen)
        code = 0
        for L in range(1, maxlen + 1):
            for s, l in enumerate(lens):
                if l == L:
                    start = code << (maxlen - L)
                    for k in range(start, start + (1 << (maxlen - L))):
                        table[k] = (s, L)
                    code += 1
            code <<= 1
        self.table = table

    def decode(self, bits: _Bits) -> int:
        if self.single is not None:
            return self.single
        v = bits.peek16() >> (16 - self.maxlen)
        s, L = self.table[v]
        bits.skip(L)
        return s


def _read_pt(bits: _Bits, nn: int, nbit: int, special: int) -> _Table:
    n = bits.get(nbit)
    if n == 0:
        return _Table(single=bits.get(nbit))
    lens = [0] * nn
    i = 0
    while i < n:
        c = bits.get(3)
        if c == 7:
            while bits.get(1) == 1:
                c += 1
        lens[i] = c
        i += 1
        if i == special:
            k = bits.get(2)
            i += k
    return _Table(lens)


def _read_c(bits: _Bits, pt: _Table) -> _Table:
    n = bits.get(9)
    if n == 0:
        return _Table(single=bits.get(9))
    lens = [0] * 510
    i = 0
    while i < n:
        c = pt.decode(bits)
        if c <= 2:
            if c == 0:
                c = 1
            elif c == 1:
                c = bits.get(4) + 3
            else:
                c = bits.get(9) + 20
            i += c
        else:
            lens[i] = c - 2
            i += 1
    return _Table(lens)


def unlzh(data: bytes, limit: int | None = None) -> bytes:
    """最初のエントリを展開して返す。limit を渡すとその長さで打ち切る（テスト用）。"""
    method = data[2:7].decode("ascii")
    comp, orig = struct.unpack_from("<II", data, 7)
    level = data[20]
    if level == 0:
        pos = data[0] + 2
    elif level == 1:
        pos = data[0] + 2
        ext = struct.unpack_from("<H", data, pos - 2)[0]
        while ext:
            pos += ext
            ext = struct.unpack_from("<H", data, pos - 2)[0]
    else:
        pos = struct.unpack_from("<H", data, 0)[0]
    if method == "-lh0-":
        return data[pos:pos + orig]
    np_, pbit = {"-lh5-": (14, 4), "-lh6-": (16, 5), "-lh7-": (17, 5)}[method]
    total = orig if limit is None else min(orig, limit)
    bits = _Bits(data, pos)
    out = bytearray()
    block = 0
    ct = pt = None
    while len(out) < total:
        if block == 0:
            block = bits.get(16)
            t = _read_pt(bits, 19, 5, 3)
            ct = _read_c(bits, t)
            pt = _read_pt(bits, np_, pbit, -1)
        block -= 1
        c = ct.decode(bits)
        if c < 256:
            out.append(c)
        else:
            length = c - 253
            j = pt.decode(bits)
            if j:
                j = (1 << (j - 1)) + bits.get(j - 1)
            s = len(out) - j - 1
            for k in range(length):
                out.append(out[s + k])
    return bytes(out[:total])
