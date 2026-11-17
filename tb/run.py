"""参照モデルと Verilog の答え合わせ（ENUM Journal Vol.1 第 2 章）

例 1〜3（model/ex*.py）を参照モデルで走らせて、設定・メモリの初期値・毎サイクルの
出力レジスタとストア・実行後のメモリを記録する。同じ設定を Icarus Verilog の
テストベンチ（tb_cgra.v）で走らせ、記録が 1 行残らず一致するかを比べる。
あわせて、Verilog の記録から「最後の結果が書かれたサイクル」を数えて表示する。

使い方: python3 run.py        （要 iverilog）
"""
import contextlib, io, os, runpy, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "..", "model")
RTL = os.path.join(HERE, "..", "rtl")
OUT = os.path.join(HERE, "..", "build")
MASK = 0xFFFF_FFFF

sys.path.insert(0, MODEL)
import cgra_sim  # noqa: E402

cases = []

class Recorder(cgra_sim.CGRA):
    """参照モデルに記録係を足したもの。例のスクリプトからは普通の CGRA に見える"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = None
        cases.append(self)

    def step(self):
        if self.log is None:                 # 最初のサイクルの直前に設定とメモリを控える
            self.cfg, self.mem0, self.log = [], list(self.mem), []
            for k, pe in enumerate(pe for row in self.pes for pe in row):
                self.cfg += [(k << 4 | s, w) for s, w in enumerate(pe.ctxs)]
                self.cfg += [(k << 4 | 8, pe.out)]
                self.cfg += [(k << 4 | 12 + j, v) for j, v in enumerate(pe.regs)]
        n = len(self.stores)
        super().step()
        t = self.cycle - 1
        for _, r, c, addr, val in self.stores[n:]:
            self.log.append(f"s {t} {r} {c} {addr & MASK:08x} {val & MASK:08x}")
        self.log.append(f"o {t} " + " ".join(f"{pe.out & MASK:08x}" for row in self.pes for pe in row))

def collect():
    """例のスクリプトを参照モデル（記録係つき）で実行する"""
    cgra_sim.CGRA = Recorder
    for ex in ("ex1_axpb", "ex2_dot", "ex3_acc"):
        start = len(cases)
        with contextlib.redirect_stdout(io.StringIO()):
            ns = runpy.run_path(os.path.join(MODEL, ex + ".py"), run_name="__main__")
        for j, g in enumerate(cases[start:]):
            g.name = ex if len(cases) - start == 1 else f"{ex}_{j}"
            g.expect, g.yb, g.n = ns["expect"], ns.get("YB"), ns["N"]
    return cases

def check(g):
    """1 ケースを Verilog で走らせて、参照モデルの記録と比べる"""
    base = os.path.join(OUT, g.name)
    cycles = sum(1 for line in g.log if line.startswith("o "))
    with open(base + ".meta", "w") as f:
        f.write(f"{g.II - 1:x}\n{cycles:x}\n{len(g.cfg):x}\n")
    with open(base + ".cfg", "w") as f:
        f.writelines(f"{a:x}\n{v & MASK:08x}\n" for a, v in g.cfg)
    with open(base + ".mem", "w") as f:
        f.writelines(f"{v & MASK:08x}\n" for v in g.mem0)
    expect = g.log + [f"m {k} {v & MASK:08x}" for k, v in enumerate(g.mem)]

    sim = base + ".vvp"
    subprocess.run(["iverilog", "-g2005", "-o", sim, "-s", "tb",
                    f"-Ptb.R={g.R}", f"-Ptb.C={g.C}", f'-Ptb.CASE="{base}"',
                    os.path.join(HERE, "tb_cgra.v"),
                    os.path.join(RTL, "cgra_top.v"), os.path.join(RTL, "cgra_pe.v")], check=True)
    subprocess.run(["vvp", "-n", sim], check=True, stdout=subprocess.DEVNULL)
    got = open(base + ".vlog").read().splitlines()

    for i, (e, v) in enumerate(zip(expect, got)):
        if e != v:
            return f"NG（{i + 1} 行目）\n  参照モデル: {e}\n  Verilog   : {v}"
    if len(expect) != len(got):
        return f"NG（行数が違う：参照モデル {len(expect)}、Verilog {len(got)}）"
    done = done_cycle(g, got)
    if done != cycles:
        return f"NG（最後の結果が {done} サイクル目に出た。回したのは {cycles} サイクル）"
    return f"OK（{g.R}x{g.C}, II={g.II}, {done} サイクルで完了, {len(got)} 行一致）"

def done_cycle(g, log):
    """Verilog の記録から、最後の結果が書かれたサイクル数（1 始まり）を数える"""
    if isinstance(g.expect, list):               # y[] に書く例：最後の要素のストア
        last = f"{(g.yb + 4 * (g.n - 1)) & MASK:08x} {g.expect[-1] & MASK:08x}"
        hits = [int(line.split()[1]) for line in log if line.startswith("s ") and line.endswith(last)]
    else:                                        # 内積：合計が初めて出力レジスタに現れたサイクル
        hits = [int(line.split()[1]) for line in log
                if line.startswith("o ") and f"{g.expect & MASK:08x}" in line.split()[2:]][:1]
    return hits[-1] + 1 if hits else None

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    results = [(g.name, check(g)) for g in collect()]
    for name, res in results:
        print(f"{name:10s} {res}")
    sys.exit(0 if all(r.startswith("OK") for _, r in results) else 1)
