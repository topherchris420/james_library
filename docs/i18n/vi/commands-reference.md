# Tài liệu lệnh (VI)

Lệnh chính:

```bash
python rain_lab.py
```

Chế độ thường dùng:

- `--mode first-run`
- `--mode chat --topic "..."`
- `--mode validate`
- `--mode status`
- `--mode models`
- `--mode backup -- --json`

## Lệnh cầu nối runtime ZeroClaw

Điểm vào cho runtime Rust:

```bash
zeroclaw gateway
zeroclaw daemon
```

Ghi chú:

- `zeroclaw gateway` và `zeroclaw daemon` mặc định dùng cổng `4200` khi không truyền `--port`.
- Khởi động sẽ bị chặn nếu dừng khẩn cấp đang bật ở mức `kill-all` hoặc `network-kill`.
