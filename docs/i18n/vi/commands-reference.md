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

## Định tuyến quyết định có giới hạn (tùy chọn)

`python rain_lab.py decide --request examples/bounded-decision.json` chỉ tạo
đề xuất, không thực thi hành động. `decide --replay ARTIFACT` đọc lại ngoại tuyến.
`RAIN_DECISION_MODE=off|laya|jev|cascade` mặc định là `off`.
`RAIN_METACOGNITIVE_CONTROL=false` giữ nguyên vòng hội thoại hiện tại.
Laya cần `RAIN_LAYA_CHECKPOINT`; đề xuất đã hiệu chuẩn cần
`RAIN_DECISION_CALIBRATION`. Nếu thiếu mô hình hoặc hiệu chuẩn, quyết định được
chuyển về R.A.I.N. Đánh giá từ xa cần sự cho phép rõ ràng; hội thoại còn cần
`RAIN_DECISION_REMOTE_ALLOWED=true`. Lỗi cấu hình được thông báo.
Xem [quyết định có giới hạn](../../bounded-decisions.md) để biết cấu hình, chẩn đoán và cách hoàn tác.
Chính sách chấp thuận của lệnh `judge` không thay đổi.

## R.A.I.N. Rig (tùy chọn)

Rig là lớp nút tùy chọn trong runtime Rust; `python rain_lab.py` không phụ
thuộc vào nó. Xem [`rig/README.md`](../../rig/README.md) (tiếng Anh).

```bash
rain rig status [--json]          # trạng thái nút (READY/DEGRADED/BLOCKED)
rain rig doctor [--json]          # PASS/WARN/FAIL/SKIP; mã thoát khác 0 khi có FAIL
rain rig models [--json]          # mô hình trên llama.cpp / Ollama / LM Studio / cuộc họp
rain rig capabilities [--json]    # danh sách khả năng và trạng thái hiện tại
rain rig peers [--json]           # danh tính có thể chia sẻ và các transport
rain rig setup [--profile local|node|field] [--node-name TEN] [--privacy local|hybrid|hosted] [--yes] [--dry-run]
rain rig up [--dry-run]           # khởi động daemon R.A.I.N. trên địa chỉ đã cấu hình
rain rig radio status|encode|decode   # modem phần mềm Skybridge (thử nghiệm, không phát RF)
```

- Việc dò tìm chỉ kiểm tra địa chỉ cục bộ (loopback hoặc mạng riêng) và không
  bao giờ liên hệ dịch vụ lưu trữ bên ngoài.
- `setup` hỏi xác nhận trước khi ghi `config.toml` (cần `--yes` khi không
  tương tác) và không cài đặt hay tải xuống gì.
- `up` chỉ khởi động daemon R.A.I.N.; nút ở trạng thái BLOCKED không khởi động gì.
