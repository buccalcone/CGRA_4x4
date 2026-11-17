# =====================================================================
#  KV260 向けのビットストリームを作る（ENUM Journal Vol.1 おまけ）
#  PS（Zynq UltraScale+）の M_AXI_HPM0_FPD に cgra_axi をつなぐ。
#  cgra_axi は 0xA000_0000 から 64 KiB に置く。
#  KV260 の Linux からは pl_clk0 の周波数を変えられなかった（100 MHz のまま）ので、
#  pl_clk0 は 100 MHz のまま受け取り、Clocking Wizard（MMCM）で CGRA と AXI のクロックを作る。
#
#  使い方: vivado -mode batch -source build.tcl [-tclargs <CGRA のクロック MHz>]
#  出力は kv260/build/vivado/ に置く（cgra.bit, cgra.bit.bin, cgra.xsa, 報告）。
# =====================================================================
set here [file dirname [file normalize [info script]]]
set rtl  [file normalize $here/../rtl]
set cgra [file normalize $here/../../rtl]
set out  [file normalize $here/../build/vivado]
set clk_mhz [expr {[llength $argv] > 0 ? [lindex $argv 0] : 80}]

create_project -force cgra_kv260 $out/proj -part xck26-sfvc784-2LV-c
set_property board_part [lindex [lsort [get_board_parts xilinx.com:kv260_som:part0:*]] end] [current_project]
add_files -norecurse [list $rtl/cgra_axi.v $cgra/cgra_top.v $cgra/cgra_pe.v]
update_compile_order -fileset sources_1

# ---- ブロックデザイン ---------------------------------------------------
create_bd_design cgra
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e ps]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} $ps
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 1 \
    CONFIG.PSU__MAXIGP0__DATA_WIDTH 128 \
    CONFIG.PSU__USE__M_AXI_GP1 0 \
    CONFIG.PSU__USE__M_AXI_GP2 0 \
    CONFIG.PSU__FPGA_PL0_ENABLE 1 \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ 100 \
] $ps

# pl_clk0（100 MHz）から CGRA 用のクロックを作る
set clk [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk]
set_property -dict [list \
    CONFIG.PRIM_SOURCE Global_buffer \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $clk_mhz \
    CONFIG.USE_RESET true \
    CONFIG.RESET_TYPE ACTIVE_LOW \
    CONFIG.RESET_PORT resetn \
    CONFIG.USE_LOCKED true \
] $clk
connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins clk/clk_in1]
connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins clk/resetn]

set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst]
connect_bd_net [get_bd_pins clk/clk_out1] [get_bd_pins rst/slowest_sync_clk]
connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins rst/ext_reset_in]
connect_bd_net [get_bd_pins clk/locked] [get_bd_pins rst/dcm_locked]

# HPM0 → SmartConnect（128 ビット AXI4 → 32 ビット AXI4-Lite）→ cgra_axi。全部 clk_out1 で動かす
create_bd_cell -type module -reference cgra_axi cgra
set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect sc]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 1] $sc
connect_bd_intf_net [get_bd_intf_pins ps/M_AXI_HPM0_FPD] [get_bd_intf_pins sc/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins sc/M00_AXI] [get_bd_intf_pins cgra/s_axi]
connect_bd_net [get_bd_pins clk/clk_out1] \
    [get_bd_pins ps/maxihpm0_fpd_aclk] [get_bd_pins sc/aclk] [get_bd_pins cgra/aclk]
connect_bd_net [get_bd_pins rst/peripheral_aresetn] [get_bd_pins sc/aresetn] [get_bd_pins cgra/aresetn]

assign_bd_address
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps/Data] -filter {NAME =~ *cgra*}]
set_property offset 0xA0000000 $seg
set_property range 64K $seg

validate_bd_design
save_bd_design
puts "PL0: [get_property CONFIG.PSU__CRL_APB__PL0_REF_CTRL__ACT_FREQMHZ $ps] MHz"
puts "CGRA clock: requested $clk_mhz MHz, clk_out1 FREQ_HZ = [get_property CONFIG.FREQ_HZ [get_bd_pins clk/clk_out1]]"
puts "HPM0_FPD: [get_property CONFIG.PSU__MAXIGP0__DATA_WIDTH $ps] bit (kv260/cgra.dtsi の config-afi と合わせる)"

set bd [get_files cgra.bd]
make_wrapper -files $bd -top
add_files -norecurse [file normalize $out/proj/cgra_kv260.gen/sources_1/bd/cgra/hdl/cgra_wrapper.v]
set_property top cgra_wrapper [current_fileset]
update_compile_order -fileset sources_1

# ---- 合成・配置配線・ビットストリーム ------------------------------------
launch_runs synth_1 -jobs 8
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    puts "ERROR: impl_1 did not finish"
    exit 1
}

open_run impl_1
report_utilization -file $out/util.rpt
report_timing_summary -file $out/timing_summary.rpt
report_timing -max_paths 3 -nworst 1 -file $out/timing_paths.rpt
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "WNS = $wns ns ([expr {$wns >= 0 ? "TIMING MET" : "TIMING FAILED"}])"

set bit [glob $out/proj/cgra_kv260.runs/impl_1/*.bit]
file copy -force $bit $out/cgra.bit
# fpgautil / xmutil が読む形式（.bit.bin）
write_cfgmem -force -format bin -interface SMAPx32 -disablebitswap \
    -loadbit "up 0x0 $out/cgra.bit" $out/cgra.bit.bin
write_hw_platform -fixed -include_bit -force $out/cgra.xsa
puts "DONE"
