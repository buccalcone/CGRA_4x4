// =====================================================================
//  rv32_cpu のテストベンチ（ENUM Journal Vol.1 第 3 章の比較用）
//  PROG.imem / PROG.dmem を読み込んで停止まで走らせ、1 サイクル 1 行の記録を PROG.vlog に書く。
//  書式は rv32.py の CPU.log と同じ：
//    r <サイクル> <PC> x<番号> <値>            … レジスタへの書き込み
//    s <サイクル> <PC> <番地> <funct3> <rs2>    … ストア
//    n <サイクル> <PC>                          … どこにも書かない命令
//    h <サイクル> <PC>                          … ecall / ebreak（停止）
//  停止後に x1..x31 とデータメモリを書き出す。
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_cpu;
    parameter PROG = "prog";

    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg  rst = 1'b1;
    wire halted;

    rv32_cpu dut (.clk(clk), .rst(rst), .halted(halted));

    integer t, k, fd;
    initial begin
        $readmemh({PROG, ".imem"}, dut.imem);
        $readmemh({PROG, ".dmem"}, dut.dmem);
        fd = $fopen({PROG, ".vlog"}, "w");

        @(negedge clk) rst = 1'b0;
        t = 0;
        while (!halted && t < 100000) begin
            #1;
            if (dut.opc == 7'h73)
                $fdisplay(fd, "h %0d %08x", t, dut.pc);
            else if (dut.is_store)
                $fdisplay(fd, "s %0d %08x %08x %0d %08x", t, dut.pc, dut.addr, dut.f3, dut.r2);
            else if (dut.we && dut.rd != 5'd0)
                $fdisplay(fd, "r %0d %08x x%0d %08x", t, dut.pc, dut.rd, dut.wdata);
            else
                $fdisplay(fd, "n %0d %08x", t, dut.pc);
            @(posedge clk) #1;
            t = t + 1;
            @(negedge clk);
        end
        for (k = 1; k < 32; k = k + 1)  $fdisplay(fd, "x %0d %08x", k, dut.xreg[k]);
        for (k = 0; k < 256; k = k + 1) $fdisplay(fd, "m %0d %08x", k, dut.dmem[k]);
        $fclose(fd);
        $finish;
    end
endmodule

`default_nettype wire
