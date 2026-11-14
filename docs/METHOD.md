# Thiết kế thí nghiệm

## Mô hình và thông số

Hai node ad hoc 802.11a dùng UDP CBR một chiều. Kênh dùng LogDistancePropagationLossModel và NistErrorRateModel. Công suất phát 16 dBm, noise figure 7 dB, hệ số suy hao 3, reference loss 46,6777 dB tại 1 m. Chi tiết API và tham số có trong hai chương trình C++.

Tải phát là 22,68 Mb/s: 30.000 datagram, payload 2.268 byte, khoảng gửi 0,8 ms. UDP bắt đầu tại t=2 s; cửa sổ đo [2,26) s. Tập mode adaptive mặc định là 6/12/18/36/54 Mb/s. Fixed quét thêm 9/24/48 Mb/s để có đủ tám mode.

ARF/AARF/AMRR được cài trong RrWifiManager riêng. ARF và AARF dùng chung lõi chuyển trạng thái, khác cơ chế tăng ngưỡng. AMRR kết hợp retry theo gói với cập nhật rate cơ sở theo chu kỳ 1 s. Đây là cài đặt theo bài báo và mã giả RR-5208; so sánh với manager có sẵn của ns-3 cần được thực hiện như một thí nghiệm riêng.

## Các chỉ số

- Goodput = 8 × số byte UDP nhận trong cửa sổ / thời lượng / 10^6, đơn vị Mb/s.
- PDR = số datagram nhận / số datagram gửi ở ứng dụng.
- Delay = trung bình thời gian từ tạo datagram đến nhận, gồm chờ hàng đợi và truyền lại.
- CI 95% dùng phân phối Student-t; chênh lệch AARF–ARF được ghép theo seed/run trong cùng cấu hình.

Trong batch chính, goodput = 22,68 × PDR. PDR ở đây phản ánh lượng gói giao trong cửa sổ đo. Hàng đợi lớn và nguồn UDP không phản hồi tải khiến gói có thể còn chờ khi hết cửa sổ; không suy trực tiếp PDR này thành xác suất lỗi PHY.

Hệ thống có FqCoDel ở lớp traffic control và hàng đợi MAC. Độ trễ phụ thuộc tải và lịch sử backlog; cần đọc cùng goodput, thời gian chạy và cửa sổ đo. Khi kênh cải thiện, việc giải phóng backlog có thể làm goodput một bin cao hơn tải phát.

## Đối chứng và phạm vi

Baseline dùng nhãn run 1–10; bộ bổ sung dùng 11–20. Các suite bổ sung có một số cấu hình lặp: 150 adaptive RTS-tắt giữa fixed/rts và 20 baseline độ nhạy với đối chứng adaptive. Vì vậy 1.150 quan sát chính tương ứng 980 cấu hình–run phân biệt; không cộng các cấu hình lặp thành mẫu độc lập.

Đường fixed tốt nhất được chọn theo mean ở từng khoảng cách với cùng tải. Đây là mốc thực nghiệm cho tập mode đang xét. Những kết luận về AARF phải đi cùng tập mode, tải và cửa sổ đo.

Các thử nghiệm adaptive đủ tám mode, tải 0,46 ms, đối chiếu manager có sẵn và các mức Smax 10/60/90 chưa nằm trong bộ kết quả công bố. RBAR/MADWIFI/AR5212 được trình bày trong tài liệu gốc; repo triển khai ARF/AARF/AMRR và fixed.
