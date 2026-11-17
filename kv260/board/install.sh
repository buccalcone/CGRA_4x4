#!/bin/sh
# =====================================================================
#  KV260 の Ubuntu で CGRA の回路を読み込む（ENUM Journal Vol.1 おまけ）
#  このディレクトリに cgra.bit.bin（vivado/build.tcl の出力）を置いてから実行する:
#      sh install.sh
#  そのあと: sudo python3 cgra_run.py cases.json
# =====================================================================
set -e
cd "$(dirname "$0")"
dtc -@ -I dts -O dtb -o cgra.dtbo cgra.dtsi        # 無ければ sudo apt install device-tree-compiler
sudo mkdir -p /lib/firmware/xilinx/cgra
sudo cp cgra.bit.bin cgra.dtbo shell.json /lib/firmware/xilinx/cgra/
sudo xmutil unloadapp || true                       # 起動時に読み込まれているアプリを外す
sudo xmutil loadapp cgra
