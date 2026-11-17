# 例 1: y[i] = a*x[i] + b（N = 16）。x[] は 0 番地、y[] は 512 番地から
        li   a0, 0              # p = &x[0]
        li   a1, 64             # 終わりの番地 4N
        li   s1, 3              # a
loop:
        lw   t0, 0(a0)          # x[i]
        mul  t0, t0, s1         # a*x[i]
        addi t0, t0, 7          # + b
        sw   t0, 512(a0)        # y[i]
        addi a0, a0, 4
        bne  a0, a1, loop
        ecall
