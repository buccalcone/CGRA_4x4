# 例 2: 内積 acc += x[i]*w[i]（N = 16）。x[] は 0 番地、w[] は 256 番地から
        li   a0, 0              # p = &x[0]
        li   a1, 64             # 終わりの番地 4N
        li   s0, 0              # acc
loop:
        lw   t0, 0(a0)          # x[i]
        lw   t1, 256(a0)        # w[i]
        mul  t0, t0, t1         # x[i]*w[i]
        add  s0, s0, t0         # acc += ...
        addi a0, a0, 4
        bne  a0, a1, loop
        ecall
