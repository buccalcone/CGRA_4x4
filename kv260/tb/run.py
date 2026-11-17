"""AXI ラッパの答え合わせ（ENUM Journal Vol.1 おまけ）

第 2 章の例 1〜3 を参照モデルで走らせ（第 2 章の tb/run.py を借りる）、同じ設定を
AXI4-Lite 越しに cgra_axi へ書き込んで実行する。KV260 に載せるのと同じ 4x4 で回し、
2x2 の例はアレイの左上に置く。毎サイクルの出力レジスタ・run が 1 だったサイクル数・
実行後のメモリが参照モデルと一致するかを、2 回続けて回して確かめる。

答えを PE のレジスタに残して終わる例（例 2 の内積）は、実行後にコンテキストだけを
書き換えて「読み出し」を走らせ、答えをメモリの最後の語に書かせてから読む。
答えのある PE から同じ行を列 0 まで西へ 1 マスずつ素通しし、列 0 の PE が sw する。

確かめたテストベクタは build/cases.json に書き出す。KV260 では board/cgra_run.py が
これを読んで同じ手順を踏み、メモリから読んだ値を期待値と比べる。

使い方: python3 run.py        （要 iverilog）
"""
import contextlib, importlib.util, io, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.join(HERE, "..", "rtl")
CGRA = os.path.join(HERE, "..", "..")
OUT = os.path.join(HERE, "..", "build")
MASK = 0xFFFF_FFFF
R, C, MEM_WORDS = 4, 4, 256                  # KV260 に載せる大きさ（cgra_axi の既定値）
RD_WORD = MEM_WORDS - 1                      # 読み出しで答えを書く語番地

# 答えを PE のレジスタに残す例：(行, 列, レジスタ)。model/ex2_dot.py の return と同じ場所
RESULT_IN = {"ex2_dot_0": (2, 2, "r0"), "ex2_dot_1": (1, 1, "r0")}

def collect():
    """第 2 章の tb/run.py で、例 1〜3 を参照モデル（記録係つき）で実行する"""
    spec = importlib.util.spec_from_file_location("cgra_tb", os.path.join(CGRA, "tb", "run.py"))
    tb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb)
    with contextlib.redirect_stdout(io.StringIO()):
        return tb, tb.collect()

def place(g, r, c):
    """例の中の PE (r, c) の、4x4 での PE 番号"""
    assert r < R and c < C
    return r * C + c

def readout(asm, g, r, c, src):
    """PE (r, c) の src（out か r0..r3）を語番地 RD_WORD に書かせる設定と、回すサイクル数"""
    x = 5 if src == "out" else 8 + int(src[1])
    prog = {}
    if c == 0:
        prog[(r, 0)] = f"sw x{x}, {4 * RD_WORD}(x0)"
    else:
        prog[(r, c)] = "nop" if x == 5 else f"addi x5, x{x}, 0"   # out に出す（out ならそのまま）
        for j in range(1, c):
            prog[(r, j)] = "addi x5, x2, 0"                         # 東隣の out を素通し
        prog[(r, 0)] = f"sw x2, {4 * RD_WORD}(x0)"
    # 実行が止まったときのコンテキスト番号は分からないので、使っていた全スロットに同じ命令を書く。
    # 読み出しに使わない PE は nop にして止める
    cfg = [(k << 4 | s, asm(prog.get(divmod(k, C), "nop")))
           for k in range(R * C) for s in range(g.II)]
    return cfg, c + 1

def check(tb, g):
    base = os.path.join(OUT, g.name)
    cycles = sum(1 for line in g.log if line.startswith("o "))
    cfg = [(place(g, *divmod(a >> 4, g.C)) << 4 | a & 15, v & MASK) for a, v in g.cfg]
    case = {"name": g.name, "shape": f"{g.R}x{g.C}", "ii": g.II, "cycles": cycles, "cfg": cfg,
            "mem0": [v & MASK for v in g.mem0], "mem": [v & MASK for v in g.mem], "readout": None}
    if g.name in RESULT_IN:
        r, c, src = RESULT_IN[g.name]
        pe = g.pes[r][c]
        assert (pe.out if src == "out" else pe.regs[int(src[1])]) == g.expect
        rd_cfg, rd_cycles = readout(tb.cgra_sim.asm, g, r, c, src)
        case["readout"] = {"pe": [r, c, src], "cfg": [(a, v & MASK) for a, v in rd_cfg],
                           "cycles": rd_cycles, "word": RD_WORD, "expect": g.expect & MASK}

    with open(base + ".meta", "w") as f:
        f.write(f"{g.II - 1:x}\n{cycles:x}\n{len(cfg):x}\n")
    with open(base + ".cfg", "w") as f:
        f.writelines(f"{a:x}\n{v:08x}\n" for a, v in cfg)
    with open(base + ".mem", "w") as f:
        f.writelines(f"{v:08x}\n" for v in case["mem0"])
    rd = case["readout"]
    with open(base + ".rdmeta", "w") as f:
        f.write(f"{len(rd['cfg']) if rd else 0:x}\n{rd['cycles'] if rd else 0:x}\n{RD_WORD:x}\n")
    with open(base + ".rdcfg", "w") as f:
        f.writelines(f"{a:x}\n{v:08x}\n" for a, v in (rd["cfg"] if rd else [(0, 0)]))

    expect = []
    for p in range(2):
        for line in g.log:                   # 例の大きさの出力を 4x4 に広げる（使わない PE は 0）
            if line.startswith("o "):
                _, t, *vals = line.split()
                hw = ["00000000"] * (R * C)
                for k, v in enumerate(vals):
                    hw[place(g, *divmod(k, g.C))] = v
                expect.append(f"o {p} {t} " + " ".join(hw))
        expect += [f"n {p} {cycles}"] + [f"m {p} {k} {v:08x}" for k, v in enumerate(case["mem"])]
        if rd:
            expect.append(f"r {p} {rd['expect']:08x}")

    sim = base + ".axi.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", sim, "-s", "tb", f'-Ptb.CASE="{base}"',
                    os.path.join(HERE, "tb_axi.v"), os.path.join(RTL, "cgra_axi.v"),
                    os.path.join(CGRA, "rtl", "cgra_top.v"), os.path.join(CGRA, "rtl", "cgra_pe.v")],
                   check=True)
    subprocess.run(["vvp", "-n", sim], check=True, stdout=subprocess.DEVNULL)
    got = open(base + ".axi.vlog").read().splitlines()

    for i, (e, v) in enumerate(zip(expect, got)):
        if e != v:
            return case, f"NG（{i + 1} 行目）\n  参照モデル: {e}\n  AXI 経由  : {v}"
    if len(expect) != len(got):
        return case, f"NG（行数が違う：参照モデル {len(expect)}、AXI 経由 {len(got)}）"
    tail = f", 読み出し {rd['cycles']} サイクルで {rd['expect']}" if rd else ""
    return case, f"OK（{g.R}x{g.C}, II={g.II}, {cycles} サイクル{tail}, × 2 回, {len(got)} 行一致）"

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    tb, cases = collect()
    results = [(g.name, *check(tb, g)) for g in cases]
    for name, _, res in results:
        print(f"{name:10s} {res}")
    ok = all(r.startswith("OK") for _, _, r in results)
    if ok:
        with open(os.path.join(OUT, "cases.json"), "w") as f:
            json.dump([case for _, case, _ in results], f)
        print(f"テストベクタを {os.path.relpath(os.path.join(OUT, 'cases.json'))} に書いた")
    sys.exit(0 if ok else 1)
