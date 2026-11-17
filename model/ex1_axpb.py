"""例 1: y[i] = a*x[i] + b を 4x4 メッシュに II=1 でマッピングする"""
from cgra_sim import CGRA

N, A, B = 16, 3, 7
XB, YB = 0, 512                    # x[] は 0 番地から、y[] は 512 番地から（バイト番地）

g = CGRA(rows=4, cols=4, ii=1)
g.store_words(XB, [i * 10 for i in range(N)])

# 各 PE は毎サイクル同じ命令を繰り返す。p は x[i] の番地 4i
g.place(0, 0, ["addi x5, x5, 4"], init_out=-4)           # p = 4t
g.place(1, 0, [f"lw   x5, {XB}(x1)"])                     # x[i]        (t+1)
g.place(1, 1, ["mul  x5, x4, x8"], regs=[A, 0, 0, 0])     # a*x[i]      (t+2) a は r0
g.place(2, 1, [f"addi x5, x1, {B}"])                      # +b          (t+3)
g.place(3, 0, ["addi x5, x5, 4"], init_out=-16)          # p' = 4(t-3) 複製カウンタ
g.place(2, 0, [f"sw   x2, {YB}(x3)"])                     # y[i]        (t+4)

CYCLES = N + 4                                            # (N-1)*II + 深さ 4 + 1
for t in range(CYCLES):
    g.step()
    if t < 8:
        print(f"t={t:2d}: p={g.pes[0][0].out:3d} x={g.pes[1][0].out:4d} "
              f"ax={g.pes[1][1].out:4d} y={g.pes[2][1].out:4d} "
              f"p'={g.pes[3][0].out:3d} st={g.stores[-1][4]:4d}@{g.stores[-1][3]}")

expect = [A * (i * 10) + B for i in range(N)]
got = g.load_words(YB, N)
print("OK" if got == expect else f"NG {got}")
print(f"{N} iterations in {CYCLES} cycles (II=1)")
