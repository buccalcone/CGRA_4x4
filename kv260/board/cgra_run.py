"""KV260 で CGRA を動かして答え合わせをする（ENUM Journal Vol.1 おまけ）

tb/run.py がシミュレーションで確かめて書き出したテストベクタ（build/cases.json）を読み、
PS から AXI4-Lite のレジスタを読み書きして、シミュレーションと同じ手順で CGRA を動かす。
実行後のメモリ 256 語と、読み出しで書かせた語（例 2 の内積）を期待値と比べる。
ここでは参照モデルも CGRA の中身も見ない。入力を入れて、出てきた値を比べるだけである。

使い方（KV260 の Ubuntu で。先に sudo xmutil loadapp cgra で回路を読み込んでおく）:
    sudo python3 cgra_run.py cases.json [回数]      （回数の既定は 2）
"""
import json, mmap, os, sys, time

BASE, SIZE = 0xA000_0000, 0x1_0000           # build.tcl で決めた cgra_axi の番地
CTRL, II_M1, CYCLES, ID, CLKCNT = 0x0000, 0x0004, 0x0008, 0x000C, 0x0010
CFG, MEM = 0x4000, 0x8000
CGRA_ID = 0x4347_5241                        # "CGRA"
PL0_HZ = 100_000_000                         # MMCM に入れる pl_clk0（build.tcl と cgra.dtsi）
CGRA_HZ = 80_000_000                         # MMCM が作る CGRA のクロック（build.tcl）

class CGRA:
    def __init__(self):
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                            offset=BASE)
        os.close(fd)
        self.w = memoryview(self.mm).cast("I")   # 32 ビット単位で読み書きする（WSTRB は見ないため）

    def rd(self, addr):
        return self.w[addr >> 2]

    def wr(self, addr, v):
        self.w[addr >> 2] = v & 0xFFFF_FFFF

    def run(self, n):
        """n サイクル回して、BUSY が 0 になるまで待つ"""
        self.wr(CYCLES, n)
        self.wr(CTRL, 1)                         # START
        t0 = time.monotonic()
        while self.rd(CTRL) & 1:
            if time.monotonic() - t0 > 1.0:
                raise RuntimeError("BUSY が 0 にならない")

def check(cg, case):
    cg.wr(CTRL, 2)                               # RESET
    cg.wr(II_M1, case["ii"] - 1)
    for a, v in case["cfg"]:                     # 設定
        cg.wr(CFG + 4 * a, v)
    for k, v in enumerate(case["mem0"]):         # メモリの初期値
        cg.wr(MEM + 4 * k, v)
    cg.run(case["cycles"])
    mem = [cg.rd(MEM + 4 * k) for k in range(len(case["mem"]))]
    bad = [k for k, (e, v) in enumerate(zip(case["mem"], mem)) if e != v]
    if bad:
        k = bad[0]
        return f"NG（メモリが {len(bad)} 語違う。最初は語 {k}：期待 {case['mem'][k]:08x}、実機 {mem[k]:08x}）"
    rd = case["readout"]
    if rd is None:
        return f"OK（{case['cycles']} サイクル、メモリ {len(mem)} 語一致）"
    for a, v in rd["cfg"]:                       # 読み出し（RESET はしない。答えが消える）
        cg.wr(CFG + 4 * a, v)
    cg.run(rd["cycles"])
    got = cg.rd(MEM + 4 * rd["word"])
    if got != rd["expect"]:
        return f"NG（読み出した答え：期待 {rd['expect']}、実機 {got}）"
    r, c, src = rd["pe"]
    return f"OK（{case['cycles']} サイクル、メモリ {len(mem)} 語一致、PE ({r},{c}) の {src} = {got}）"

def pl0_rate():
    """pl_clk0 の周波数（Linux が設定している値）。読めなければ None"""
    for path in ("/sys/bus/platform/devices/axi:clocking0/set_rate",
                 "/sys/kernel/debug/clk/pl0_ref/clk_rate"):
        try:
            return int(open(path).read())
        except (OSError, ValueError):
            pass
    return None

def measure_clock(cg, sec=0.5):
    """CLKCNT の増え方から、CGRA のクロックを実測する"""
    c0, t0 = cg.rd(CLKCNT), time.monotonic()
    time.sleep(sec)
    c1, t1 = cg.rd(CLKCNT), time.monotonic()
    return ((c1 - c0) & 0xFFFF_FFFF) / (t1 - t0)

if __name__ == "__main__":
    cases = json.load(open(sys.argv[1]))
    repeat = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    state = open("/sys/class/fpga_manager/fpga0/state").read().strip()
    if state != "operating":                     # 回路が無いまま PL の番地を読むと止まる
        sys.exit(f"FPGA が動いていない（state = {state}）。先に xmutil loadapp cgra を実行する")
    hz = pl0_rate()
    if hz is None:
        print("注意：pl_clk0 の周波数を読めなかった")
    elif abs(hz - PL0_HZ) > PL0_HZ // 100:     # MMCM の出力は入力に比例するので、入力がずれていたら止める
        sys.exit(f"pl_clk0 が {hz / 1e6:.2f} MHz。MMCM は {PL0_HZ / 1e6:.0f} MHz の入力を前提にしている")
    else:
        print(f"pl_clk0：{hz / 1e6:.2f} MHz")
    cg = CGRA()
    if cg.rd(ID) != CGRA_ID:
        sys.exit(f"ID が {cg.rd(ID):08x}。cgra のビットストリームが読み込まれていない")
    f = measure_clock(cg)
    print(f"CGRA のクロック（CLKCNT で実測）：{f / 1e6:.2f} MHz")
    if f > CGRA_HZ * 1.01:
        sys.exit(f"{CGRA_HZ / 1e6:.0f} MHz を超えている。タイミングが保証されない")
    ok = True
    for i in range(repeat):
        for case in cases:
            res = check(cg, case)
            ok = ok and res.startswith("OK")
            print(f"{i + 1} 回目 {case['name']:10s} {case['shape']} II={case['ii']}  {res}")
    sys.exit(0 if ok else 1)
