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

## Toàn bộ khả năng của James

James không chỉ là một hệ thống chat đa agent — đó là một hệ điều hành nghiên cứu hoàn chỉnh: 10+ nhà cung cấp mô hình, 25+ nền tảng nhắn tin, 60+ công cụ tích hợp, điều khiển phần cứng (Arduino, STM32, Raspberry Pi), mô hình mã hóa não thần kinh học (TRIBE v2), đồ thị tri thức, bộ nhớ ngữ nghĩa, và nhiều hơn nữa. Danh sách đầy đủ tại [`README.md` tiếng Anh - What You Can Do](README.md#what-you-can-do).

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

## Xem hoạt động thực tế

Đặt một câu hỏi nghiên cứu thô. Xem bốn agent chuyên gia — James (nhà khoa học trưởng), Jasmine (hậu tiến sĩ hoài nghi), Luca (nhà hình học) và Elena (nhà logic học) — tranh luận theo thời gian thực.

```
TOPIC: Could a "Phononic Morphogenetic Field" — precise acoustic interference patterns
guiding matter assembly like DNA guides cell growth — actually work?

**James:** ...phononic frequency combs could act like an acoustic blueprint for
molecular organization. The missing link between quantum coherence and biological
assembly?

**Jasmine:** Hold on. Cymatic patterns are *static* — they don't adapt to errors
or material changes the way DNA does. And the energy density needed exceeds
current acoustic levitation by *orders of magnitude*. Where's the thermal
dissipation analysis?

**Luca:** The geometry is compelling though. Wavelength spacing in phononic
combs (ωₙ₊₁ - ωₙ = 2πc/λ) parallels scalar field gradients in relic field
tomography. But macroscopic assembly requires E > 10⁴⁵ J — far beyond reach.

**Elena:** The math is elegant but the premise has a fatal flaw. The energy
density violates the Landauer limit by multiple orders of magnitude. Current
systems operate ~10³ times lower. Without experimental validation at that
scale, this remains speculation.

[Meeting continues — James responds, Jasmine pushes back, consensus forms...]
```

Tham gia một cuộc họp nghiên cứu, khám phá các bất đồng và ra về với các bước tiếp theo — không chỉ là liên kết.

---

## Chất lượng đầu ra và mức độ tin cậy

### Chất lượng đầu ra (đã benchmark)

R.A.I.N. Lab theo dõi chất lượng kỹ thuật trong CI và công bố rõ định nghĩa chỉ số, baseline, cùng mục tiêu (ví dụ: số lần panic, số lần unwrap, tỷ lệ test flaky và độ bao phủ critical path).

- Hợp đồng chỉ số chất lượng: [`docs/project/quality-metrics.md`](docs/project/quality-metrics.md)
- Bộ tạo báo cáo chất lượng: [`scripts/ci/quality_metrics_report.py`](scripts/ci/quality_metrics_report.py)

Với benchmark đầu ra nghiên cứu, chúng tôi khuyến nghị công bố bộ hiện vật đánh giá before/after có thể tái lập (task set, baseline, rubric, file kết quả) cùng với các báo cáo chất lượng này.

### Câu chuyện tin cậy + quyền riêng tư

R.A.I.N. Lab được thiết kế local-first với mặc định an toàn:

- hỗ trợ luồng làm việc local/private và tùy chọn định tuyến model cục bộ
- gateway mặc định bind vào localhost, bật pairing và tắt public bind
- tư thế allowlist theo nguyên tắc deny-by-default cho truy cập kênh
- xử lý secret quan trọng bằng mã hóa at-rest

Tài liệu bảo mật theo hành vi hiện tại:

- [`docs/security/README.md`](docs/security/README.md)
- [`docs/reference/api/config-reference.md`](docs/reference/api/config-reference.md)
