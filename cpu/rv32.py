"""比較用の RV32I（＋mul）シングルサイクル CPU：アセンブラと命令レベルシミュレータ
（ENUM Journal Vol.1 第 3 章の比較用。本筋ではないのでリポジトリにだけ置く）

- 命令は RV32I すべてと、M 拡張の mul。ecall / ebreak で停止する。fence は何もしない。
- 1 命令を 1 サイクルで実行する（パイプラインが無いのでハザードも無い）。
- 命令メモリとデータメモリは別。データメモリはバイト番地で、大きさで折り返す。
"""
MASK = 0xFFFF_FFFF

def s32(v):
    v &= MASK
    return v - (1 << 32) if v & 0x8000_0000 else v

ABI = {"zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4, "t0": 5, "t1": 6, "t2": 7,
       "s0": 8, "fp": 8, "s1": 9, **{f"a{i}": 10 + i for i in range(8)},
       **{f"s{i}": 16 + i for i in range(2, 12)}, **{f"t{i}": 25 + i for i in range(3, 7)}}

R_OPS = {"add": (0x00, 0), "sub": (0x20, 0), "sll": (0x00, 1), "slt": (0x00, 2),
         "sltu": (0x00, 3), "xor": (0x00, 4), "srl": (0x00, 5), "sra": (0x20, 5),
         "or": (0x00, 6), "and": (0x00, 7), "mul": (0x01, 0)}
I_OPS = {"addi": 0, "slti": 2, "sltiu": 3, "xori": 4, "ori": 6, "andi": 7}
SH_OPS = {"slli": (0x00, 1), "srli": (0x00, 5), "srai": (0x20, 5)}
LOADS = {"lb": 0, "lh": 1, "lw": 2, "lbu": 4, "lhu": 5}
STORES = {"sb": 0, "sh": 1, "sw": 2}
BRANCHES = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}

def reg(s):
    if s in ABI:
        return ABI[s]
    n = int(s[1:]) if s[:1] == "x" and s[1:].isdigit() else -1
    assert 0 <= n < 32, f"レジスタ名が不正: {s}"
    return n

def assemble(src):
    """アセンブリ（ラベル・# コメント可）を 32 ビット語の列にする"""
    lines, labels = [], {}
    for line in src.splitlines():
        line = line.split("#")[0].strip()
        if line.endswith(":"):
            labels[line[:-1]] = 4 * len(lines)
        elif line:
            lines.append(line)
    return [encode(line, 4 * k, labels) for k, line in enumerate(lines)]

def encode(text, pc, labels):
    op, _, rest = text.partition(" ")
    a = [t.strip() for t in rest.replace("(", ",").replace(")", "").split(",") if t.strip()]
    imm = lambda s: labels[s] - pc if s in labels else int(s, 0)
    if op == "nop":
        op, a = "addi", ["x0", "x0", "0"]
    elif op == "li":                                  # 12 ビットに収まる即値だけ
        op, a = "addi", [a[0], "x0", a[1]]
    elif op == "mv":
        op, a = "addi", [a[0], a[1], "0"]
    elif op == "j":
        op, a = "jal", ["x0", a[0]]
    if op in R_OPS:
        (f7, f3), (rd, rs1, rs2) = R_OPS[op], map(reg, a)
        return f7 << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | rd << 7 | 0x33
    if op in I_OPS or op in SH_OPS:
        rd, rs1, v = reg(a[0]), reg(a[1]), imm(a[2])
        if op in SH_OPS:
            f7, f3 = SH_OPS[op]
            v = f7 << 5 | (v & 0x1F)
        else:
            f3 = I_OPS[op]
        return (v & 0xFFF) << 20 | rs1 << 15 | f3 << 12 | rd << 7 | 0x13
    if op in LOADS or op == "jalr":                   # op rd, imm(rs1)
        rd, v, rs1 = reg(a[0]), imm(a[1]), reg(a[2])
        f3, opc = (LOADS[op], 0x03) if op in LOADS else (0, 0x67)
        return (v & 0xFFF) << 20 | rs1 << 15 | f3 << 12 | rd << 7 | opc
    if op in STORES:                                  # op rs2, imm(rs1)
        rs2, v, rs1 = reg(a[0]), imm(a[1]), reg(a[2])
        return ((v >> 5) & 0x7F) << 25 | rs2 << 20 | rs1 << 15 | STORES[op] << 12 | (v & 0x1F) << 7 | 0x23
    if op in BRANCHES:                                # op rs1, rs2, label
        rs1, rs2, v = reg(a[0]), reg(a[1]), imm(a[2])
        return ((v >> 12) & 1) << 31 | ((v >> 5) & 0x3F) << 25 | rs2 << 20 | rs1 << 15 | \
               BRANCHES[op] << 12 | ((v >> 1) & 0xF) << 8 | ((v >> 11) & 1) << 7 | 0x63
    if op == "jal":                                   # jal rd, label
        rd, v = reg(a[0]), imm(a[1])
        return ((v >> 20) & 1) << 31 | ((v >> 1) & 0x3FF) << 21 | ((v >> 11) & 1) << 20 | \
               ((v >> 12) & 0xFF) << 12 | rd << 7 | 0x6F
    if op in ("lui", "auipc"):
        rd, v = reg(a[0]), int(a[1], 0)
        return (v & 0xFFFFF) << 12 | rd << 7 | (0x37 if op == "lui" else 0x17)
    if op in ("ecall", "ebreak"):
        return 0x73 if op == "ecall" else 0x0010_0073
    if op == "fence":
        return 0x0FF0_000F
    raise ValueError(f"未対応の命令: {text}")

def alu(f3, f7, a, b):
    if f7 == 0x01:
        return a * b
    sh = b & 0x1F
    return {0: a - b if f7 == 0x20 else a + b, 1: a << sh,
            2: int(s32(a) < s32(b)), 3: int((a & MASK) < (b & MASK)), 4: a ^ b,
            5: s32(a) >> sh if f7 == 0x20 else (a & MASK) >> sh, 6: a | b, 7: a & b}[f3]

class CPU:
    def __init__(self, prog, mem_words=256, imem_words=256):
        self.imem = list(prog) + [0] * (imem_words - len(prog))
        self.mem = [0] * mem_words
        self.x = [0] * 32
        self.pc = self.cycle = 0
        self.halted = False
        self.log = []                                 # 1 サイクル 1 行の記録

    def step(self):
        pc, w = self.pc, self.imem[(self.pc >> 2) % len(self.imem)]
        opc, rd, f3 = w & 0x7F, (w >> 7) & 0x1F, (w >> 12) & 7
        r1, r2 = self.x[(w >> 15) & 0x1F], self.x[(w >> 20) & 0x1F]
        f7, imm_i, t = w >> 25, s32(w) >> 20, self.cycle
        imm_s = (s32(w) >> 25) << 5 | (w >> 7) & 0x1F
        imm_b = (s32(w) >> 31) << 12 | ((w >> 7) & 1) << 11 | ((w >> 25) & 0x3F) << 5 | ((w >> 8) & 0xF) << 1
        imm_j = (s32(w) >> 31) << 20 | ((w >> 12) & 0xFF) << 12 | ((w >> 20) & 1) << 11 | ((w >> 21) & 0x3FF) << 1
        npc, val = pc + 4, None
        if opc == 0x33:
            val = alu(f3, f7, r1, r2)
        elif opc == 0x13:
            val = alu(f3, f7 if f3 in (1, 5) else 0, r1, imm_i)
        elif opc == 0x03:                             # ロード
            addr = r1 + imm_i
            word = self.mem[(addr >> 2) % len(self.mem)] & MASK
            b, h = (word >> 8 * (addr & 3)) & 0xFF, (word >> 8 * (addr & 2)) & 0xFFFF
            val = {0: s32(b << 24) >> 24, 1: s32(h << 16) >> 16, 4: b, 5: h}.get(f3, word)
        elif opc == 0x23:                             # ストア
            addr, k = r1 + imm_s, ((r1 + imm_s) >> 2) % len(self.mem)
            word, sh = self.mem[k] & MASK, 8 * (addr & 3)
            if f3 == 0:
                word = word & ~(0xFF << sh) | (r2 & 0xFF) << sh
            elif f3 == 1:
                sh = 8 * (addr & 2)
                word = word & ~(0xFFFF << sh) | (r2 & 0xFFFF) << sh
            else:
                word = r2
            self.mem[k] = s32(word)
            self.log.append(f"s {t} {pc:08x} {addr & MASK:08x} {f3} {r2 & MASK:08x}")
        elif opc == 0x63:                             # 分岐
            take = {0: r1 == r2, 1: r1 != r2, 4: s32(r1) < s32(r2), 5: s32(r1) >= s32(r2),
                    6: (r1 & MASK) < (r2 & MASK), 7: (r1 & MASK) >= (r2 & MASK)}.get(f3, False)
            npc = pc + imm_b if take else pc + 4
        elif opc == 0x6F:
            val, npc = pc + 4, pc + imm_j
        elif opc == 0x67:
            val, npc = pc + 4, (r1 + imm_i) & ~1
        elif opc == 0x37:
            val = w & 0xFFFFF000
        elif opc == 0x17:
            val = pc + (w & 0xFFFFF000)
        elif opc == 0x73:                             # ecall / ebreak で止まる
            self.log.append(f"h {t} {pc:08x}")
            self.halted, npc = True, pc
        if val is not None and rd != 0:
            self.x[rd] = s32(val)
            self.log.append(f"r {t} {pc:08x} x{rd} {val & MASK:08x}")
        elif opc not in (0x23, 0x73):
            self.log.append(f"n {t} {pc:08x}")
        self.pc = npc & MASK
        self.cycle += 1

    def run(self, max_cycles=100_000):
        while not self.halted and self.cycle < max_cycles:
            self.step()
        return self.cycle
