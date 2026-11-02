# Invoice Processor (Tháng 08/2026)

Hệ thống xử lý hóa đơn, trích xuất cấu trúc văn bản bảo vệ quyền riêng tư tài chính và kiểm tra số học cục bộ cho kế toán.

## 1. Cài đặt môi trường

Yêu cầu: Python 3.10 hoặc 3.11.

```bash
# Tạo môi trường ảo
py -3.10 -m venv .venv

# Kích hoạt môi trường (Windows PowerShell / Git Bash)
source .venv/Scripts/activate

# Cài đặt các gói phụ thuộc đã pin
pip install -r requirements.txt
```

Cấu hình token proxy LLM: Đặt API token trong file `.env.ggproproxyserver` (không bao giờ commit file này lên git).

---

## 2. Cách chạy hệ thống

### Chạy kiểm tra rò rỉ trước khi xử lý (`--dry-run`)
Chạy đến bước mask & Leak Guard, in toàn bộ payload sẽ gửi ra console để kiểm tra độc lập và dừng (không gọi LLM):
```bash
python main.py samples_synthetic/ --month 2026-08 --dry-run
```

### Chạy thử nghiệm một file đơn lẻ (`--only`)
In chi tiết các bước xử lý (Ingestion, Preprocessing, Layout, Redactor, Tokenizer, Leak Guard, Rehydrate, Validator):
```bash
python main.py samples_synthetic/ --only 01_multipage_goods.pdf --month 2026-08
```

### Chạy batch toàn bộ thư mục
```bash
python main.py samples_synthetic/ --month 2026-08 --out output --workers 2
```

Tùy chọn:
- `--no-cache`: Bỏ qua cache phản hồi LLM (mặc định cache lưu tại `cache/` theo mã băm nội dung).
- `--workers <N>`: Số luồng xử lý song song (mặc định: 2).

---

## 3. Ý nghĩa trạng thái (Status)

Mọi hóa đơn sau khi trích xuất được gán một trong các trạng thái:
- `VERIFIED`: Đạt toàn bộ kiểm tra toán học bắt buộc (Tầng 1 hàng hóa, Tầng 2 tổng dòng, Tầng 3 tổng hóa đơn hoặc Tầng 4 chi phí tiện ích); độ tin cậy OCR cao (`>= 0.90`); không có số/ngày mơ hồ; không có token lạ/trùng/bỏ rơi.
- `REVIEW_NEEDED`: Cần con người kiểm tra lại. Xảy ra khi: lệch toán học; thiếu subtotal; chữ số OCR mờ (`< 0.90`); ngày mơ hồ (`ambiguous_date`); hoặc tài liệu dạng bảng kê (`statement`/`other`). Lý do chi tiết được ghi trong cột *Discrepancy Alerts*.
- `FAILED`: Không đọc được file, file hỏng, hoặc lỗi không phục hồi được sau retry.
- `DUPLICATE`: Hóa đơn trùng lặp (cùng mã băm nội dung SHA-256 hoặc trùng bộ khóa vendor, số bill, tổng tiền). Bản đầu được giữ lại, bản sau bị đánh dấu trùng và không cộng vào tổng hợp chi phí.

---

## 4. Cấu trúc thư mục đầu ra (`output/`)

```
output/
├── invoices.jsonl          # Danh sách CanonicalInvoice (Decimal dưới dạng chuỗi, kèm Provenance tọa độ gốc)
├── failures.jsonl          # Danh sách file lỗi (đường dẫn, mã lỗi; không chứa nội dung văn bản)
└── Summary_2026-08.xlsx    # Báo cáo Excel 4 sheet cho kế toán:
    ├── Sheet 1: Invoice Overview (Ngày, Số bill, Nhà cung cấp, Loại chi phí, Tiền trước thuế, Thuế, Tổng tiền, Trạng thái, File nguồn)
    ├── Sheet 2: Line Items Detail (Chi tiết từng dòng hàng của các hóa đơn hợp lệ, liên kết về Sheet 1)
    ├── Sheet 3: Discrepancy Alerts (Danh sách REVIEW_NEEDED và FAILED kèm lý do, hyperlink mở file gốc, cột kiểm toán)
    └── Sheet 4: Duplicates (Danh sách các cặp nghi trùng lặp và lý do)
```

---

## 5. Checklist pháp lý & An toàn thông tin (PLAN.md Mục 0)

Trước khi chạy hệ thống trên dữ liệu hóa đơn thật, các bộ phận liên quan phải hoàn thành checklist sau:
- [ ] **Data Protection / Pháp chế:** Xác nhận việc gửi tên vendor và tên mặt hàng (Tier B) qua proxy LLM phù hợp Nghị định 13/2023/NĐ-CP (PDPD: cơ sở pháp lý, chuyển dữ liệu xuyên biên giới, DPA với nhà cung cấp LLM).
- [ ] **Bảo mật Proxy:** Kiểm tra proxy local `http://127.0.0.1:8045/v1`: xác nhận cấu hình không log request body, giới hạn quyền truy cập cục bộ.
- [ ] **Dữ liệu PII khách hàng:** Đánh giá các biên lai bán lẻ có chứa tên thẻ khách hàng/thu ngân hay không; xác định thời hạn lưu giữ và đánh giá tác động DPIA.
- [ ] **Kiểm soát truy cập thư mục:** Phân quyền thư mục `output/` chỉ cho nhân sự kế toán được ủy quyền truy cập (dữ liệu giá nhà cung cấp là T2 Confidential).
- [ ] **Kiểm toán xác thực độc lập:** Kế toán kiểm tra toàn bộ danh sách `REVIEW_NEEDED` và lấy mẫu ngẫu nhiên 5-10% các hóa đơn `VERIFIED` để đo lường độ chính xác thực tế trước khi hạch toán.
