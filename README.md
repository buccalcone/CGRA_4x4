# CGRA_4x4

4×4 の小さな CGRA（Coarse-Grained Reconfigurable Array：粗粒度再構成可能アレイ）の実装です。
Python のシミュレータと Verilog の RTL があり、両者が 1 サイクルずつ同じ動きをすることを確かめられます。

技術同人誌『ENUM Journal』Vol.1（特集：CGRA）のコードを、本とは別にまとめたものです。
コードのコメントにある「第 2 章」「第 3 章」「おまけ」は、この本の章を指します。

## 構成

| ディレクトリ | 中身 | 本の章 |
|---|---|---|
| `model/` | Python のシミュレータ `cgra_sim.py` と、ループを載せる例 3 本 | 第 2 章、第 3 章 |
| `rtl/` | CGRA の Verilog。`cgra_pe.v` が PE 1 個、`cgra_top.v` がメッシュとデータメモリ | 第 2 章 |
| `tb/` | シミュレータと Verilog の答え合わせ | 第 2 章 |
| `cpu/` | 比較用の RV32I（＋mul）シングルサイクル CPU と、サイクル数の比較 | 第 3 章 |
| `kv260/` | KV260 で動かすための AXI ラッパ、答え合わせ、Vivado のスクリプト、実機に置くファイル | おまけ |

## CGRA の仕様

- R×C の 2 次元メッシュで、既定は 4×4。PE の隣は上下左右の 4 つ。
- PE は ALU 1 個、出力レジスタ 1 個、汎用レジスタ 4 個（r0〜r3）を持つ。
- PE の命令は RV32I（＋mul）の 32 ビット語。プログラムカウンタは無く、レジスタ番号の意味だけ読み替える。
- メモリ命令（`lw`、`sw`）を実行できるのは列 0 の PE だけ。
- 各 PE は開始間隔（II）と同じ数の命令を持ち、サイクルごとに切り替える。

レジスタ番号の読み替えは次のとおりです。

| 番号 | 読むと | 書き込み先にすると |
|---|---|---|
| x0 | 0 | 何も書かない |
| x1〜x4 | 北・東・南・西の隣の、前サイクルの出力 | （読み出し専用） |
| x5 | 自分の前サイクルの出力 | 出力レジスタ |
| x8〜x11 | r0〜r3 | r0〜r3 と出力レジスタの両方 |

## 動かし方

シミュレータは Python 3 だけで動きます。答え合わせ（`tb/`、`cpu/`、`kv260/tb/`）には Icarus Verilog が要ります。

```sh
python3 model/ex1_axpb.py   # y[i] = a*x[i] + b を 4x4、開始間隔 1 で
python3 model/ex2_dot.py    # 内積を 4x4（開始間隔 1）と 2x2（開始間隔 2）で
python3 model/ex3_acc.py    # 累算つきループを 4x4、開始間隔 1 で

python3 tb/run.py           # シミュレータと Verilog の答え合わせ
python3 cpu/run.py          # 比較用 CPU の答え合わせと、サイクル数の比較
python3 kv260/tb/run.py     # AXI ラッパの答え合わせ
```

`tb/run.py` は、毎サイクルの全 PE の出力とストアを、シミュレータと Verilog で 1 行ずつ比べます。

```
ex1_axpb   OK（4x4, II=1, 20 サイクルで完了, 296 行一致）
ex2_dot_0  OK（4x4, II=1, 20 サイクルで完了, 276 行一致）
ex2_dot_1  OK（2x2, II=2, 35 サイクルで完了, 291 行一致）
ex3_acc    OK（4x4, II=1, 22 サイクルで完了, 300 行一致）
```

`cpu/run.py` は、同じ 3 つのループを CPU でも動かして、サイクル数を並べます（反復数は 16）。

```
例            CPU 1 反復   CPU 合計   CGRA            合計   使った PE
ex1_axpb         6 命令    100   4x4 II=1        20      6
ex2_dot_0        6 命令    100   4x4 II=1        20      7
ex2_dot_1        6 命令    100   2x2 II=2        35      4
ex3_acc          7 命令    117   4x4 II=1        22      8
```

比べているのはサイクル数だけです。CGRA は演算器を何個も並べていて、クロック周波数や消費電力は比べていません。

`rtl/` の 2 ファイルは、`verilator --lint-only -Wall rtl/cgra_top.v rtl/cgra_pe.v` で警告が出ません。

## KV260 で動かす

AMD Kria KV260 の PL に CGRA を置き、PS の Linux（Ubuntu）から AXI4-Lite で設定と入力を書き込みます。

1. `python3 kv260/tb/run.py` で、テストベクタ `kv260/build/cases.json` を作る。
2. `vivado -mode batch -source kv260/vivado/build.tcl` で、`kv260/build/vivado/cgra.bit.bin` を作る。CGRA のクロックは既定で 80 MHz。
3. `kv260/board/` のファイルと `cgra.bit.bin`、`cases.json` を KV260 の同じディレクトリに置く。
4. KV260 で `sh install.sh` を実行して回路を読み込み、`sudo python3 cgra_run.py cases.json` で答え合わせをする。

## ライセンス

MIT ライセンスです。[LICENSE](LICENSE) を見てください。

## 連絡先

著者は中腸腺です。

- GitHub：[buccalcone](https://github.com/buccalcone)
- X：[@bukkalcone](https://x.com/bukkalcone)
