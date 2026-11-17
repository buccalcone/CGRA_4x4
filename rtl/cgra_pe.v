// =====================================================================
//  最小 CGRA の PE（ENUM Journal Vol.1 第 2 章）
//  参照モデル model/cgra_sim.py の step() を 1 PE ぶん RTL にしたもの。
//
//  命令は RV32I＋mul の 32 ビット語。レジスタ番号の意味だけ読み替える：
//    x0 = 0 / x1..x4 = 隣の N, E, S, W の出力 / x5 = self（自分の出力）/ x8..x11 = r0..r3
//  書き込み先 rd：x0 は何も書かない（nop は値を保持）、x5 は out、
//                 x8..x11 は r0..r3 と out の両方
// =====================================================================
`default_nettype none

module cgra_pe #(
    parameter MAX_II  = 8,                   // コンテキストの最大数（8 まで）
    parameter HAS_MEM = 0                    // 1 なら lw/sw を実行できる（列 0 の PE）
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        run,                  // 1 のサイクルだけ命令を実行する
    input  wire [2:0]  slot,                 // 今サイクルのコンテキスト番号（t mod II）

    input  wire [31:0] in_n, in_e, in_s, in_w,   // 隣の PE の出力（端では 0）
    output reg  [31:0] out,                  // 出力レジスタ（隣が次のサイクルに読む）

    // 設定の書き込み（run = 0 のときに使う）
    input  wire        cfg_we,
    input  wire [3:0]  cfg_sel,              // 0..7: コンテキスト、8: out、12..15: r0..r3
    input  wire [31:0] cfg_wdata,

    // データメモリ（HAS_MEM = 1 の PE だけが使う）
    output wire [31:0] mem_addr,             // バイト番地
    output wire        mem_we,
    output wire [31:0] mem_wdata,
    input  wire [31:0] mem_rdata
);
    localparam OP = 7'h33, OP_IMM = 7'h13, LOAD = 7'h03, STORE = 7'h23, LUI = 7'h37;

    reg [31:0] ctx  [0:MAX_II-1];            // コンテキストメモリ（命令語 × MAX_II）
    reg [31:0] regs [0:3];                   // r0..r3

    // ---- 命令の解読 -----------------------------------------------------
    wire [31:0] ins   = ctx[slot];
    wire [6:0]  opc   = ins[6:0];
    wire [4:0]  rd    = ins[11:7];
    wire [2:0]  f3    = ins[14:12];
    wire [4:0]  rs1   = ins[19:15];
    wire [4:0]  rs2   = ins[24:20];
    wire [6:0]  f7    = ins[31:25];
    wire [31:0] imm_i = {{20{ins[31]}}, ins[31:20]};
    wire [31:0] imm_s = {{20{ins[31]}}, ins[31:25], ins[11:7]};
    wire [31:0] imm_u = {ins[31:12], 12'b0};

    // ---- レジスタ番号の読み替え（x6, x7, x12 以降は 0 として読む） --------
    wire [31:0] xr [0:11];
    assign xr[0]  = 32'd0;
    assign xr[1]  = in_n;
    assign xr[2]  = in_e;
    assign xr[3]  = in_s;
    assign xr[4]  = in_w;
    assign xr[5]  = out;                     // self は「前のサイクルの自分の出力」
    assign xr[6]  = 32'd0;
    assign xr[7]  = 32'd0;
    assign xr[8]  = regs[0];
    assign xr[9]  = regs[1];
    assign xr[10] = regs[2];
    assign xr[11] = regs[3];

    wire [31:0] a = (rs1 < 5'd12) ? xr[rs1[3:0]] : 32'd0;   // 第 1 オペランド
    wire [31:0] c = (rs2 < 5'd12) ? xr[rs2[3:0]] : 32'd0;   // rs2 の値（R 形式、sw の書き込み値）
    wire [31:0] b = (opc == OP) ? c : imm_i;            // 第 2 オペランド

    // ---- ALU ------------------------------------------------------------
    // alt：R 形式なら funct7[5]（sub, sra）、I 形式なら srai のときだけ 1
    wire        alt = (opc == OP) ? f7[5] : (f3 == 3'b101 && ins[30]);
    wire [4:0]  sh  = b[4:0];
    wire [31:0] sra = $signed(a) >>> sh;     // 符号付きの式は単独で書く（混ぜると符号なしになる）
    reg  [31:0] alu;
    always @* begin
        case (f3)
            3'b000:  alu = alt ? a - b : a + b;
            3'b001:  alu = a << sh;
            3'b010:  alu = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            3'b011:  alu = (a < b) ? 32'd1 : 32'd0;
            3'b100:  alu = a ^ b;
            3'b101:  alu = alt ? sra : a >> sh;
            3'b110:  alu = a | b;
            default: alu = a & b;
        endcase
    end

    wire        is_mul = (opc == OP) && (f7 == 7'b0000001);   // M 拡張から借りた mul
    wire [31:0] result = (opc == LUI)  ? imm_u :
                         (opc == LOAD) ? mem_rdata :
                         is_mul        ? a * c :
                                         alu;

    // ---- メモリ（lw はサイクル開始時点の値を読み、sw はクロックで書く） ----
    assign mem_addr  = a + ((opc == STORE) ? imm_s : imm_i);
    assign mem_we    = (HAS_MEM != 0) && run && (opc == STORE);
    assign mem_wdata = c;

    // ---- 書き戻し ---------------------------------------------------------
    wire writes = (opc == OP) || (opc == OP_IMM) || (opc == LUI) ||
                  ((opc == LOAD) && (HAS_MEM != 0));
    wire to_reg = (rd[4:2] == 3'b010);       // x8..x11
    wire to_out = (rd == 5'd5) || to_reg;

    integer k;
    always @(posedge clk) begin
        if (rst) begin
            out <= 32'd0;
            for (k = 0; k < 4; k = k + 1)      regs[k] <= 32'd0;
            for (k = 0; k < MAX_II; k = k + 1) ctx[k]  <= 32'h0000_0013;   // nop
        end else if (cfg_we) begin
            if (cfg_sel < MAX_II)             ctx[cfg_sel[2:0]]  <= cfg_wdata;
            else if (cfg_sel == 4'd8)         out                <= cfg_wdata;
            else if (cfg_sel[3:2] == 2'b11)   regs[cfg_sel[1:0]] <= cfg_wdata;
        end else if (run && writes) begin
            if (to_out) out <= result;
            if (to_reg) regs[rd[1:0]] <= result;
        end
    end
endmodule

`default_nettype wire
