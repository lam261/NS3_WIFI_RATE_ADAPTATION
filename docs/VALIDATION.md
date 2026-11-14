# Kiểm chứng và truy vết

## Phiên bản tạo số liệu

Người dùng đã build và chạy bộ mô phỏng bằng ns-3.45 trên Ubuntu/WSL, hoàn tất baseline 150 lần và bốn nhóm bổ sung 60/300/550/240 lần, cùng 6 smoke test. CSV và plan trong repo được lấy từ kết quả đã cung cấp, không dùng fixture kiểm thử làm dữ liệu nghiên cứu.

Ba nguồn mở rộng khớp SHA-256 trong tất cả plan của bộ kết quả. Mã baseline và script đi kèm được sao nguyên byte từ gói thực nghiệm lưu cùng dữ liệu. `SHA256SUMS.txt` ghi hash cho toàn bộ tệp công bố, trừ chính tệp hash.

Kiểm tra sau khi clone trên Linux:

```bash
sha256sum -c SHA256SUMS.txt
```

Các script kiểm thử chuyển trạng thái và điều phối dùng chuỗi xác định hoặc dữ liệu tổng hợp tạm thời. Chúng xác nhận logic script; build, smoke và chạy ns-3 xác nhận đường thực thi mô phỏng. Hai loại bằng chứng được phân biệt trong tài liệu này.

## Chạy kiểm tra

```bash
python extended/verify_package.py
python extended/install.py --ns3-root /duong/dan/ns-3.45
```

Lệnh đầu kiểm tra ma trận số run, tham số, công thức đo và PCAP parser. Lệnh thứ hai kiểm tra core C++ rồi build target thật trên checkout ns-3.45. Sau đó chạy smoke theo RUNNING.md.

Nguồn mở rộng không thay đổi tên hoặc ghi đè target baseline. Để tái tạo số liệu, dùng đúng phiên bản ns-3, tham số, seed/run và thời lượng trong plan. Thay code hoặc tập mode cần một thư mục output mới và ghi nhận như thí nghiệm mới.
