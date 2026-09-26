# Tài liệu cấu hình (VI)

Schema cấu hình chuẩn:

- [`../../../src/config/schema/mod.rs`](../../../src/config/schema/mod.rs)

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

## Mục R.A.I.N. Rig (`[rig]`, thêm vào 2026-09)

Tùy chọn; nếu bỏ qua, hành vi cũ được giữ nguyên. Khóa không xác định bị từ chối.

```toml
[rig]
profile = "local"        # local | node | field
node_name = "rain-local" # chữ thường, chữ số, '-'; 1-32 ký tự
privacy = "local"        # local | hybrid | hosted; mặc định: theo profile, nếu không thì hybrid

[rig.meeting]            # tùy chọn; dùng chung với `python rain_lab.py`
base_url = "http://127.0.0.1:8080/v1"
model = "Qwen3-4B-Q4_K_M.gguf"

[rig.bridge]             # cầu nối Reticulum/LXMF tùy chọn
enabled = false          # mặc định false; `rig up` khởi động khi true
port = 42627             # cổng cục bộ (1024-65535); luôn lắng nghe 127.0.0.1
announce = false         # quảng bá địa chỉ LXMF của nút

[rig.radio]              # cấu hình radio Skybridge tùy chọn
receive = ["rtl_fm", "-f", "14.1M", "-M", "usb", "-s", "8000", "-"]  # argv, chỉ thu
callsign = "N0CALL"      # hô hiệu được cấp phép (phát RF + mã trạm)
max_power_w = 20         # 1-1500 W

[rig.radio.transmit]     # chỉ dùng với --features rig-rf-transmit
ptt_on = ["rigctl", "-m", "2", "F", "{frequency_hz}", "T", "1"]
play = ["aplay", "-q", "{wav}"]
ptt_off = ["rigctl", "-m", "2", "T", "0"]
```

- `[rig.meeting]` lưu điểm truy cập và mô hình của cuộc họp. Thứ tự ưu tiên:
  biến `RAIN_LLM_*` / `LM_STUDIO_*` > `[rig.meeting]` > mặc định tích hợp. Ở chế
  độ `local`, cuộc họp Python (chat, RLM) và runtime lab-server từ chối điểm
  truy cập lưu trữ bên ngoài và mô hình Ollama `:cloud`.

- `privacy = "local"` khiến việc tạo nhà cung cấp từ chối mọi điểm suy luận
  không phải loopback hoặc mạng riêng, kể cả nhà cung cấp dự phòng, tuyến mô
  hình và agent ủy quyền (lỗi có kiểu, không thử lại; không có dự phòng lưu
  trữ ngầm).
- Mọi profile tích hợp mặc định là `local` và không thể thay đổi chính sách
  bảo mật, quyền tự chủ hay địa chỉ lắng nghe.

- `[rig.bridge]`: tắt theo mặc định, không có khóa host. `rain` và cầu nối
  xác thực bằng token mà cầu nối ghi vào `<workspace>/rig/bridge.token`
  (quyền 0600) mỗi lần khởi động.
- `[rig.radio]`: mọi lệnh là argv chạy không qua shell. `receive` phải ghi
  PCM16 LE mono 8000 Hz ra stdout. Các lệnh `transmit` dùng được `{wav}`,
  `{frequency_hz}` và `{power_w}`. Bắt buộc có `ptt_off` khi đặt `ptt_on`. Ở
  bản build mặc định, `[rig.radio.transmit]` bị bỏ qua và phát RF vẫn tắt.

Hoàn tác: xóa bảng `[rig]`. Chi tiết: [`rig/getting-started.md`](../../rig/getting-started.md) (tiếng Anh).
