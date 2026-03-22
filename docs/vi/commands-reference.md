# Tham khảo lệnh R.A.I.N.

Dựa trên CLI hiện tại (`R.A.I.N. --help`).

Xác minh lần cuối: **2026-02-20**.

## Lệnh cấp cao nhất

| Lệnh | Mục đích |
|---|---|
| `onboard` | Khởi tạo workspace/config nhanh hoặc tương tác |
| `agent` | Chạy chat tương tác hoặc chế độ gửi tin nhắn đơn |
| `gateway` | Khởi động gateway webhook và HTTP WhatsApp |
| `daemon` | Khởi động runtime có giám sát (gateway + channels + heartbeat/scheduler tùy chọn) |
| `service` | Quản lý vòng đời dịch vụ cấp hệ điều hành |
| `doctor` | Chạy chẩn đoán và kiểm tra trạng thái |
| `status` | Hiển thị cấu hình và tóm tắt hệ thống |
| `cron` | Quản lý tác vụ định kỳ |
| `models` | Làm mới danh mục model của provider |
| `providers` | Liệt kê ID provider, bí danh và provider đang dùng |
| `channel` | Quản lý kênh và kiểm tra sức khỏe kênh |
| `integrations` | Kiểm tra chi tiết tích hợp |
| `skills` | Liệt kê/cài đặt/gỡ bỏ skills |
| `migrate` | Nhập dữ liệu từ runtime khác (hiện hỗ trợ OpenClaw) |
| `config` | Xuất schema cấu hình dạng máy đọc được |
| `completions` | Tạo script tự hoàn thành cho shell ra stdout |
| `hardware` | Phát hiện và kiểm tra phần cứng USB |
| `peripheral` | Cấu hình và nạp firmware thiết bị ngoại vi |

## Nhóm lệnh

### `onboard`

- `R.A.I.N. onboard`
- `R.A.I.N. onboard --channels-only`
- `R.A.I.N. onboard --api-key <KEY> --provider <ID> --memory <sqlite|lucid|markdown|none>`
- `R.A.I.N. onboard --api-key <KEY> --provider <ID> --model <MODEL_ID> --memory <sqlite|lucid|markdown|none>`

### `agent`

- `R.A.I.N. agent`
- `R.A.I.N. agent -m "Hello"`
- `R.A.I.N. agent --provider <ID> --model <MODEL> --temperature <0.0-2.0>`
- `R.A.I.N. agent --peripheral <board:path>`

### `gateway` / `daemon`

- `R.A.I.N. gateway [--host <HOST>] [--port <PORT>]`
- `R.A.I.N. daemon [--host <HOST>] [--port <PORT>]`

### `service`

- `R.A.I.N. service install`
- `R.A.I.N. service start`
- `R.A.I.N. service stop`
- `R.A.I.N. service restart`
- `R.A.I.N. service status`
- `R.A.I.N. service uninstall`

### `cron`

- `R.A.I.N. cron list`
- `R.A.I.N. cron add <expr> [--tz <IANA_TZ>] <command>`
- `R.A.I.N. cron add-at <rfc3339_timestamp> <command>`
- `R.A.I.N. cron add-every <every_ms> <command>`
- `R.A.I.N. cron once <delay> <command>`
- `R.A.I.N. cron remove <id>`
- `R.A.I.N. cron pause <id>`
- `R.A.I.N. cron resume <id>`

### `models`

- `R.A.I.N. models refresh`
- `R.A.I.N. models refresh --provider <ID>`
- `R.A.I.N. models refresh --force`

`models refresh` hiện hỗ trợ làm mới danh mục trực tiếp cho các provider: `openrouter`, `openai`, `anthropic`, `groq`, `mistral`, `deepseek`, `xai`, `together-ai`, `gemini`, `ollama`, `astrai`, `venice`, `fireworks`, `cohere`, `moonshot`, `glm`, `zai`, `qwen` và `nvidia`.

### `channel`

- `R.A.I.N. channel list`
- `R.A.I.N. channel start`
- `R.A.I.N. channel doctor`
- `R.A.I.N. channel bind-telegram <IDENTITY>`
- `R.A.I.N. channel add <type> <json>`
- `R.A.I.N. channel remove <name>`

Lệnh trong chat khi runtime đang chạy (Telegram/Discord):

- `/models`
- `/models <provider>`
- `/model`
- `/model <model-id>`

Channel runtime cũng theo dõi `config.toml` và tự động áp dụng thay đổi cho:
- `default_provider`
- `default_model`
- `default_temperature`
- `api_key` / `api_url` (cho provider mặc định)
- `reliability.*` cài đặt retry của provider

`add/remove` hiện chuyển hướng về thiết lập có hướng dẫn / cấu hình thủ công (chưa hỗ trợ đầy đủ mutator khai báo).

### `integrations`

- `R.A.I.N. integrations info <name>`

### `skills`

- `R.A.I.N. skills list`
- `R.A.I.N. skills install <source>`
- `R.A.I.N. skills remove <name>`

`<source>` chấp nhận git remote (`https://...`, `http://...`, `ssh://...` và `git@host:owner/repo.git`) hoặc đường dẫn cục bộ.

Skill manifest (`SKILL.toml`) hỗ trợ `prompts` và `[[tools]]`; cả hai được đưa vào system prompt của agent khi chạy, giúp model có thể tuân theo hướng dẫn skill mà không cần đọc thủ công.

### `migrate`

- `R.A.I.N. migrate openclaw [--source <path>] [--dry-run]`

### `config`

- `R.A.I.N. config schema`

`config schema` xuất JSON Schema (draft 2020-12) cho toàn bộ hợp đồng `config.toml` ra stdout.

### `completions`

- `R.A.I.N. completions bash`
- `R.A.I.N. completions fish`
- `R.A.I.N. completions zsh`
- `R.A.I.N. completions powershell`
- `R.A.I.N. completions elvish`

`completions` chỉ xuất ra stdout để script có thể được source trực tiếp mà không bị lẫn log/cảnh báo.

### `hardware`

- `R.A.I.N. hardware discover`
- `R.A.I.N. hardware introspect <path>`
- `R.A.I.N. hardware info [--chip <chip_name>]`

### `peripheral`

- `R.A.I.N. peripheral list`
- `R.A.I.N. peripheral add <board> <path>`
- `R.A.I.N. peripheral flash [--port <serial_port>]`
- `R.A.I.N. peripheral setup-uno-q [--host <ip_or_host>]`
- `R.A.I.N. peripheral flash-nucleo`

## Kiểm tra nhanh

Để xác minh nhanh tài liệu với binary hiện tại:

```bash
R.A.I.N. --help
R.A.I.N. <command> --help
```
