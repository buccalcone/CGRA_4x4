# 例 3: t = a*x[i]; acc += t; y[i] = acc + b（N = 16）。x[] は 0 番地、y[] は 512 番地から
        li   a0, 0              # p = &x[0]
        li   a1, 64             # 終わりの番地 4N
        li   s1, 3              # a
        li   s0, 0              # acc
loop:
        lw   t0, 0(a0)          # x[i]
        mul  t0, t0, s1         # t = a*x[i]
        add  s0, s0, t0         # acc += t
        addi t1, s0, 7          # acc + b
        sw   t1, 512(a0)        # y[i]
        addi a0, a0, 4
        bne  a0, a1, loop
        ecall
