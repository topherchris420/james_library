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

## Dành cho ai

R.A.I.N. Lab được xây dựng cho những người cần câu trả lời có thể bảo vệ được, chứ không chỉ những câu trả lời nghe có vẻ hay.

| Vai trò | Bạn có thể làm gì với R.A.I.N. Lab |
| --- | --- |
| Nhà sáng lập và lãnh đạo sản phẩm | Kiểm tra áp lực các quyết định chiến lược bằng tranh luận có cấu trúc trước khi cam kết lộ trình hoặc ngân sách |
| Nhà nghiên cứu và phân tích | So sánh các giả thuyết cạnh tranh, bảo tồn bất đồng và ghi lại các chuỗi lập luận có thể kiểm toán |
| Vận hành và đội ngũ kỹ thuật | Biến các cuộc thảo luận lộn xộn thành đầu ra có thể xác minh, sẵn sàng để xem xét, chia sẻ và chạy lại |

Trên thực tế, điều này có nghĩa là ít hơn những ngõ cụt kiểu "AI đã nói vậy". Bạn có thể bắt đầu từ một câu hỏi duy nhất, để nhiều agent thách thức các giả định, chuyển các xung đột chưa giải quyết qua quy trình xác minh, và ra về với kết quả mà bạn có thể tự tin trình bày cho người khác.

## Bắt đầu nhanh

```bash
python rain_lab.py
```

Xem thêm tài liệu lệnh và cấu hình trong docs hub và các trang tham chiếu runtime.
