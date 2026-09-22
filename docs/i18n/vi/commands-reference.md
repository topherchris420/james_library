# Tài liệu lệnh (VI)

Lệnh chính:

```bash
python rain_lab.py
```

Chế độ thường dùng:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode chat --topic "..." --temp 0.85 --max-tokens 320` để tạo đầu ra thử nghiệm giàu khám phá hơn
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

Trong cuộc họp ở chế độ chat, sự lặp lại kéo dài sẽ lần lượt dẫn đến yêu cầu
bằng chứng, một giả thuyết thay thế có thể kiểm chứng để bác bỏ, rồi chuyển sang
tổng kết sớm nếu cần. Mỗi lần can thiệp dành một vòng đầy đủ cho các tác nhân;
phần tổng kết không khởi động lại tranh luận hoặc vượt quá giới hạn lượt.
Các hành động được lưu trong tệp phiên. Xem
[cơ chế phục hồi cuộc họp](../../meeting-recovery.md) (tiếng Anh).

## Lệnh cầu nối runtime R.A.I.N.

Điểm vào cho runtime Rust:

```bash
R.A.I.N. gateway
R.A.I.N. daemon
```

Ghi chú:

- `R.A.I.N. gateway` và `R.A.I.N. daemon` dùng `gateway.port` từ config khi không truyền `--port`.
- Nếu muốn mặc định cầu nối Body-daemon, đặt `gateway.port = 4200` trong config hoặc `R.A.I.N._GATEWAY_PORT=4200` trong môi trường.
- Khởi động sẽ bị chặn nếu dừng khẩn cấp đang bật ở mức `kill-all` hoặc `network-kill`.

## Phán đoán có kiểu

```bash
python rain_lab.py judge --evidence cycle.json
python rain_lab.py judge --replay meeting_archives/session_artifacts/session_<id>.json
```

Lệnh này áp dụng ranh giới thăng cấp năm giai đoạn cho gói bằng chứng đã được
chọn lọc. Truy cập từ xa mặc định tắt; phát lại bản ghi không gọi nhà cung cấp.
Xem [`typed-judgment.md`](../../typed-judgment.md).
