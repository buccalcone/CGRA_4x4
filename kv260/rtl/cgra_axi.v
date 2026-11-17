// =====================================================================
//  cgra_top を AXI4-Lite につなぐラッパ（ENUM Journal Vol.1 おまけ）
//  KV260 の PS からレジスタを読み書きして、テストベンチ（第 2 章の tb_cgra.v）と
//  同じ順番で CGRA を動かす：
//    RESET → II-1 → 設定 → メモリ初期化 → CYCLES → START → BUSY が 0 になるのを待つ → メモリ読み出し
//
//  番地（バイト番地、64 KiB）：
//    0x0000  CTRL    書き込み：bit0 = START、bit1 = RESET（どちらも 1 を書いたときだけ効く）
//                    読み出し：bit0 = BUSY（実行中）
//    0x0004  II_M1   II - 1（[2:0]）
//    0x0008  CYCLES  START で回すサイクル数
//    0x000C  ID      読み出すと 0x43475241（"CGRA"）
//    0x0010  CLKCNT  読み出しのみ。aclk で毎サイクル 1 増える（PS からクロックを実測する）
//    0x4000- CFG     書き込みのみ。cgra_top の cfg_addr = 番地[13:2]
//    0x8000- MEM     データメモリ。語番地 = 番地[2 +: AW]
//  実行中は II_M1・CYCLES・CFG・MEM への書き込みと START を無視する（RESET は効く）。
//  WSTRB は見ない（32 ビット単位で書く）。
// =====================================================================
`default_nettype none

module cgra_axi #(
    parameter R         = 4,
    parameter C         = 4,
    parameter MAX_II    = 8,
    parameter MEM_WORDS = 256
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire        aclk,
    input  wire        aresetn,

    input  wire [15:0] s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output wire [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,

    input  wire [15:0] s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready
);
    localparam AW = $clog2(MEM_WORDS);
    localparam [1:0] REG = 2'd0, CFG = 2'd1, MEM = 2'd2;

    // ---- AXI のハンドシェイク（書き込みを優先し、1 サイクルで受けて返す） ----
    wire wr = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    wire rd = s_axi_arvalid && !s_axi_rvalid && !wr;
    assign s_axi_awready = wr;
    assign s_axi_wready  = wr;
    assign s_axi_arready = rd;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;

    wire [1:0] wsel = s_axi_awaddr[15:14];
    wire [1:0] rsel = s_axi_araddr[15:14];
    wire [2:0] wreg = s_axi_awaddr[4:2];     // 制御レジスタの番号
    wire [2:0] rreg = s_axi_araddr[4:2];

    // ---- 制御レジスタ ------------------------------------------------------
    reg  [2:0]  ii_m1;
    reg  [31:0] cycles, remain, clkcnt;
    reg         busy, soft_rst;

    wire wr_reg = wr && wsel == REG;
    wire start  = wr_reg && wreg == 3'd0 && s_axi_wdata[0] && !busy;
    wire rst    = !aresetn || soft_rst;

    // RESET は書き込みの次のサイクルに 1 サイクルだけ効く（そのサイクルは bvalid が 1 なので
    // 次の書き込みとは重ならない）
    always @(posedge aclk) begin
        soft_rst <= aresetn && wr_reg && wreg == 3'd0 && s_axi_wdata[1];
        if (rst) begin
            busy   <= 1'b0;
            remain <= 32'd0;
        end else if (busy) begin             // CYCLES サイクルのあいだ 1
            remain <= remain - 32'd1;
            if (remain == 32'd1) busy <= 1'b0;
        end else if (start && cycles != 32'd0) begin
            busy   <= 1'b1;
            remain <= cycles;
        end
        if (!aresetn) begin
            ii_m1  <= 3'd0;
            cycles <= 32'd0;
        end else if (wr_reg && !busy) begin
            if (wreg == 3'd1) ii_m1  <= s_axi_wdata[2:0];
            if (wreg == 3'd2) cycles <= s_axi_wdata;
        end
        clkcnt <= aresetn ? clkcnt + 32'd1 : 32'd0;
    end

    // ---- CGRA 本体 ---------------------------------------------------------
    wire [AW-1:0] host_addr = wr ? s_axi_awaddr[2 +: AW] : s_axi_araddr[2 +: AW];
    wire [31:0]   host_rdata;

    cgra_top #(.R(R), .C(C), .MAX_II(MAX_II), .MEM_WORDS(MEM_WORDS)) cgra (
        .clk(aclk), .rst(rst), .run(busy), .ii_m1(ii_m1),
        .cfg_we(wr && wsel == CFG && !busy), .cfg_addr(s_axi_awaddr[13:2]),
        .cfg_wdata(s_axi_wdata),
        .host_we(wr && wsel == MEM && !busy), .host_addr(host_addr),
        .host_wdata(s_axi_wdata), .host_rdata(host_rdata)
    );

    // ---- 応答 ----------------------------------------------------------------
    always @(posedge aclk) begin
        if (!aresetn) begin
            s_axi_bvalid <= 1'b0;
            s_axi_rvalid <= 1'b0;
        end else begin
            if (wr)                                s_axi_bvalid <= 1'b1;
            else if (s_axi_bready)                 s_axi_bvalid <= 1'b0;
            if (rd)                                s_axi_rvalid <= 1'b1;
            else if (s_axi_rready)                 s_axi_rvalid <= 1'b0;
        end
        if (rd)
            case (rsel)
                REG:     case (rreg)
                             3'd0:    s_axi_rdata <= {31'd0, busy};
                             3'd1:    s_axi_rdata <= {29'd0, ii_m1};
                             3'd2:    s_axi_rdata <= cycles;
                             3'd3:    s_axi_rdata <= 32'h4347_5241;   // "CGRA"
                             3'd4:    s_axi_rdata <= clkcnt;
                             default: s_axi_rdata <= 32'd0;
                         endcase
                MEM:     s_axi_rdata <= host_rdata;
                default: s_axi_rdata <= 32'd0;
            endcase
    end
endmodule

`default_nettype wire
