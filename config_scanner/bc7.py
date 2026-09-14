"""BC7 (DXGI 98) block decompress — GameStar languageBtn flags are this format."""

from __future__ import annotations

# Official BC7 interpolation weights (D3D).
_W2 = (0, 21, 43, 64)
_W3 = (0, 9, 18, 27, 37, 46, 55, 64)
_W4 = (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64)

# 2-subset partitions (64 x 16). Each nibble pair packed as 16 nybbles in a u64
# would be bulky; store 16 subset ids per row.
_PART2: tuple[tuple[int, ...], ...] = (
    (0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1),
    (0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1),
    (0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1),
    (0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1),
    (0, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1),
    (0, 0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1),
    (0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1),
    (0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 1),
    (0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0),
    (0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0),
    (0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0),
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0),
    (0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0, 1),
    (0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0),
    (0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 0, 0),
    (0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0),
    (0, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1, 1, 0, 0),
    (0, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0),
    (0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0),
    (0, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 1, 0),
    (0, 0, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0),
    (0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1),
    (0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1),
    (0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0),
    (0, 0, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0),
    (0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0),
    (0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0),
    (0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1),
    (0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1),
    (0, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0),
    (0, 0, 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 0),
    (0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0, 0),
    (0, 0, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1, 0, 0),
    (0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 1, 0),
    (0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1),
    (0, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1),
    (0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0),
    (0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0),
    (0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0),
    (0, 0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 0),
    (0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1),
    (0, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1),
    (0, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0),
    (0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 0),
    (0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1),
    (0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1),
    (0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 1),
    (0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1),
    (0, 0, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1),
    (0, 0, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0),
    (0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0),
    (0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 1, 0, 1, 1, 1),
)

_PART3: tuple[tuple[int, ...], ...] = (
    (0, 0, 1, 1, 0, 0, 1, 1, 0, 2, 2, 1, 2, 2, 2, 2),
    (0, 0, 0, 1, 0, 0, 1, 1, 2, 2, 1, 1, 2, 2, 2, 1),
    (0, 0, 0, 0, 2, 0, 0, 1, 2, 2, 1, 1, 2, 2, 1, 1),
    (0, 2, 2, 2, 0, 0, 2, 2, 0, 0, 1, 1, 0, 1, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 1, 1, 2, 2),
    (0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 2, 2, 0, 0, 2, 2),
    (0, 0, 2, 2, 0, 0, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1),
    (0, 0, 1, 1, 0, 0, 1, 1, 2, 2, 1, 1, 2, 2, 1, 1),
    (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2),
    (0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2),
    (0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2),
    (0, 0, 1, 2, 0, 0, 1, 2, 0, 0, 1, 2, 0, 0, 1, 2),
    (0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2),
    (0, 1, 2, 2, 0, 1, 2, 2, 0, 1, 2, 2, 0, 1, 2, 2),
    (0, 0, 1, 1, 0, 1, 1, 2, 1, 1, 2, 2, 1, 2, 2, 2),
    (0, 0, 1, 1, 2, 0, 0, 1, 2, 2, 0, 0, 2, 2, 2, 0),
    (0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 2, 1, 1, 2, 2),
    (0, 1, 1, 1, 0, 0, 1, 1, 2, 0, 0, 1, 2, 2, 0, 0),
    (0, 0, 0, 0, 1, 1, 2, 2, 1, 1, 2, 2, 1, 1, 2, 2),
    (0, 0, 2, 2, 0, 0, 2, 2, 0, 0, 2, 2, 1, 1, 1, 1),
    (0, 1, 1, 1, 0, 1, 1, 1, 0, 2, 2, 2, 0, 2, 2, 2),
    (0, 0, 0, 1, 0, 0, 0, 1, 2, 2, 2, 1, 2, 2, 2, 1),
    (0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 2, 2, 0, 1, 2, 2),
    (0, 0, 0, 0, 1, 1, 0, 0, 2, 2, 1, 0, 2, 2, 1, 0),
    (0, 1, 2, 2, 0, 1, 2, 2, 0, 0, 1, 1, 0, 0, 0, 0),
    (0, 0, 1, 2, 0, 0, 1, 2, 1, 1, 2, 2, 2, 2, 2, 2),
    (0, 1, 1, 0, 1, 2, 2, 1, 1, 2, 2, 1, 0, 1, 1, 0),
    (0, 0, 0, 0, 0, 1, 1, 0, 1, 2, 2, 1, 1, 2, 2, 1),
    (0, 0, 2, 2, 1, 1, 0, 2, 1, 1, 0, 2, 0, 0, 2, 2),
    (0, 1, 1, 0, 0, 1, 1, 0, 2, 0, 0, 2, 2, 2, 2, 2),
    (0, 0, 1, 1, 0, 1, 2, 2, 0, 1, 2, 2, 0, 0, 1, 1),
    (0, 0, 0, 0, 2, 0, 0, 0, 2, 2, 1, 1, 2, 2, 2, 1),
    (0, 0, 0, 0, 0, 0, 0, 2, 1, 1, 2, 2, 1, 2, 2, 2),
    (0, 2, 2, 2, 0, 0, 2, 2, 0, 0, 1, 2, 0, 0, 1, 1),
    (0, 0, 1, 1, 0, 0, 1, 2, 0, 0, 2, 2, 0, 2, 2, 2),
    (0, 1, 2, 0, 0, 1, 2, 0, 0, 1, 2, 0, 0, 1, 2, 0),
    (0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 0, 0, 0, 0),
    (0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2, 0),
    (0, 1, 2, 0, 2, 0, 1, 2, 1, 2, 0, 1, 0, 1, 2, 0),
    (0, 0, 1, 1, 2, 2, 0, 0, 1, 1, 2, 2, 0, 0, 1, 1),
    (0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 0, 0, 0, 0, 1, 1),
    (0, 1, 0, 1, 0, 1, 0, 1, 2, 2, 2, 2, 2, 2, 2, 2),
    (0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 2, 1, 2, 1, 2, 1),
    (0, 0, 2, 2, 1, 1, 2, 2, 0, 0, 2, 2, 1, 1, 2, 2),
    (0, 0, 2, 2, 0, 0, 1, 1, 0, 0, 2, 2, 0, 0, 1, 1),
    (0, 2, 2, 0, 1, 2, 2, 1, 0, 2, 2, 0, 1, 2, 2, 1),
    (0, 1, 0, 1, 2, 2, 2, 2, 2, 2, 2, 2, 0, 1, 0, 1),
    (0, 0, 0, 0, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1),
    (0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 2, 2, 2, 2),
    (0, 2, 2, 2, 0, 1, 1, 1, 0, 2, 2, 2, 0, 1, 1, 1),
    (0, 0, 0, 2, 1, 1, 1, 2, 0, 0, 0, 2, 1, 1, 1, 2),
    (0, 0, 0, 0, 2, 1, 1, 2, 2, 1, 1, 2, 2, 1, 1, 2),
    (0, 2, 2, 2, 0, 1, 1, 1, 0, 1, 1, 1, 0, 2, 2, 2),
    (0, 0, 0, 2, 1, 1, 1, 2, 1, 1, 1, 2, 0, 0, 0, 2),
    (0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 2, 2, 2, 2),
    (0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 1, 2, 2, 1, 1, 2),
    (0, 1, 1, 0, 0, 1, 1, 0, 2, 2, 2, 2, 2, 2, 2, 2),
    (0, 0, 2, 2, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 2, 2),
    (0, 0, 2, 2, 1, 1, 2, 2, 1, 1, 2, 2, 0, 0, 2, 2),
    (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1, 1, 2),
    (0, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 1),
    (0, 2, 2, 2, 1, 2, 2, 2, 0, 2, 2, 2, 1, 2, 2, 2),
    (0, 1, 0, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2),
    (0, 1, 1, 1, 2, 0, 1, 1, 2, 2, 0, 1, 2, 2, 2, 0),
)

# Anchor index for subset 1 of a 2-subset partition.
_ANCHOR2 = (
    15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15,
    15, 2, 8, 2, 2, 8, 8, 15, 2, 8, 2, 2, 8, 8, 2, 2,
    15, 15, 6, 8, 2, 8, 15, 15, 2, 8, 2, 2, 2, 15, 15, 6,
    6, 2, 6, 8, 15, 15, 2, 2, 15, 15, 15, 15, 15, 2, 2, 15,
)

# Anchor indices for 3-subset partitions (subset 1, subset 2).
_ANCHOR3_1 = (
    3, 3, 15, 15, 8, 3, 15, 15, 8, 8, 6, 6, 6, 5, 3, 3,
    3, 3, 8, 15, 3, 3, 6, 10, 5, 8, 8, 6, 8, 5, 15, 15,
    8, 15, 3, 5, 6, 10, 8, 15, 15, 3, 15, 5, 15, 15, 15, 15,
    3, 15, 5, 5, 5, 8, 5, 10, 5, 10, 8, 13, 15, 12, 3, 3,
)
_ANCHOR3_2 = (
    15, 8, 8, 3, 15, 15, 3, 8, 15, 15, 15, 15, 15, 15, 15, 8,
    15, 8, 15, 3, 15, 8, 15, 8, 3, 15, 6, 10, 15, 15, 10, 8,
    15, 3, 15, 10, 10, 8, 9, 10, 6, 15, 8, 15, 3, 6, 6, 8,
    15, 3, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 3, 15, 15, 8,
)

# mode: subsets, part_bits, rot_bits, idx_sel_bits, color_bits, alpha_bits,
# pbit_type (0 none, 1 unique, 2 shared), index_bits, index_bits2
_MODE = (
    (3, 4, 0, 0, 4, 0, 1, 3, 0),  # 0
    (2, 6, 0, 0, 6, 0, 2, 3, 0),  # 1
    (3, 6, 0, 0, 5, 0, 0, 2, 0),  # 2
    (2, 6, 0, 0, 7, 0, 1, 2, 0),  # 3
    (1, 0, 2, 1, 5, 6, 0, 2, 3),  # 4
    (1, 0, 2, 0, 7, 8, 0, 2, 2),  # 5
    (1, 0, 0, 0, 7, 7, 1, 4, 0),  # 6
    (2, 6, 0, 0, 5, 5, 1, 2, 0),  # 7
)


class _Bits:
    def __init__(self, block: bytes) -> None:
        self._v = int.from_bytes(block, "little")
        self._i = 0

    def get(self, n: int) -> int:
        if n <= 0:
            return 0
        mask = (1 << n) - 1
        out = (self._v >> self._i) & mask
        self._i += n
        return out


def _unquant(value: int, bits: int) -> int:
    if bits <= 0:
        return 0
    if bits >= 8:
        return value & 255
    return (value << (8 - bits)) | (value >> (max(2 * bits - 8, 0)))


def _expand_endpoint(raw: int, bits: int, pbit: int | None) -> int:
    if pbit is None:
        return _unquant(raw, bits)
    return _unquant((raw << 1) | pbit, bits + 1)


def _interp(e0: int, e1: int, index: int, bits: int) -> int:
    table = _W2 if bits == 2 else _W3 if bits == 3 else _W4
    w = table[index]
    return ((64 - w) * e0 + w * e1 + 32) >> 6


def _decode_block(block: bytes) -> list[tuple[int, int, int, int]]:
    bits = _Bits(block)
    mode = 0
    while mode < 8:
        if bits.get(1):
            break
        mode += 1
    else:
        return [(0, 0, 0, 0)] * 16
    subsets, part_bits, rot_bits, idx_sel_bits, cb, ab, pkind, ib, ib2 = _MODE[mode]
    partition = bits.get(part_bits)
    rotation = bits.get(rot_bits)
    index_sel = bits.get(idx_sel_bits)
    endpoints = 2 * subsets
    colors: list[list[int]] = [[0, 0, 0, 255] for _ in range(endpoints)]
    for ch in range(3):
        for i in range(endpoints):
            colors[i][ch] = bits.get(cb)
    if ab:
        for i in range(endpoints):
            colors[i][3] = bits.get(ab)
    pbits: list[int | None] = [None] * endpoints
    if pkind == 1:
        for i in range(endpoints):
            pbits[i] = bits.get(1)
    elif pkind == 2:
        shared0 = bits.get(1)
        shared1 = bits.get(1)
        pbits[0] = pbits[1] = shared0
        if endpoints > 2:
            pbits[2] = pbits[3] = shared1
        if endpoints > 4:
            extra = bits.get(1)
            pbits[4] = pbits[5] = extra
    for i in range(endpoints):
        r, g, b, a = colors[i]
        colors[i][0] = _expand_endpoint(r, cb, pbits[i])
        colors[i][1] = _expand_endpoint(g, cb, pbits[i])
        colors[i][2] = _expand_endpoint(b, cb, pbits[i])
        if ab:
            colors[i][3] = _expand_endpoint(a, ab, pbits[i] if mode == 7 else None)
        elif mode < 4:
            colors[i][3] = 255
        else:
            colors[i][3] = _expand_endpoint(a, ab, pbits[i]) if ab else 255
    if mode == 6:
        # Mode 6: RGBA 7-bit + unique pbit on all channels including alpha.
        pass

    def subset_of(pixel: int) -> int:
        if subsets == 1:
            return 0
        if subsets == 2:
            return _PART2[partition][pixel]
        return _PART3[partition][pixel]

    def anchor_of(pixel: int) -> bool:
        if subsets == 1:
            return pixel == 0
        sub = subset_of(pixel)
        if subsets == 2:
            return pixel == 0 or pixel == _ANCHOR2[partition]
        if sub == 0:
            return pixel == 0
        if sub == 1:
            return pixel == _ANCHOR3_1[partition]
        return pixel == _ANCHOR3_2[partition]

    index1 = [0] * 16
    index2 = [0] * 16
    for i in range(16):
        n = ib - (1 if anchor_of(i) else 0)
        index1[i] = bits.get(n)
    if ib2:
        for i in range(16):
            n = ib2 - (1 if (i == 0) else 0)
            index2[i] = bits.get(n)

    pixels: list[tuple[int, int, int, int]] = []
    for i in range(16):
        sub = subset_of(i)
        e0 = colors[2 * sub]
        e1 = colors[2 * sub + 1]
        if ib2:
            ci, ai = (index2[i], index1[i]) if index_sel else (index1[i], index2[i])
            cb_i, ab_i = (ib2, ib) if index_sel else (ib, ib2)
            r = _interp(e0[0], e1[0], ci, cb_i)
            g = _interp(e0[1], e1[1], ci, cb_i)
            b = _interp(e0[2], e1[2], ci, cb_i)
            a = _interp(e0[3], e1[3], ai, ab_i)
        else:
            idx = index1[i]
            r = _interp(e0[0], e1[0], idx, ib)
            g = _interp(e0[1], e1[1], idx, ib)
            b = _interp(e0[2], e1[2], idx, ib)
            a = _interp(e0[3], e1[3], idx, ib)
        if rotation == 1:
            r, a = a, r
        elif rotation == 2:
            g, a = a, g
        elif rotation == 3:
            b, a = a, b
        pixels.append((r, g, b, a))
    return pixels


def decode_bc7_image(payload: bytes, width: int, height: int) -> bytes:
    """Return tightly packed RGBA8 for a BC7 image (no mips)."""
    if width <= 0 or height <= 0:
        raise ValueError("empty BC7 image")
    bw = (width + 3) // 4
    bh = (height + 3) // 4
    need = bw * bh * 16
    if len(payload) < need:
        raise ValueError("truncated BC7 payload")
    out = bytearray(width * height * 4)
    src = 0
    for by in range(bh):
        for bx in range(bw):
            block = payload[src : src + 16]
            src += 16
            pixels = _decode_block(block)
            for py in range(4):
                y = by * 4 + py
                if y >= height:
                    continue
                for px in range(4):
                    x = bx * 4 + px
                    if x >= width:
                        continue
                    r, g, b, a = pixels[py * 4 + px]
                    di = (y * width + x) * 4
                    out[di] = r
                    out[di + 1] = g
                    out[di + 2] = b
                    out[di + 3] = a
    return bytes(out)
