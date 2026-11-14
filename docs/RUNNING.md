# Chạy lại thí nghiệm trên ns-3.45

Thực hiện trong Ubuntu hoặc WSL Ubuntu. Đặt repo và ns-3 trong filesystem Linux để giảm thời gian I/O.

## 1. Chuẩn bị

```bash
sudo apt update
sudo apt install build-essential cmake ninja-build git python3 python3-venv
python3 -m venv "$HOME/rr-venv"
source "$HOME/rr-venv/bin/activate"
git clone https://github.com/lam261/NS3_WIFI_RATE_ADAPTATION.git "$HOME/NS3_WIFI_RATE_ADAPTATION"
cd "$HOME/NS3_WIFI_RATE_ADAPTATION"
pkg="$PWD"
python -m pip install -r requirements.txt
```

Nếu đã có venv và repo, chỉ kích hoạt venv rồi đặt lại `pkg`. Nếu `ensurepip` thiếu, cài gói venv đúng phiên bản Python của Ubuntu, ví dụ `python3.12-venv`.

Sử dụng checkout ns-3.45 hiện có:

```bash
nsroot="$HOME/workspace/ns-allinone-3.45/ns-3.45"
cat "$nsroot/VERSION"
```

Nếu chưa có ns-3.45, tạo checkout riêng:

```bash
git clone --branch ns-3.45 --depth 1 https://gitlab.com/nsnam/ns-3-dev.git "$HOME/ns-3.45"
nsroot="$HOME/ns-3.45"
cd "$nsroot"
./ns3 configure --enable-asserts --enable-logs
cd "$pkg"
```

## 2. Kiểm tra và build

```bash
python "$pkg/extended/verify_package.py"
python "$pkg/extended/install.py" --ns3-root "$nsroot"
```

Installer kiểm tra VERSION, chạy core tests, chép ba nguồn mở rộng vào scratch và build `rr-extended`. Nếu nguồn cùng tên đã tồn tại nhưng khác nội dung, script dừng để bạn đối chiếu phiên bản.

## 3. Smoke trước batch chính

```bash
result="$HOME/rr-reproduce-345"
python "$pkg/extended/run_suite.py" --ns3-root "$nsroot" --suite smoke   --first-run 11 --out "$result/00-smoke" --resume
python "$pkg/extended/check_smoke.py" "$result/00-smoke"
```

Kỳ vọng: 6 verified simulations và PASS cho smoke/PCAP RTS. Nếu lỗi, đọc console log của run trước khi tiếp tục.

## 4. Chạy bốn nhóm theo thứ tự

```bash
for suite in step rts fixed sensitivity; do
  python "$pkg/extended/run_suite.py" --ns3-root "$nsroot"     --suite "$suite" --runs 10 --first-run 11     --out "$result/$suite" --resume || break
  python "$pkg/extended/analyze_suite.py" "$result/$suite"     --out "$result/$suite-analysis" || break
done
```

Số lượng lần lượt là **60 → 300 → 550 → 240**. Seed mặc định bằng 1; nhãn run là 11–20. `--resume` kiểm tra lại dữ liệu hoàn tất rồi tiếp tục phần thiếu. Giữ nguyên nguồn, tham số và thư mục đầu ra khi tiếp tục một plan.

Có thể dùng script gốc để tự động toàn bộ bước kiểm tra, build, smoke và bốn nhóm; script dừng ngay khi có lỗi:

```bash
bash "$pkg/extended/run_in_order.sh" "$nsroot" "$result" 10 11
```

Muốn chạy thử 3 run, dùng thư mục khác và thay `10` bằng `3`. Không đổi số run trong thư mục đã có plan. Máy sleep làm tiến trình tạm ngừng; sau khi thức dậy thời gian thực còn lại vẫn cần được thực hiện.

## 5. Batch baseline và trace 40 m

Batch ban đầu dùng target riêng. Chạy installer khi ba nguồn baseline chưa tồn tại trong scratch:

```bash
bash "$pkg/baseline/install.sh" "$nsroot"
python "$pkg/baseline/run_experiments.py" --ns3-root "$nsroot"   --runs 10 --distances 20,35,40,45,50 --rts 0   --out "$HOME/rr-baseline-reproduce-345"
python "$pkg/baseline/analyze.py" "$HOME/rr-baseline-reproduce-345/all-runs.csv"   --out "$HOME/rr-baseline-analysis-345"
```

Chữ `3.44` còn trong thông báo usage của installer gốc; thí nghiệm kèm repo đã chạy bằng ns-3.45. Giữ nguyên script để đối chiếu phiên bản.

```bash
cd "$nsroot"
mkdir -p results-trace40
for alg in ARF AARF AMRR; do
  ./ns3 run "scratch/rr-rate-adaptation --algorithm=$alg --distance=40 --seed=1 --run=1 --traceState=1 --prefix=results-trace40/$alg"
done
python "$pkg/baseline/plot_trace.py" results-trace40/ARF results-trace40/AARF   results-trace40/AMRR --out "$HOME/trace-40m-reproduce.png"
```

## 6. Đầu ra cần giữ

Mỗi run tạo summary, timeseries, rates, state và FlowMonitor; bộ mở rộng còn lưu lệnh, log và marker hoàn tất. Giữ toàn bộ thư mục `result` nếu cần kiểm chứng lại từng lần chạy. CSV công bố trong repo cho phép xem số liệu ngay; chạy lại bộ phân tích mở rộng cần thư mục output đầy đủ vừa tạo, không chỉ CSV tổng hợp trong `results/`.
