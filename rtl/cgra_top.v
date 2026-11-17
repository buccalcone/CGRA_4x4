// =====================================================================
//  最小 CGRA のアレイ（ENUM Journal Vol.1 第 2 章）
//  R x C の PE をメッシュにつなぎ、列 0 の PE にデータメモリを持たせる。
//
//  設定：cfg_addr = {PE 番号 (r*C + c), sel[3:0]}
//        sel 0..7 がコンテキスト、8 が out の初期値、12..15 が r0..r3 の初期値
//  データメモリ：PE からはバイト番地、ホストからは語番地でアクセスする
// =====================================================================
`default_nettype none

module cgra_top #(
    parameter R         = 4,
    parameter C         = 4,
    parameter MAX_II    = 8,
    parameter MEM_WORDS = 256                // 2 のべき乗（番地の上位ビットは無視する）
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        run,                  // 1 のあいだ毎サイクル 1 ステップ進む
    input  wire [2:0]  ii_m1,                // II - 1

    input  wire        cfg_we,
    input  wire [11:0] cfg_addr,
    input  wire [31:0] cfg_wdata,

    input  wire        host_we,              // ホストからのメモリアクセス（run = 0 のとき）
    input  wire [$clog2(MEM_WORDS)-1:0] host_addr,
    input  wire [31:0] host_wdata,
    output wire [31:0] host_rdata
);
    localparam AW = $clog2(MEM_WORDS);

    // ---- コンテキスト番号（t mod II） -------------------------------------
    reg [2:0] slot;
    always @(posedge clk)
        if (rst)      slot <= 3'd0;
        else if (run) slot <= (slot == ii_m1) ? 3'd0 : slot + 3'd1;

    // ---- PE アレイ --------------------------------------------------------
    wire [32*R*C-1:0] outs;                  // PE k = r*C + c の出力は outs[32*k +: 32]
    wire [32*R-1:0]   m_addr, m_wdata, m_rdata;   // 列 0 の PE（行 r）のメモリポート
    wire [R-1:0]      m_we;

    genvar r, c;
    generate
        for (r = 0; r < R; r = r + 1) begin : row
            for (c = 0; c < C; c = c + 1) begin : col
                localparam K = r * C + c;
                wire [31:0] n, e, s, w;
                /* verilator lint_off UNUSEDSIGNAL */  // 列 0 以外ではメモリポートを使わない
                wire [31:0] maddr, mwdata;
                wire        mwe;
                /* verilator lint_on UNUSEDSIGNAL */
                // 隣の出力（アレイの端では 0）
                if (r > 0)     begin : g_n assign n = outs[32*(K-C) +: 32]; end
                else           begin : g_n0 assign n = 32'd0; end
                if (c < C - 1) begin : g_e assign e = outs[32*(K+1) +: 32]; end
                else           begin : g_e0 assign e = 32'd0; end
                if (r < R - 1) begin : g_s assign s = outs[32*(K+C) +: 32]; end
                else           begin : g_s0 assign s = 32'd0; end
                if (c > 0)     begin : g_w assign w = outs[32*(K-1) +: 32]; end
                else           begin : g_w0 assign w = 32'd0; end

                cgra_pe #(.MAX_II(MAX_II), .HAS_MEM(c == 0)) pe (
                    .clk(clk), .rst(rst), .run(run), .slot(slot),
                    .in_n(n), .in_e(e), .in_s(s), .in_w(w), .out(outs[32*K +: 32]),
                    .cfg_we(cfg_we && cfg_addr[11:4] == K), .cfg_sel(cfg_addr[3:0]),
                    .cfg_wdata(cfg_wdata),
                    .mem_addr(maddr), .mem_we(mwe), .mem_wdata(mwdata),
                    .mem_rdata(c == 0 ? m_rdata[32*r +: 32] : 32'd0)
                );

                if (c == 0) begin : memport
                    assign m_addr[32*r +: 32]  = maddr;
                    assign m_wdata[32*r +: 32] = mwdata;
                    assign m_we[r]             = mwe;
                end
            end
        end
    endgenerate

    // ---- データメモリ（読み出しは組合せ、書き込みはクロックの立ち上がり） ----
    reg [31:0] mem [0:MEM_WORDS-1];
    generate
        for (r = 0; r < R; r = r + 1) begin : rport
            assign m_rdata[32*r +: 32] = mem[m_addr[32*r+2 +: AW]];
        end
    endgenerate
    assign host_rdata = mem[host_addr];

    integer i;
    always @(posedge clk) begin
        if (host_we) mem[host_addr] <= host_wdata;
        for (i = 0; i < R; i = i + 1)        // 同じ番地への同時書き込みは行番号の大きい方が勝つ
            if (m_we[i]) mem[m_addr[32*i+2 +: AW]] <= m_wdata[32*i +: 32];
    end
endmodule

`default_nettype wire
