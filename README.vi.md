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

## Tổng quan tính năng

James không chỉ là một hệ thống chat đa agent — đó là một hệ điều hành nghiên cứu hoàn chỉnh: 10+ nhà cung cấp mô hình, 25+ nền tảng nhắn tin, 60+ công cụ tích hợp, điều khiển phần cứng (Arduino, STM32, Raspberry Pi), mô hình mã hóa não thần kinh học (TRIBE v2), đồ thị tri thức, bộ nhớ ngữ nghĩa, và nhiều hơn nữa. Danh sách đầy đủ tại [`README.md` tiếng Anh - What It Does](README.md#what-it-does).

## Dành cho ai

R.A.I.N. Lab được xây dựng cho những người cần câu trả lời có thể bảo vệ được, chứ không chỉ những câu trả lời nghe có vẻ hay.

| Vai trò | Bạn có thể làm gì với R.A.I.N. Lab |
| --- | --- |
| Nhà sáng lập và lãnh đạo sản phẩm | Kiểm tra áp lực các quyết định chiến lược bằng tranh luận có cấu trúc trước khi cam kết lộ trình hoặc ngân sách |
| Nhà nghiên cứu và phân tích | So sánh các giả thuyết cạnh tranh, bảo tồn bất đồng và ghi lại các chuỗi lập luận có thể kiểm toán |
| Vận hành và đội ngũ kỹ thuật | Biến các cuộc thảo luận lộn xộn thành đầu ra có thể xác minh, sẵn sàng để xem xét, chia sẻ và chạy lại |

## Điểm khác biệt

| Công cụ nghiên cứu thông thường | R.A.I.N. Lab |
| --- | --- |
| Trả về danh sách bài báo | Trả về một cuộc tranh luận |
| Coi câu trả lời hợp lý đầu tiên là đúng | Giữ lại bất đồng cho đến khi có bằng chứng giải quyết |
| Một góc nhìn, một mô hình | Bốn tiếng nói với chuyên môn và ràng buộc khác nhau |
| Ưu tiên cloud | Chạy hoàn toàn cục bộ nếu bạn muốn |

## Quy trình làm việc cục bộ và riêng tư

R.A.I.N. Lab chạy hoàn toàn trên phần cứng của bạn. Kết nối mô hình cục bộ qua [LM Studio](https://lmstudio.ai/) hoặc [Ollama](https://ollama.com/) — không có cuộc gọi cloud, không telemetry, không chia sẻ dữ liệu.

## Bắt đầu nhanh

**Demo trực tuyến:** [rainlabteam.vercel.app](https://rainlabteam.vercel.app/) — không cần cài đặt

```bash
python rain_lab.py
```

Windows: nhấp đúp `INSTALL_RAIN.cmd`.
macOS/Linux: chạy `./install.sh`.

Xem thêm tài liệu lệnh và cấu hình trong docs hub và các trang tham chiếu runtime.

## Yêu cầu hệ thống

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (khuyến nghị) hoặc pip
- Rust toolchain (tùy chọn, cho lớp runtime ZeroClaw)
- Mô hình cục bộ qua [LM Studio](https://lmstudio.ai/) hoặc [Ollama](https://ollama.com/) (tùy chọn — chế độ demo không cần)

## Tài liệu

| | |
|---|---|
| **Bắt đầu** | [Bắt đầu tại đây](START_HERE.md) -- [Hướng dẫn cho người mới](docs/getting-started/README.md) -- [Cài đặt một cú nhấp](docs/one-click-bootstrap.md) -- [Khắc phục sự cố](docs/troubleshooting.md) |
| **Bài báo** | [Kho nghiên cứu](https://topherchris420.github.io/research/) |
| **Ngôn ngữ khác** | [English](README.md) -- [简体中文](README.zh-CN.md) -- [日本語](README.ja.md) -- [Русский](README.ru.md) -- [Français](README.fr.md) |

## Dành cho nhà phát triển

Kiến trúc, điểm mở rộng và hướng dẫn đóng góp có tại [`README.md` tiếng Anh - For Developers](README.md#for-developers), [ARCHITECTURE.md](ARCHITECTURE.md) và [CLAUDE.md](CLAUDE.md).

## Lời cảm ơn

Đặc biệt cảm ơn đội ngũ **ZeroClaw** đã xây dựng engine runtime Rust làm nền tảng cho R.A.I.N. Lab. Xem thư mục `crates/` để biết thêm chi tiết.

---

**Giấy phép:** MIT -- [Vers3Dynamics](https://vers3dynamics.com/)
