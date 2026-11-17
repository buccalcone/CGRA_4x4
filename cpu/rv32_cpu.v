// =====================================================================
//  比較用の RV32I（＋mul）シングルサイクル CPU（ENUM Journal Vol.1 第 3 章の比較用）
//  本筋ではないのでリポジトリにだけ置く。rv32.py の CPU.step() と同じ動きをする。
//
//  - 1 命令を 1 サイクルで実行する（パイプラインが無いのでハザードも無い）
//  - 命令メモリとデータメモリは別。どちらも読み出しは組合せ、書き込みはクロック
//  - ecall / ebreak で停止する（halted = 1）。fence と未定義の命令は何もしない
// =====================================================================
`default_nettype none

module rv32_cpu #(
    parameter IMEM_WORDS = 256,
    parameter DMEM_WORDS = 256
) (
    input  wire clk,
    input  wire rst,
    output reg  halted
);
    localparam IAW = $clog2(IMEM_WORDS), DAW = $clog2(DMEM_WORDS);
    localparam OP = 7'h33, OP_IMM = 7'h13, LOAD = 7'h03, STORE = 7'h23, BRANCH = 7'h63,
               JAL = 7'h6f, JALR = 7'h67, LUI = 7'h37, AUIPC = 7'h17, SYSTEM = 7'h73;

    /* verilator lint_off UNDRIVEN */
    reg [31:0] imem [0:IMEM_WORDS-1];        // テストベンチが $readmemh で読み込む
    /* verilator lint_on UNDRIVEN */
    reg [31:0] dmem [0:DMEM_WORDS-1];
    reg [31:0] xreg [0:31];
    reg [31:0] pc;

    // ---- 命令の解読 -----------------------------------------------------
    wire [31:0] ins   = imem[pc[IAW+1:2]];
    wire [6:0]  opc   = ins[6:0];
    wire [4:0]  rd    = ins[11:7];
    wire [2:0]  f3    = ins[14:12];
    wire [4:0]  rs1   = ins[19:15];
    wire [4:0]  rs2   = ins[24:20];
    wire [6:0]  f7    = ins[31:25];
    wire [31:0] imm_i = {{20{ins[31]}}, ins[31:20]};
    wire [31:0] imm_s = {{20{ins[31]}}, ins[31:25], ins[11:7]};
    wire [31:0] imm_b = {{19{ins[31]}}, ins[31], ins[7], ins[30:25], ins[11:8], 1'b0};
    wire [31:0] imm_u = {ins[31:12], 12'b0};
    wire [31:0] imm_j = {{11{ins[31]}}, ins[31], ins[19:12], ins[20], ins[30:21], 1'b0};

    wire [31:0] r1 = (rs1 == 5'd0) ? 32'd0 : xreg[rs1];
    wire [31:0] r2 = (rs2 == 5'd0) ? 32'd0 : xreg[rs2];

    // ---- ALU（CGRA の PE と同じ） ----------------------------------------
    wire [31:0] b   = (opc == OP) ? r2 : imm_i;
    wire        alt = (opc == OP) ? f7[5] : (f3 == 3'b101 && ins[30]);
    wire [4:0]  sh  = b[4:0];
    wire [31:0] sra = $signed(r1) >>> sh;
    reg  [31:0] alu;
    always @* begin
        case (f3)
            3'b000:  alu = alt ? r1 - b : r1 + b;
            3'b001:  alu = r1 << sh;
            3'b010:  alu = ($signed(r1) < $signed(b)) ? 32'd1 : 32'd0;
            3'b011:  alu = (r1 < b) ? 32'd1 : 32'd0;
            3'b100:  alu = r1 ^ b;
            3'b101:  alu = alt ? sra : r1 >> sh;
            3'b110:  alu = r1 | b;
            default: alu = r1 & b;
        endcase
    end
    wire        is_mul  = (opc == OP) && (f7 == 7'b0000001);
    wire [31:0] alu_out = is_mul ? r1 * r2 : alu;

    // ---- 分岐 -----------------------------------------------------------
    reg take;
    always @* begin
        case (f3)
            3'b000:  take = (r1 == r2);
            3'b001:  take = (r1 != r2);
            3'b100:  take = ($signed(r1) <  $signed(r2));
            3'b101:  take = ($signed(r1) >= $signed(r2));
            3'b110:  take = (r1 <  r2);
            3'b111:  take = (r1 >= r2);
            default: take = 1'b0;
        endcase
    end

    // ---- データメモリ（バイト・ハーフワードは語の中から切り出す） --------
    /* verilator lint_off UNUSEDSIGNAL */    // 番地の上位ビットと、切り出した残りは使わない
    wire [31:0] addr = r1 + ((opc == STORE) ? imm_s : imm_i);
    wire [31:0] wb_  = dmem[addr[DAW+1:2]] >> {addr[1:0], 3'b000};
    wire [31:0] wh_  = dmem[addr[DAW+1:2]] >> {addr[1], 4'b0000};
    /* verilator lint_on UNUSEDSIGNAL */
    wire [31:0] word = dmem[addr[DAW+1:2]];
    reg  [31:0] ld, st;
    always @* begin
        case (f3)
            3'b000:  ld = {{24{wb_[7]}}, wb_[7:0]};      // lb
            3'b001:  ld = {{16{wh_[15]}}, wh_[15:0]};    // lh
            3'b100:  ld = {24'd0, wb_[7:0]};             // lbu
            3'b101:  ld = {16'd0, wh_[15:0]};            // lhu
            default: ld = word;                          // lw
        endcase
        case (f3)
            3'b000:  st = (word & ~(32'h0000_00ff << {addr[1:0], 3'b000})) |
                          ({24'd0, r2[7:0]}  << {addr[1:0], 3'b000});     // sb
            3'b001:  st = (word & ~(32'h0000_ffff << {addr[1], 4'b0000})) |
                          ({16'd0, r2[15:0]} << {addr[1], 4'b0000});      // sh
            default: st = r2;                                             // sw
        endcase
    end

    // ---- 書き戻しと次の PC ------------------------------------------------
    reg [31:0] wdata;
    reg        we;
    always @* begin
        we = 1'b1;
        case (opc)
            OP, OP_IMM: wdata = alu_out;
            LOAD:       wdata = ld;
            LUI:        wdata = imm_u;
            AUIPC:      wdata = pc + imm_u;
            JAL, JALR:  wdata = pc + 32'd4;
            default:    begin wdata = 32'd0; we = 1'b0; end
        endcase
    end
    wire        is_store = (opc == STORE);
    wire [31:0] npc = (opc == JAL)            ? pc + imm_j :
                      (opc == JALR)           ? ((r1 + imm_i) & ~32'd1) :
                      (opc == BRANCH && take) ? pc + imm_b :
                                                pc + 32'd4;

    integer k;
    always @(posedge clk) begin
        if (rst) begin
            pc     <= 32'd0;
            halted <= 1'b0;
            for (k = 0; k < 32; k = k + 1) xreg[k] <= 32'd0;
        end else if (!halted) begin
            if (we && rd != 5'd0) xreg[rd] <= wdata;
            if (is_store)         dmem[addr[DAW+1:2]] <= st;
            if (opc == SYSTEM)    halted <= 1'b1;
            else                  pc <= npc;
        end
    end
endmodule

`default_nettype wire
