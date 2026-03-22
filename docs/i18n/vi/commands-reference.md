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
