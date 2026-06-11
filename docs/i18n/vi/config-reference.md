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
