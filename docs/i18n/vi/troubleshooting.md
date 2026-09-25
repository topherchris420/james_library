# Khac phuc su co (VI)

Diem vao canonical cho tieng Viet:

- [`../../troubleshooting.md`](../../troubleshooting.md)

## Đánh giá có kiểu dữ liệu, tùy chọn

Lệnh `python rain_lab.py judge --evidence cycle.json` đánh giá một gói bằng chứng
đã được chọn lọc. [Hướng dẫn đánh giá có kiểu dữ liệu](../../typed-judgment.md)
(tiếng Anh) mô tả cấu trúc JSON và các ngưỡng quyết định chính xác.

- `INVALID EVIDENCE OR CONFIGURATION` (mã thoát 2): kiểm tra schema
  `rain-judgment-cycle/v1`, các trường bắt buộc, kiểu dữ liệu, khóa JSON trùng lặp
  và giới hạn 128 KiB. Loại bỏ trường không được hỗ trợ và bí mật khỏi gói.
  `RAIN_JUDGMENT_PROVIDER` phải là `off` hoặc `typesafe`.
- `DISABLED`: mặc định là `off`. Để chủ động bật Jev, đặt
  `RAIN_JUDGMENT_PROVIDER=typesafe` và `TYPESAFE_API_KEY` trong môi trường cục bộ.
  Không đưa khóa vào gói bằng chứng, nhật ký hoặc phiếu báo lỗi.
  `TYPESAFE_MODEL` là tùy chọn (mặc định `jev-latest`).
- `NOT_RUN` (hiển thị `NOT RUN`) với `peer_score_below_threshold`: điểm phản biện
  dưới 8; cần sửa lại đề xuất. Nhà cung cấp chưa được gọi.
- `UNAVAILABLE` với `provider_not_configured` hoặc `provider_authentication_error`:
  kiểm tra sự hiện diện và tính hợp lệ của `TYPESAFE_API_KEY` trong môi trường
  của tiến trình. Với `provider_timeout` hoặc `provider_transport_error`, kiểm tra
  kết nối và tình trạng dịch vụ. Với `provider_rate_limited`, đợi trước khi chạy
  lại thủ công. Không tự động thử lại hoặc chuyển sang mô hình khác; lỗi không
  bao giờ cho phép chuyển sang giai đoạn khám phá.
- `REVISE`: sửa bằng chứng, mâu thuẫn, phạm vi khẳng định hoặc kết quả kiểm tra
  cục bộ không đạt. `HUMAN_REVIEW`: yêu cầu con người xem xét rõ ràng mức độ
  bất định; kiểm tra chưa chạy hoặc bị lỗi, hay trạng thái bị cắt bớt, cũng
  yêu cầu xem xét. Xem chính sách trong hướng dẫn để biết các ngưỡng.
  Mã thoát 1 nghĩa là chưa được chuyển sang giai đoạn khám phá.
- `RECORDED JUDGMENT INVALID` (mã thoát 2) khi dùng `judge --replay`: kiểm tra
  tệp là bản ghi phiên nguyên vẹn. Mã băm trạng thái hoặc phong bì bản ghi
  không khớp sẽ bị từ chối; khôi phục bản gốc thay vì tính lại mã băm để che
  giấu thay đổi. Đọc lại bản ghi không gọi nhà cung cấp.

Chạy lại các ca tham chiếu luôn tắt đánh giá trong tiến trình con và loại bỏ
thông tin xác thực TypeSafe. `--live-judgment` bị từ chối: dùng rõ ràng
`judge --evidence` để đánh giá mới. `PASS` là quyết định định tuyến có giới hạn,
không phải bằng chứng khoa học.

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

## R.A.I.N. Rig

- `rain rig doctor` báo `FAIL default provider … not reachable`: máy chủ cục
  bộ đã cấu hình chưa chạy. Hãy tự khởi động (ví dụ `llama-server -m model.gguf --port 8080`
  hoặc `ollama serve`); Rig không bao giờ khởi động máy chủ của bên thứ ba.
- `privacy mode 'local' refuses inference provider '…'`: có nhà cung cấp lưu
  trữ bên ngoài trong khi quyền riêng tư là `local`. Dùng máy chủ cục bộ
  (`rain rig setup` sẽ đề xuất nếu phát hiện) hoặc đặt `[rig] privacy = "hybrid"`.
- Trạng thái `BLOCKED` với `EXTERNAL BIND`: `[gateway] host` không phải
  loopback và không được cho phép rõ ràng. Hãy dùng `host = "127.0.0.1"`.
- `research library not found`: chạy `rain rig` từ thư mục James Library hoặc
  truyền `--library <đường dẫn>`.
- Cảnh báo `meeting inference`: mô hình của cuộc họp Python là mô hình Ollama
  `:cloud` hoặc chưa được chỉ định. Hãy đặt `RAIN_LLM_MODEL`.
