"""例 2: 内積 acc += x[i]*w[i] を (a) 4x4 II=1 と (b) 2x2 II=2 でマッピングする"""
from cgra_sim import CGRA

N = 16
x = [i + 1 for i in range(N)]        # 1..16
w = [2 * i for i in range(N)]        # 0,2,4,...
expect = sum(a * b for a, b in zip(x, w))
XB, WB = 0, 256                      # バイト番地

def run_4x4():
    g = CGRA(4, 4, ii=1)
    g.store_words(XB, x)
    g.store_words(WB, w)
    g.place(0, 0, ["addi x5, x5, 4"], init_out=-4)       # p = 4t
    g.place(1, 0, [f"lw   x5, {XB}(x1)"])                 # x[i]     (t+1)
    g.place(1, 1, ["addi x5, x4, 0"])                     # x[i]     (t+2) 遅延合わせ
    g.place(3, 0, ["addi x5, x5, 4"], init_out=-8)       # p' = 4(t-1)
    g.place(2, 0, [f"lw   x5, {WB}(x3)"])                 # w[i]     (t+2)
    g.place(2, 1, ["mul  x5, x1, x4"])                    # x*w      (t+3)
    g.place(2, 2, ["add  x8, x4, x8"])                    # acc      (t+4) r0 に累算
    cycles = N + 4
    g.run(cycles)
    return g.pes[2][2].regs[0], cycles

def run_2x2():
    g = CGRA(2, 2, ii=2)
    g.store_words(XB, x)
    g.store_words(WB, w)
    # ctx0（偶数サイクル 2i）         ctx1（奇数サイクル 2i+1）
    g.place(0, 0, ["addi x8, x8, 4",  f"lw x5, {XB}(x5)"], regs=[-4, 0, 0, 0])
                                                          # A: p / x[i]
    g.place(1, 0, ["nop",             f"lw x5, {WB}(x1)"])  # B: 保持 / w[i]
    g.place(0, 1, ["addi x5, x4, 0",  "nop"])             # C: x[i] を東へ / 保持
    g.place(1, 1, ["add  x8, x5, x8", "mul x5, x1, x4"])  # D: acc += p / p = x*w
    cycles = 2 * N + 3                                    # (N-1)*2 + 深さ 4 + 1
    g.run(cycles)
    return g.pes[1][1].regs[0], cycles

for name, fn in [("4x4 II=1", run_4x4), ("2x2 II=2", run_2x2)]:
    got, cyc = fn()
    print(f"{name}: acc={got} expect={expect} {'OK' if got == expect else 'NG'} "
          f"({N} iterations in {cyc} cycles)")
