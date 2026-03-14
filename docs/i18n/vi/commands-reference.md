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

- `zeroclaw gateway` và `zeroclaw daemon` dùng `gateway.port` từ config khi không truyền `--port`.
- Nếu muốn mặc định cầu nối Body-daemon, đặt `gateway.port = 4200` trong config hoặc `ZEROCLAW_GATEWAY_PORT=4200` trong môi trường.
- Khởi động sẽ bị chặn nếu dừng khẩn cấp đang bật ở mức `kill-all` hoặc `network-kill`.
