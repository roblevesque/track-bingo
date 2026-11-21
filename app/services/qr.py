"""A small QR code encoder (byte mode, versions 1-10, error correction L or M) that draws SVG.

Pure Python with no dependencies, so the phone remote can show a scannable code without any extra
package or a JavaScript library. Versions 1-10 hold up to 213 bytes at level M (271 at L), plenty for
a web address. Follows ISO/IEC 18004 and is checked in the tests by decoding the result.
"""

from __future__ import annotations

MAX_VERSION = 10
_ECC_PER_BLOCK = {"L": (7, 10, 15, 20, 26, 18, 20, 24, 30, 18), "M": (10, 16, 26, 18, 24, 16, 18, 22, 22, 26)}
_NUM_BLOCKS = {"L": (1, 1, 1, 1, 1, 2, 2, 2, 2, 4), "M": (1, 1, 1, 2, 2, 4, 4, 4, 5, 5)}
_FORMAT_BITS = {"L": 1, "M": 0}


class QRError(ValueError):
    pass


def _raw_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        align = version // 7 + 2
        result -= (25 * align - 10) * align - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version: int, level: str) -> int:
    return _raw_modules(version) // 8 - _ECC_PER_BLOCK[level][version - 1] * _NUM_BLOCKS[level][version - 1]


def capacity(level: str = "M") -> int:
    """The most bytes a code can hold at this error-correction level."""
    version = MAX_VERSION
    return _data_codewords(version, level) - (3 if version >= 10 else 2)  # mode and length header


# ---------------------------------------------------------------- Reed-Solomon over GF(256)

def _gf_mul(x: int, y: int) -> int:
    result = 0
    for i in range(7, -1, -1):
        result = (result << 1) ^ ((result >> 7) * 0x11D)
        result ^= ((y >> i) & 1) * x
    return result


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# ---------------------------------------------------------------- building the code words

def _codewords(data: bytes, version: int, level: str) -> list[int]:
    capacity_bits = _data_codewords(version, level) * 8
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in range(length - 1, -1, -1))

    put(0b0100, 4)
    put(len(data), 16 if version >= 10 else 8)
    for byte in data:
        put(byte, 8)
    put(0, min(4, capacity_bits - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity_bits:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    blocks_n = _NUM_BLOCKS[level][version - 1]
    ecc_len = _ECC_PER_BLOCK[level][version - 1]
    total = _raw_modules(version) // 8
    short_blocks = blocks_n - total % blocks_n
    short_len = total // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(blocks_n):
        length = short_len - ecc_len + (0 if i < short_blocks else 1)
        chunk = words[k:k + length]
        k += length
        ecc = _rs_remainder(chunk, divisor)
        blocks.append(chunk + ([0] if i < short_blocks else []) + ecc)  # a placeholder keeps the columns aligned
    result = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_blocks:  # skip the placeholder
                result.append(block[i])
    return result


# ---------------------------------------------------------------- drawing

class _Grid:
    def __init__(self, version: int):
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.function[y][x] = True

    def draw_function_patterns(self, level: str) -> None:
        size = self.size
        for i in range(size):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = self._alignment_positions()
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i == 0 and j == 0) or (i == 0 and j == len(positions) - 1) or (i == len(positions) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(level, 0)  # reserves the format area; drawn again once the mask is chosen
        self._draw_version()

    def _alignment_positions(self) -> list[int]:
        if self.version == 1:
            return []
        count = self.version // 7 + 2
        step = (self.version * 8 + count * 3 + 5) // (count * 4 - 4) * 2
        return [6] + [self.size - 7 - i * step for i in range(count - 2, -1, -1)]

    def draw_format(self, level: str, mask: int) -> None:
        data = (_FORMAT_BITS[level] << 3) | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        bits = ((data << 10) | remainder) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        size = self.size
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, size - 15 + i, bit(i))
        self.set(8, size - 8, True)  # the always-dark module

    def _draw_version(self) -> None:
        if self.version < 7:
            return
        remainder = self.version
        for _ in range(12):
            remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
        bits = (self.version << 12) | remainder
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self.set(a, b, dark)
            self.set(b, a, dark)

    def place_data(self, words: list[int]) -> None:
        bits = [(word >> (7 - i)) & 1 for word in words for i in range(8)]
        k = 0
        right = self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = self.size - 1 - vert if upward else vert
                    if not self.function[y][x] and k < len(bits):
                        self.dark[y][x] = bits[k] == 1
                        k += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        tests = (
            lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
            lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
        )[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.function[y][x] and tests(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        size, grid = self.size, self.dark
        score = 0
        for lines in (grid, [list(col) for col in zip(*grid)]):
            for line in lines:
                run = 1
                for i in range(1, size):
                    if line[i] == line[i - 1]:
                        run += 1
                        continue
                    score += run - 2 if run >= 5 else 0
                    run = 1
                score += run - 2 if run >= 5 else 0
                text = "".join("1" if v else "0" for v in line)
                score += 40 * (text.count("10111010000") + text.count("00001011101"))
        for y in range(size - 1):
            for x in range(size - 1):
                if grid[y][x] == grid[y][x + 1] == grid[y + 1][x] == grid[y + 1][x + 1]:
                    score += 3
        dark = sum(map(sum, grid))
        score += 10 * ((abs(dark * 20 - size * size * 10) + size * size - 1) // (size * size) - 1)
        return score


def encode(text: str, level: str = "M") -> list[list[bool]]:
    """The code as rows of dark (True) and light modules, without the quiet zone."""
    if level not in _FORMAT_BITS:
        raise QRError("Error correction must be L or M.")
    data = text.encode("utf-8")
    for version in range(1, MAX_VERSION + 1):
        if len(data) <= _data_codewords(version, level) - (3 if version >= 10 else 2):
            break
    else:
        raise QRError("That is too long for a QR code here.")
    words = _codewords(data, version, level)
    best = None
    for mask in range(8):
        grid = _Grid(version)
        grid.draw_function_patterns(level)
        grid.place_data(words)
        grid.apply_mask(mask)
        grid.draw_format(level, mask)
        score = grid.penalty()
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1].dark


def to_svg(text: str, level: str = "M", scale: int = 1, quiet: int = 4) -> str:
    """The code as a standalone SVG: black on white (a light border is needed to scan, in any theme)."""
    modules = encode(text, level)
    size = len(modules)
    total = size + quiet * 2
    cells = "".join(
        f"M{x + quiet} {y + quiet}h1v1h-1z" for y, row in enumerate(modules) for x, dark in enumerate(row) if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" width="{total * scale}" '
        f'height="{total * scale}" shape-rendering="crispEdges" role="img" aria-label="QR code">'
        f'<rect width="{total}" height="{total}" fill="#fff"/><path d="{cells}" fill="#000"/></svg>'
    )
