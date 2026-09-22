# Tài liệu cấu hình (VI)

Schema cấu hình chuẩn:

- [`../../../src/config/schema.rs`](../../../src/config/schema.rs)

Mã tải/gộp cấu hình:

- [`../../../src/config/mod.rs`](../../../src/config/mod.rs)

Các khóa plugin mới:

- `[plugins].marketplace_enabled` (mặc định `false`, bắt buộc để cài từ HTTP(S))
- `[plugins].allowed_permissions` (allowlist quyền được chấp nhận khi cài plugin)

## Các mục runtime tự trị (thêm 2026-06)

Tất cả mặc định tắt; bỏ qua chúng sẽ giữ nguyên hành vi trước đây.

- `[autonomous_runtime]` — chạy tác vụ nền (bắt đầu với heartbeat) qua
  pulse driver trong `src/autonomy/`; bao gồm
  `[autonomous_runtime.vitals]` (ngưỡng phát hiện trì trệ/bế tắc của bộ
  giám sát vitals). Đặt tên như vậy để tránh trùng với mục bảo mật
  `[autonomy]`.
- `[senses]` — bus cảm biến có ưu tiên cho luồng tin nhắn kênh (dung lượng
  hàng đợi, tín dụng chống bỏ đói, bộ đệm ambient, cửa sổ gộp sự kiện).
- `[hooks.builtin].episodic_events` — ghi một dòng JSONL cho mỗi lần gọi
  công cụ vào `episodic_memory/episodic_events.jsonl` (chỉ tên công cụ,
  kết quả, thời lượng; không bao giờ ghi đối số hay đầu ra).

Thiết kế: [`autonomous-runtime-design.md`](../../autonomous-runtime-design.md).

## Môi trường phán đoán có kiểu

- `RAIN_JUDGMENT_PROVIDER=off|typesafe` (mặc định: `off`)
- `TYPESAFE_API_KEY` (chỉ bắt buộc khi bật TypeSafe)
- `TYPESAFE_MODEL` (mặc định: `jev-latest`)

Lỗi nhà cung cấp tạo `UNAVAILABLE`, không tự động thử lại hoặc chuyển sang mô
hình khác. Xem [`typed-judgment.md`](../../typed-judgment.md).

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
