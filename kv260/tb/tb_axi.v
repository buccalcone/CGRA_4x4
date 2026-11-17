// =====================================================================
//  cgra_axi のテストベンチ（ENUM Journal Vol.1 おまけ）
//  PS のプログラムと同じ順番で AXI4-Lite の読み書きをして CGRA を動かし、
//  毎サイクルの出力レジスタと実行後のメモリを CASE.axi.vlog に書く。同じケースを 2 回続けて
//  回し、RESET で前の実行の状態（コンテキスト番号など）が消えることも確かめる。
//  CASE.rdmeta の設定の組の数が 0 でなければ、実行後にコンテキストを読み出し用に書き換えて
//  （RESET はしない）もう一度回し、答えを書かせた語を読む。
//    o <回> <サイクル> <PE0 の out> ...   … そのサイクル終了時の出力レジスタ（階層参照で見る）
//    n <回> <サイクル数>                  … run が 1 だったサイクル数
//    m <回> <語番地> <値>                 … 実行後のメモリ
//    r <回> <値>                          … 読み出しで書かせた語
// =====================================================================
`timescale 1ns/1ps
`default_nettype none

module tb;
    parameter R = 4, C = 4, MAX_II = 8, MEM_WORDS = 256;
    parameter CASE = "case";

    reg clk = 1'b0;
    always #5 clk = ~clk;

    reg         aresetn = 1'b0;
    reg  [15:0] awaddr = 0, araddr = 0;
    reg  [31:0] wdata = 0;
    reg         awvalid = 0, wvalid = 0, bready = 0, arvalid = 0, rready = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;

    cgra_axi #(.R(R), .C(C), .MAX_II(MAX_II), .MEM_WORDS(MEM_WORDS)) dut (
        .aclk(clk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hf), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready)
    );

    // AW と W は 1 回おきにずらして出す（相互接続を通るとそろって来るとは限らない）
    reg skew = 1'b0;
    task axi_write(input [15:0] a, input [31:0] d);
        begin
            @(negedge clk);
            awaddr = a; wdata = d; awvalid = 1'b1; wvalid = !skew;
            if (skew) begin @(negedge clk); wvalid = 1'b1; end
            skew = !skew;
            #1 while (!(awready && wready)) begin @(negedge clk); #1; end
            @(posedge clk) #1;
            awvalid = 1'b0; wvalid = 1'b0; bready = 1'b1;
            while (!bvalid) begin @(posedge clk) #1; end
            @(posedge clk) #1 bready = 1'b0;
        end
    endtask

    task axi_read(input [15:0] a, output [31:0] d);
        begin
            @(negedge clk);
            araddr = a; arvalid = 1'b1;
            #1 while (!arready) begin @(negedge clk); #1; end
            @(posedge clk) #1;
            arvalid = 1'b0; rready = 1'b1;
            while (!rvalid) begin @(posedge clk) #1; end
            d = rdata;
            @(posedge clk) #1 rready = 1'b0;
        end
    endtask

    reg [31:0] meta   [0:2];                 // II-1, サイクル数, 設定の組の数
    reg [31:0] cfg    [0:4095];              // 設定：番地, データ, 番地, データ, ...
    reg [31:0] mem0   [0:MEM_WORDS-1];
    reg [31:0] rdmeta [0:2];                 // 読み出し：設定の組の数, サイクル数, 語番地
    reg [31:0] rdcfg  [0:4095];
    reg [31:0] v, v0;
    reg        log_o = 1'b1;
    integer p, k, fd, j, nrun = 0;

    task run_cgra(input [31:0] n);           // n サイクル回して、BUSY が 0 になるまで待つ
        begin
            axi_write(16'h0008, n);                          // CYCLES
            axi_write(16'h0000, 32'd1);                      // START
            v = 1;
            while (v[0]) axi_read(16'h0000, v);
        end
    endtask

    always @(posedge clk)
        if (dut.busy && log_o) begin         // このクロックで 1 ステップ進んだ
            #1 $fwrite(fd, "o %0d %0d", p, nrun);
            for (j = 0; j < R*C; j = j + 1) $fwrite(fd, " %08x", dut.cgra.outs[32*j +: 32]);
            $fwrite(fd, "\n");
            nrun = nrun + 1;
        end

    initial begin
        $readmemh({CASE, ".meta"}, meta);
        $readmemh({CASE, ".cfg"},  cfg);
        $readmemh({CASE, ".mem"},  mem0);
        $readmemh({CASE, ".rdmeta"}, rdmeta);
        $readmemh({CASE, ".rdcfg"},  rdcfg);
        fd = $fopen({CASE, ".axi.vlog"}, "w");

        repeat (4) @(posedge clk);
        aresetn = 1'b1;
        axi_read(16'h000C, v);
        if (v !== 32'h4347_5241) $fdisplay(fd, "e ID が %08x", v);
        axi_read(16'h0010, v0);                              // CLKCNT は読むたびに増えている
        axi_read(16'h0010, v);
        if (v - v0 < 2 || v - v0 > 10) $fdisplay(fd, "e CLKCNT が %0d → %0d", v0, v);

        for (p = 0; p < 2; p = p + 1) begin
            axi_write(16'h0000, 32'd2);                      // RESET
            axi_write(16'h0004, meta[0]);                    // II - 1
            for (k = 0; k < meta[2]; k = k + 1)              // 設定
                axi_write(16'h4000 + 4 * cfg[2*k][11:0], cfg[2*k+1]);
            for (k = 0; k < MEM_WORDS; k = k + 1)            // メモリの初期値
                axi_write(16'h8000 + 4 * k, mem0[k]);
            nrun = 0;
            run_cgra(meta[1]);
            $fdisplay(fd, "n %0d %0d", p, nrun);
            for (k = 0; k < MEM_WORDS; k = k + 1) begin
                axi_read(16'h8000 + 4 * k, v);
                $fdisplay(fd, "m %0d %0d %08x", p, k, v);
            end
            if (rdmeta[0] != 0) begin                        // 読み出し（RESET はしない）
                for (k = 0; k < rdmeta[0]; k = k + 1)
                    axi_write(16'h4000 + 4 * rdcfg[2*k][11:0], rdcfg[2*k+1]);
                log_o = 1'b0;
                run_cgra(rdmeta[1]);
                log_o = 1'b1;
                axi_read(16'h8000 + 4 * rdmeta[2], v);
                $fdisplay(fd, "r %0d %08x", p, v);
            end
        end
        $fclose(fd);
        $finish;
    end
endmodule

`default_nettype wire
