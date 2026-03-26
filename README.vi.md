# Điểm vào tài liệu R.A.I.N. Lab (VI)

<p align="center">
  <a href="https://github.com/topherchris420/james_library/actions/workflows/ci.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/tests.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/tests.yml/badge.svg?branch=main" alt="Tests" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/deploy-docs.yml/badge.svg?branch=main" alt="Docs" /></a>
  <a href="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml"><img src="https://github.com/topherchris420/james_library/actions/workflows/sec-audit.yml/badge.svg?branch=main" alt="Security Audit" /></a>
</p>

> Trang này là điểm vào tiếng Việt, đồng bộ với README chính và cấu trúc docs.

## Điều hướng

- README chính: [`README.md`](README.md)
- Hub tài liệu tiếng Việt: [`docs/i18n/vi/README.md`](docs/i18n/vi/README.md)
- Mục lục tổng hợp: [`docs/SUMMARY.md`](docs/SUMMARY.md)

## Bản đồ nhanh về định danh dự án

- **R.A.I.N. Lab**: trải nghiệm sản phẩm cho người dùng cuối
- **James Library**: lớp nghiên cứu/quy trình Python
- **R.A.I.N.**: lớp runtime Rust (crate `R.A.I.N.`)

Luồng chạy: `Người dùng -> giao diện R.A.I.N. Lab -> runtime R.A.I.N. -> quy trình nghiên cứu James Library -> API model/provider`

## Bắt đầu nhanh

```bash
python rain_lab.py
```

Xem thêm tài liệu lệnh và cấu hình trong docs hub và các trang tham chiếu runtime.

## Năng lực tổng quan (Capabilities At A Glance)

Trang này là điểm vào. Để xem đầy đủ bề mặt runtime (lệnh, kênh, provider, vận hành, bảo mật, phần cứng), dùng các liên kết bên dưới.

| Nhóm năng lực | Bạn nhận được gì | Tài liệu chuẩn |
| --- | --- | --- |
| CLI và tự động hóa | Onboarding, agent, gateway/daemon, service, chẩn đoán, estop, cron, skills, cập nhật | [Commands Reference](docs/reference/cli/commands-reference.md) |
| Kênh và nhắn tin | Phân phối đa kênh, allowlist, chế độ webhook/polling, cấu hình theo kênh | [Channels Reference](docs/reference/api/channels-reference.md) |
| Provider và định tuyến mô hình | Provider local/cloud, alias, biến môi trường xác thực, quy trình làm mới mô hình | [Providers Reference](docs/reference/api/providers-reference.md) |
| Cấu hình và hợp đồng runtime | Schema cấu hình và cam kết hành vi | [Config Reference](docs/reference/api/config-reference.md) |
| Vận hành và xử lý sự cố | Runbook, mẫu triển khai, chẩn đoán và khôi phục lỗi | [Operations Runbook](docs/ops/operations-runbook.md), [Troubleshooting](docs/ops/troubleshooting.md) |
| Mô hình bảo mật | Sandbox, ranh giới chính sách, tư thế kiểm toán | [Security Docs Hub](docs/security/README.md) |
| Phần cứng và thiết bị ngoại vi | Thiết lập board và thiết kế công cụ ngoại vi | [Hardware Docs Hub](docs/hardware/README.md) |

## Ai nên đọc gì tiếp theo (Who Should Read What Next)

- **Người dùng mới / lần đầu trải nghiệm**: bắt đầu từ [`START_HERE.md`](START_HERE.md), sau đó đọc [`docs/getting-started/README.md`](docs/getting-started/README.md), sau đó [`docs/troubleshooting.md`](docs/troubleshooting.md).
- **Vận hành / chủ sở hữu triển khai**: ưu tiên [`docs/ops/operations-runbook.md`](docs/ops/operations-runbook.md), [`docs/ops/network-deployment.md`](docs/ops/network-deployment.md), [`docs/security/README.md`](docs/security/README.md).
- **Tích hợp / phát triển mở rộng**: ưu tiên [`docs/reference/cli/commands-reference.md`](docs/reference/cli/commands-reference.md), [`docs/reference/api/providers-reference.md`](docs/reference/api/providers-reference.md), [`docs/reference/api/channels-reference.md`](docs/reference/api/channels-reference.md).
