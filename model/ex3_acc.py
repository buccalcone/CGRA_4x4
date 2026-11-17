"""例 3: 累算つきループを 4x4 メッシュに II=1 でマッピングする
    t = a*x[i]; acc = acc + t; y[i] = acc + b
"""
from cgra_sim import CGRA

N, A, B = 16, 3, 7
XB, YB = 0, 512                                          # バイト番地

g = CGRA(4, 4, ii=1)
g.store_words(XB, [i + 1 for i in range(N)])             # x = 1..16

g.place(0, 0, ["addi x5, x5, 4"], init_out=-4)          # p = 4t
g.place(1, 0, [f"lw   x5, {XB}(x1)"])                    # x[i]       (t+1)
g.place(1, 1, ["mul  x5, x4, x8"], regs=[A, 0, 0, 0])    # a*x[i]     (t+2) a は r0
g.place(1, 2, ["add  x8, x4, x8"])                       # acc += t   (t+3) 前の反復の acc は r0
g.place(2, 2, [f"addi x5, x1, {B}"])                     # acc + b    (t+4)
g.place(2, 1, ["addi x5, x2, 0"])                        # 西へ転送   (t+5)
g.place(3, 0, ["addi x5, x5, 4"], init_out=-24)         # p' = 4(t-5) 複製カウンタ
g.place(2, 0, [f"sw   x2, {YB}(x3)"])                    # y[i]       (t+6)

g.run(N + 6)

acc, expect = 0, []
for i in range(N):
    acc += A * (i + 1)
    expect.append(acc + B)
got = g.load_words(YB, N)
print("OK" if got == expect else f"NG {got}")
print(f"{N} iterations in {N + 6} cycles (II=1), acc={g.pes[1][2].regs[0]}")
