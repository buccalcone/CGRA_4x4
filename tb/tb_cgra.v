// =====================================================================
//  cgra_top のテストベンチ（ENUM Journal Vol.1 第 2 章）
//  run.py が参照モデルから作ったテストベクタ（CASE.meta / .cfg / .mem）を読み、
//  設定 → メモリ初期化 → 実行 の順に進めて、毎サイクルの様子を CASE.vlog に書く。
//  書式は run.py が参照モデルから作る期待値（CASE.expect）と同じ：
//    s <サイクル> <行> <列> <番地> <値>   … そのサイクルのストア
//    o <サイクル> <PE0 の out> <PE1 の out> ...   … そのサイクル終了時の出力レジスタ
//    m <語番地> <値>                      … 実行後のメモリ
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb;
    parameter R = 4, C = 4, MAX_II = 8, MEM_WORDS = 256;
    parameter CASE = "case";                 // ファイル名の接頭辞（run.py が -P で渡す）

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg         rst = 1'b1, run = 1'b0, cfg_we = 1'b0, host_we = 1'b0;
    reg  [2:0]  ii_m1 = 3'd0;
    reg  [11:0] cfg_addr = 12'd0;
    reg  [31:0] cfg_wdata = 32'd0, host_wdata = 32'd0;
    reg  [$clog2(MEM_WORDS)-1:0] host_addr = 0;
    wire [31:0] host_rdata;

    cgra_top #(.R(R), .C(C), .MAX_II(MAX_II), .MEM_WORDS(MEM_WORDS)) dut (
        .clk(clk), .rst(rst), .run(run), .ii_m1(ii_m1),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .host_we(host_we), .host_addr(host_addr), .host_wdata(host_wdata),
        .host_rdata(host_rdata)
    );

    reg [31:0] meta [0:2];                   // II-1, サイクル数, 設定の組の数
    reg [31:0] cfg  [0:4095];                // 設定：番地, データ, 番地, データ, ...
    reg [31:0] mem0 [0:MEM_WORDS-1];         // メモリの初期値
    integer t, k, fd;

    initial begin
        $readmemh({CASE, ".meta"}, meta);
        $readmemh({CASE, ".cfg"},  cfg);
        $readmemh({CASE, ".mem"},  mem0);
        fd = $fopen({CASE, ".vlog"}, "w");

        @(negedge clk) rst = 1'b0;
        ii_m1 = meta[0][2:0];
        for (k = 0; k < meta[2]; k = k + 1) begin          // 設定を書き込む
            cfg_we = 1'b1; cfg_addr = cfg[2*k][11:0]; cfg_wdata = cfg[2*k+1];
            @(negedge clk);
        end
        cfg_we = 1'b0;
        for (k = 0; k < MEM_WORDS; k = k + 1) begin        // メモリを初期化する
            host_we = 1'b1; host_addr = k; host_wdata = mem0[k];
            @(negedge clk);
        end
        host_we = 1'b0;

        run = 1'b1;
        for (t = 0; t < meta[1]; t = t + 1) begin          // 実行する
            #1;
            for (k = 0; k < R; k = k + 1)
                if (dut.m_we[k])
                    $fdisplay(fd, "s %0d %0d 0 %08x %08x", t, k,
                              dut.m_addr[32*k +: 32], dut.m_wdata[32*k +: 32]);
            @(posedge clk) #1;
            $fwrite(fd, "o %0d", t);
            for (k = 0; k < R*C; k = k + 1) $fwrite(fd, " %08x", dut.outs[32*k +: 32]);
            $fwrite(fd, "\n");
            @(negedge clk);
        end
        run = 1'b0;

        for (k = 0; k < MEM_WORDS; k = k + 1) begin        // 実行後のメモリを読み出す
            host_addr = k; #1;
            $fdisplay(fd, "m %0d %08x", k, host_rdata);
        end
        $fclose(fd);
        $finish;
    end
endmodule

`default_nettype wire
