"""比較用 CPU の答え合わせと、CGRA とのサイクル数の比較（ENUM Journal Vol.1 第 3 章）

1. 例 1〜3 と同じループを RV32I（＋mul）のアセンブリで書き（ex*.s）、
   命令レベルシミュレータ（rv32.py）で走らせて結果を確かめる。
2. 同じ命令列を Verilog の CPU（rv32_cpu.v）で走らせ、1 サイクルずつの記録と
   停止後のレジスタ・メモリが参照モデルと一致するかを比べる。
3. CGRA（model/ の参照モデル）のサイクル数と並べて表にする。

使い方: python3 run.py        （要 iverilog）
"""
import contextlib, importlib.util, io, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "build", "cpu")
sys.path.insert(0, HERE)
from rv32 import CPU, MASK, assemble  # noqa: E402

N, A, B = 16, 3, 7

def image(*blocks):
    """(バイト番地, 値の列) の組からデータメモリ 256 語の初期値を作る"""
    mem = [0] * 256
    for addr, values in blocks:
        mem[addr >> 2:(addr >> 2) + len(values)] = values
    return mem

def acc_plus_b(xs):
    acc, ys = 0, []
    for x in xs:
        acc += A * x
        ys.append(acc + B)
    return ys

X1 = [i * 10 for i in range(N)]                 # 例 1〜3 の CGRA 版と同じデータ
X2, W2 = [i + 1 for i in range(N)], [2 * i for i in range(N)]
X3 = [i + 1 for i in range(N)]
CASES = {   # 名前: (データメモリの初期値, 結果の確かめ方)
    "ex1_axpb": (image((0, X1)), lambda c: c.mem[128:128 + N] == [A * x + B for x in X1]),
    "ex2_dot":  (image((0, X2), (256, W2)), lambda c: c.x[8] == sum(x * w for x, w in zip(X2, W2))),
    "ex3_acc":  (image((0, X3)), lambda c: c.mem[128:128 + N] == acc_plus_b(X3)),
}

def loop_length(src):
    """ラベル loop: から分岐までの命令数（ループ 1 回ぶん）"""
    body = src.split("loop:")[1].split("ecall")[0]
    return sum(1 for line in body.splitlines() if line.split("#")[0].strip())

def check(name):
    src = open(os.path.join(HERE, name + ".s")).read()
    prog = assemble(src)
    mem0, ok = CASES[name]
    cpu = CPU(prog)
    cpu.mem = list(mem0)
    cycles = cpu.run()
    assert ok(cpu), f"{name}: 参照モデルの結果が期待値と違う"
    expect = cpu.log + [f"x {k} {cpu.x[k] & MASK:08x}" for k in range(1, 32)] + \
             [f"m {k} {v & MASK:08x}" for k, v in enumerate(cpu.mem)]

    base = os.path.join(OUT, name)
    with open(base + ".imem", "w") as f:
        f.writelines(f"{w:08x}\n" for w in cpu.imem)
    with open(base + ".dmem", "w") as f:
        f.writelines(f"{v & MASK:08x}\n" for v in mem0)
    sim = base + ".vvp"
    subprocess.run(["iverilog", "-g2005", "-o", sim, "-s", "tb_cpu", f'-Ptb_cpu.PROG="{base}"',
                    os.path.join(HERE, "tb_cpu.v"), os.path.join(HERE, "rv32_cpu.v")], check=True)
    subprocess.run(["vvp", "-n", sim], check=True, stdout=subprocess.DEVNULL)
    got = open(base + ".vlog").read().splitlines()
    halt = [int(line.split()[1]) for line in got if line.startswith("h ")]
    cycles = halt[0] + 1 if halt else None       # Verilog で数えた、ecall までのサイクル数
    for i, (e, v) in enumerate(zip(expect, got)):
        if e != v:
            return cycles, loop_length(src), f"NG（{i + 1} 行目）\n  参照: {e}\n  RTL : {v}"
    if len(expect) != len(got):
        return cycles, loop_length(src), f"NG（行数：参照 {len(expect)}、RTL {len(got)}）"
    return cycles, loop_length(src), f"OK（{len(got)} 行一致）"

def cgra_cycles():
    """CGRA の参照モデルで例 1〜3 を走らせ、サイクル数と使った PE の数を返す"""
    spec = importlib.util.spec_from_file_location("cgra_tb", os.path.join(HERE, "..", "tb", "run.py"))
    tb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tb)
    with contextlib.redirect_stdout(io.StringIO()):
        cases = tb.collect()
    nop = tb.cgra_sim.asm("nop")
    return [(g.name, f"{g.R}x{g.C} II={g.II}", sum(1 for line in g.log if line.startswith("o ")),
             sum(1 for row in g.pes for pe in row if any(w != nop for w in pe.ctxs))) for g in cases]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    cpu = {name: check(name) for name in CASES}
    for name, (_, _, res) in cpu.items():
        print(f"CPU {name:9s} {res}")
    print()
    print(f"{'例':10s} {'CPU 1 反復':>10s} {'CPU 合計':>8s}   {'CGRA':12s} {'合計':>5s} {'使った PE':>8s}")
    for name, shape, cyc, pes in cgra_cycles():
        c_cyc, c_loop, _ = cpu[name.rsplit("_", 1)[0] if name.startswith("ex2") else name]
        print(f"{name:10s} {c_loop:>7d} 命令 {c_cyc:>6d}   {shape:12s} {cyc:>5d} {pes:>6d}")
    sys.exit(0 if all(r.startswith("OK") for _, _, r in cpu.values()) else 1)
