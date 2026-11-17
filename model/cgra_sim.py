"""最小 CGRA シミュレータ（ENUM Journal Vol.1 第 2 章の参照モデル）

- R x C のメッシュ。各 PE は ALU 1 個・出力レジスタ out・汎用レジスタ r0..r3。
- 命令は RV32I（＋M 拡張の mul）の 32 ビット語。レジスタ番号の意味だけ読み替える：
    x0 = 0 / x1..x4 = 隣の N, E, S, W の前サイクル出力 / x5 = self（自分の前サイクル出力）
    x8..x11 = r0..r3
- 書き込み先 rd：x0 なら何も書かない（nop は値を保持する）、x5 なら out、
  x8..x11 なら r0..r3 と out の両方に書く。
- lw/sw は列 0 の PE だけ。番地はバイト単位（4 の倍数）で、メモリの大きさで折り返す。
  lw はサイクル開始時点のメモリを読み、sw はサイクルの終わりにまとめて反映する。
- 各 PE は II 個の命令を持ち、サイクル t には ctxs[t % II] を実行する。
"""
from dataclasses import dataclass, field

MASK = 0xFFFF_FFFF

def s32(v):
    """32 ビット符号付き整数として読む"""
    v &= MASK
    return v - (1 << 32) if v & 0x8000_0000 else v

# ---- アセンブラ（RV32I＋mul のうち、この CGRA で意味を持つ命令だけ） --------
R_OPS = {"add": (0x00, 0), "sub": (0x20, 0), "sll": (0x00, 1), "slt": (0x00, 2),
         "sltu": (0x00, 3), "xor": (0x00, 4), "srl": (0x00, 5), "sra": (0x20, 5),
         "or": (0x00, 6), "and": (0x00, 7), "mul": (0x01, 0)}   # (funct7, funct3)
I_OPS = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
SH_OPS = {"slli": (0x00, 1), "srli": (0x00, 5), "srai": (0x20, 5)}

def reg(s):
    n = int(s[1:]) if s[:1] == "x" and s[1:].isdigit() else -1
    assert 0 <= n < 32, f"レジスタ名が不正: {s}"
    return n

def asm(text):
    """1 命令をアセンブルして 32 ビット語を返す。例: asm("addi x5, x5, 4")"""
    op, _, rest = text.strip().partition(" ")
    a = [t.strip() for t in rest.replace("(", ",").replace(")", "").split(",") if t.strip()]
    if op == "nop":
        return asm("addi x0, x0, 0")
    if op in R_OPS:                                   # op rd, rs1, rs2
        (f7, f3), (rd, rs1, rs2) = R_OPS[op], map(reg, a)
        return f7 << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | rd << 7 | 0x33
    if op in I_OPS or op in SH_OPS:                   # op rd, rs1, imm
        rd, rs1, imm = reg(a[0]), reg(a[1]), int(a[2], 0)
        if op in SH_OPS:
            f7, f3 = SH_OPS[op]
            imm = f7 << 5 | (imm & 0x1F)
        else:
            f3 = I_OPS[op]
        return (imm & 0xFFF) << 20 | rs1 << 15 | f3 << 12 | rd << 7 | 0x13
    if op == "lw":                                    # lw rd, imm(rs1)
        rd, imm, rs1 = reg(a[0]), int(a[1], 0), reg(a[2])
        return (imm & 0xFFF) << 20 | rs1 << 15 | 2 << 12 | rd << 7 | 0x03
    if op == "sw":                                    # sw rs2, imm(rs1)
        rs2, imm, rs1 = reg(a[0]), int(a[1], 0), reg(a[2])
        return ((imm >> 5) & 0x7F) << 25 | rs2 << 20 | rs1 << 15 | 2 << 12 | (imm & 0x1F) << 7 | 0x23
    if op == "lui":                                   # lui rd, imm20
        rd, imm = reg(a[0]), int(a[1], 0)
        return (imm & 0xFFFFF) << 12 | rd << 7 | 0x37
    raise ValueError(f"未対応の命令: {text}")

# ---- ALU ------------------------------------------------------------------
def alu(f3, f7, a, b):
    """f7 は R 形式とシフトのときだけ意味を持つ（それ以外は 0 を渡す）"""
    if f7 == 0x01:
        return a * b                                  # mul（M 拡張から借用）
    sh = b & 0x1F
    return {0: a - b if f7 == 0x20 else a + b, 1: a << sh,
            2: int(s32(a) < s32(b)), 3: int((a & MASK) < (b & MASK)), 4: a ^ b,
            5: s32(a) >> sh if f7 == 0x20 else (a & MASK) >> sh, 6: a | b, 7: a & b}[f3]

@dataclass
class PE:
    out: int = 0                                      # 出力レジスタ（隣が次サイクルに読む）
    regs: list = field(default_factory=lambda: [0, 0, 0, 0])
    ctxs: list = field(default_factory=list)          # 32 ビット命令語 × II

class CGRA:
    def __init__(self, rows, cols, ii, mem_words=256):
        self.R, self.C, self.II = rows, cols, ii
        self.pes = [[PE(ctxs=[asm("nop")] * ii) for _ in range(cols)] for _ in range(rows)]
        self.mem = [0] * mem_words                    # 32 ビット語の配列
        self.cycle = 0
        self.stores = []                              # (サイクル, r, c, 番地, 値) の記録

    def place(self, r, c, ctxs, init_out=0, regs=None):
        """PE(r,c) に II 個の命令を置く。文字列ならアセンブルする"""
        assert len(ctxs) == self.II, f"PE({r},{c}): {self.II} 個の命令が必要"
        pe = self.pes[r][c]
        pe.ctxs = [asm(w) if isinstance(w, str) else w for w in ctxs]
        pe.out = init_out
        if regs:
            pe.regs = list(regs)
        for w in pe.ctxs:
            opc, rd = w & 0x7F, (w >> 7) & 0x1F
            assert opc in (0x33, 0x13, 0x03, 0x23, 0x37), f"PE({r},{c}): 未対応 {w:08x}"
            assert opc not in (0x03, 0x23) or c == 0, f"PE({r},{c}): lw/sw は列 0 のみ"
            assert opc == 0x23 or rd in (0, 5, 8, 9, 10, 11), f"PE({r},{c}): 書き込み先 x{rd} は使えない"

    def store_words(self, addr, values):              # バイト番地 addr から語を並べる
        for k, v in enumerate(values):
            self.mem[(addr >> 2) + k] = s32(v)

    def load_words(self, addr, n):
        return self.mem[addr >> 2:(addr >> 2) + n]

    def _read(self, r, c, x, prev_out):
        """レジスタ番号 x を解決する。prev_out は全 PE の前サイクル出力のスナップショット"""
        if x == 0:
            return 0
        if 1 <= x <= 4:
            dr, dc = ((-1, 0), (0, 1), (1, 0), (0, -1))[x - 1]  # N, E, S, W
            nr, nc = r + dr, c + dc
            assert 0 <= nr < self.R and 0 <= nc < self.C, f"PE({r},{c}): x{x} は端の外"
            return prev_out[nr][nc]
        if x == 5:
            return prev_out[r][c]
        assert 8 <= x <= 11, f"PE({r},{c}): x{x} は使えない"
        return self.pes[r][c].regs[x - 8]

    def step(self):
        k = self.cycle % self.II
        prev_out = [[pe.out for pe in row] for row in self.pes]   # 同時更新の要
        pending = []                                              # このサイクルのストア
        for r in range(self.R):
            for c in range(self.C):
                pe, w = self.pes[r][c], self.pes[r][c].ctxs[k]
                opc, rd, f3 = w & 0x7F, (w >> 7) & 0x1F, (w >> 12) & 7
                rs1, rs2, f7 = (w >> 15) & 0x1F, (w >> 20) & 0x1F, w >> 25
                imm_i = s32(w) >> 20                              # 符号拡張した 12 ビット
                rx = lambda x: self._read(r, c, x, prev_out)
                if opc == 0x33:                                   # R 形式
                    val = alu(f3, f7, rx(rs1), rx(rs2))
                elif opc == 0x13:                                 # I 形式の演算
                    val = alu(f3, f7 if f3 in (1, 5) else 0, rx(rs1), imm_i)
                elif opc == 0x37:                                 # lui
                    val = w & 0xFFFFF000
                elif opc == 0x03:                                 # lw
                    val = self.mem[((rx(rs1) + imm_i) >> 2) % len(self.mem)]
                else:                                             # sw（rd は無い）
                    addr = rx(rs1) + ((s32(w) >> 25) << 5 | (w >> 7) & 0x1F)
                    pending.append((r, c, addr, rx(rs2)))
                    continue
                if rd == 5 or 8 <= rd <= 11:
                    pe.out = s32(val)
                if 8 <= rd <= 11:
                    pe.regs[rd - 8] = s32(val)
        for r, c, addr, val in pending:                           # ストアはサイクルの終わりに反映
            self.mem[(addr >> 2) % len(self.mem)] = val
            self.stores.append((self.cycle, r, c, addr, val))
        self.cycle += 1

    def run(self, cycles):
        for _ in range(cycles):
            self.step()
