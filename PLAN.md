# Invoice Processor, kế hoạch v2 (đã vá theo audit)

Phân loại dữ liệu: T2 Confidential (nội bộ). Không chia sẻ ra ngoài khi chưa review.

## 0. Mục tiêu, threat model, nguyên tắc bất biến

**Mục tiêu:** đọc ~215 hóa đơn/biên lai tháng 08/2026 (PDF text, PDF scan, JPG/PNG/WEBP/HEIC), trích xuất có cấu trúc, kiểm tra số học tại máy, xuất JSONL và Excel cho kế toán.

**Threat model (đã chốt với user):** dữ liệu tài chính không được rời máy. Gemini qua proxy chỉ được thấy cấu trúc văn bản, không được thấy số liệu hay định danh.

**Dữ liệu tuyệt đối không gửi LLM (Tier A, luôn bị mask hoặc redact):**
- Mọi số có chữ số: tiền, đơn giá, số lượng, thuế, tổng, số hóa đơn, số PO, số tài khoản, mã khách hàng, mã hàng (SKU/UPC).
- Ngày tháng.
- Địa chỉ, số điện thoại, email, URL, số thẻ (kể cả 4 số cuối), tên người (khách, thu ngân, "Server: ...").
- Mã vạch, số tham chiếu giao dịch.

**Dữ liệu được gửi (Tier B, rủi ro còn lại đã chấp nhận, cần sign-off):**
- Tên nhà cung cấp và tên mặt hàng (cần để LLM phân loại chi phí và hiểu ngữ nghĩa dòng).
- Nhãn cột và nhãn trường ("Qty", "Due Date", "Subtotal").

**Bất biến (phải có test chứng minh):**
1. Vault chỉ tồn tại trong RAM, theo từng tài liệu, không bao giờ ghi ra đĩa, log, cache hay exception message.
2. Payload gửi đi đã qua Leak Guard (mục Phase 3.5). Không qua guard thì không gửi.
3. LLM chỉ trả về tham chiếu token, không bao giờ trả về giá trị số. Giá trị thật chỉ sinh ra từ vault tại máy.
4. `VERIFIED` chỉ khi mọi kiểm tra bắt buộc đều chạy và đều đạt. Thiếu dữ liệu để kiểm tra thì là `REVIEW_NEEDED`, không phải `VERIFIED`.

**Điều kiện trước khi chạy dữ liệu thật (checklist, không phải code):**
- [ ] Data Protection/Legal xác nhận Tier B được gửi Google qua proxy (PDPD Nghị định 13/2023: cơ sở pháp lý, chuyển dữ liệu xuyên biên giới; DPA với nhà cung cấp LLM).
- [ ] Kiểm tra proxy `127.0.0.1:8045`: nó chuyển tiếp tới đâu, có log request body không, ai truy cập được. Nếu log body thì phải tắt hoặc coi log là dữ liệu đã gửi.
- [ ] Xác nhận hóa đơn có chứa PII khách hàng nào không (biên lai Whole Foods/Mr Plum có thể có tên thẻ). Nếu có: thời hạn lưu giữ, đánh giá tác động (DPIA) cho phân tích.
- [ ] Quyết định ai được truy cập thư mục `output/`.

## Phase 0. Chuẩn bị môi trường, golden set, lát cắt đầu-cuối

### 0.1 Môi trường
- Python 3.11 (PaddlePaddle chưa ổn định trên 3.13). Tạo venv: `py -3.11 -m venv .venv`.
- Pin chính xác phiên bản trong `requirements.txt` sau khi cài thành công (`pip freeze`): paddlepaddle, paddleocr (nhánh 3.x), pymupdf, pillow, pillow-heif, opencv-python-headless, numpy, pydantic>=2, openpyxl, openai, python-dotenv, tqdm, pytest, rapidfuzz.
- Lý do thêm: opencv (deskew, CLAHE), rapidfuzz (khớp mờ nhãn trường), tqdm (progress bar), python-dotenv (đọc `.env.ggproproxyserver`).

### 0.2 .gitignore (làm ngay, trước commit đầu tiên)
```
.venv/
__pycache__/
.env*
output/
cache/
logs/
samples/
*.heic
```
Lý do: `output/` chứa giá nhà cung cấp (T2), `samples/` chứa hóa đơn thật, `.env*` chứa token.

### 0.3 Cấu trúc dự án
```
invoice_processor/
├── config.py            # đường dẫn, proxy URL, dung sai, ngưỡng; KHÔNG chứa secret
├── core/
│   ├── ingestion.py     # phân loại file, ImageLoader, PDF routing
│   ├── ocr_engine.py    # PaddleOCR wrapper, preprocess
│   ├── layout.py        # gom dòng, gom cột (thuật toán hình học, tách khỏi OCR để test)
│   ├── numparse.py      # parse số: locale, dấu âm, tiền tệ -> Decimal
│   ├── redactor.py      # PII redaction (địa chỉ, SĐT, email, thẻ, URL)
│   ├── tokenizer.py     # mask số -> <N_k>, <D_k>, <ID_k>; Vault
│   ├── leak_guard.py    # kiểm tra payload trước khi gửi
│   ├── llm_parser.py    # gọi Gemini proxy, JSON mode, retry, cache
│   ├── rehydrator.py    # token ref -> giá trị thật; kiểm tra token
│   ├── validator.py     # kiểm tra số học, gán status
│   └── pipeline.py      # nối các bước cho 1 file, cô lập lỗi
├── models/
│   └── schema.py        # Pydantic: LLM output schema và Canonical Invoice
├── exporters/
│   ├── jsonl_exporter.py
│   └── excel_exporter.py
├── main.py              # CLI
├── eval/
│   ├── golden/          # nhãn tay (JSON) cho ~20 file
│   └── run_eval.py      # tính metric
└── tests/
```

### 0.4 Golden set (làm trước khi code logic)
- Chọn ~20 file đại diện: 4 ca điển hình (Baldor/Chefs' Warehouse, Whole Foods/Mr Plum, HEIC, Con Edison) + ít nhất 1 credit memo, 1 hóa đơn nhiều trang, 1 PDF scan có text layer rác, 1 hóa đơn có chiết khấu, 1 hàng bán theo cân, 1 hóa đơn không phải tiếng Anh nếu có.
- Kế toán hoặc user gán nhãn tay: vendor, số hóa đơn, ngày, từng dòng (qty, price, total), subtotal, tax, các khoản phí, grand total, loại chi phí.
- Lưu ở `eval/golden/*.json`. Thư mục này có dữ liệu thật nên nằm ngoài git (thêm vào `.gitignore`).

### 0.5 Lát cắt đầu-cuối (vertical slice)
Làm đủ pipeline cho **1 file text-PDF đơn giản** trước (ingestion, layout, tokenizer, LLM, rehydrate, validate, in ra console), sau đó mới mở rộng ảnh, scan, Excel. Lý do: lộ rủi ro tích hợp sớm (schema LLM, token) trước khi đầu tư vào OCR.

**Tiêu chí xong Phase 0:** môi trường chạy được, golden set có ít nhất 10 file gán nhãn, 1 file chạy qua pipeline đến validator.

## Phase 1. Ingestion và chuẩn hóa đầu vào

### 1.1 Phân loại file
- Dò theo magic bytes, không tin đuôi file (`%PDF`, `\xff\xd8`, `\x89PNG`, `RIFF....WEBP`, `ftypheic/heix/mif1`).
- File không hỗ trợ hoặc hỏng: ghi vào danh sách lỗi (tên file, lý do), tiếp tục batch. Không làm chết cả lần chạy.
- Tính `sha256` của file gốc: dùng cho cache và dedup (mục 6.3).

### 1.2 Universal Image Loader
- `.jpg/.jpeg/.png/.webp`: Pillow. `.heic/.heif`: đăng ký `pillow_heif.register_heif_opener()` rồi mở bằng Pillow.
- **Bắt buộc `ImageOps.exif_transpose`** ngay sau khi mở (ảnh iPhone thường lưu xoay trong EXIF; thiếu bước này OCR đọc ảnh nằm ngang).
- Chuyển về RGB, rồi `numpy.ndarray` uint8. Giới hạn cạnh dài tối đa (vd 4000 px) để tránh tràn RAM với ảnh 48MP; ghi lại hệ số scale để quy ngược bounding box.
- Ảnh nhiều frame (một số WEBP/HEIC): chỉ lấy frame đầu, cảnh báo.

### 1.3 PDF dual-routing, theo từng trang
Một trang được coi là "text sạch" khi **cả ba** điều kiện đều đúng:
1. Số ký tự in được ≥ 50.
2. Tỉ lệ ký tự hợp lệ (chữ, số, dấu câu thường gặp) ≥ 0.85, loại text layer rác (OCR cũ lỗi, font không map).
3. Ảnh nền không chiếm > 80% diện tích trang.

Không đạt: render 300 DPI (`page.get_pixmap(dpi=300)`) rồi đưa vào OCR. Giới hạn kích thước pixmap để tránh trang khổ lớn ngốn RAM.
Đạt: `page.get_text("words")` lấy từ kèm bbox (cùng cấu trúc đầu ra với OCR, xem 2.4). Tôn trọng `page.rotation`.

**Hợp đồng đầu ra chung (quan trọng):** cả hai nhánh đều trả `list[Word]` với `Word(text, bbox, conf, page, source)`. `conf` của nhánh text-layer là 1.0, `source` là `"pdf_text"` hoặc `"ocr"`. Mọi bước sau chỉ nhìn kiểu dữ liệu này.

### 1.4 Gộp theo tài liệu
- Không xử lý từng trang độc lập. Gộp tất cả trang của một file thành một `Document` (danh sách trang có thứ tự) trước khi tokenize, để line items kéo qua nhiều trang và tổng ở trang cuối vẫn thuộc cùng một hóa đơn.
- Trước khi gửi LLM, loại header/footer lặp lại giữa các trang ("Page 2 of 5", tên vendor lặp) bằng so khớp dòng trùng ở mép trang.

**Tiêu chí xong:** unit test cho từng định dạng (gồm 1 file HEIC xoay EXIF), test PDF hỗn hợp (trang text + trang scan), test PDF text-layer rác bị đẩy sang OCR.

## Phase 2. OCR cục bộ và tái tạo bố cục

### 2.1 Khởi tạo PaddleOCR (API v3, kiểm tra theo phiên bản đã pin)
- Cấu hình hướng dẫn: `PaddleOCR(lang="en", use_doc_orientation_classify=True, use_doc_unwarping=False, use_textline_orientation=True)`, gọi bằng `.predict(img)`, đọc `rec_texts`, `rec_scores`, `rec_polys`.
- Các tham số cũ `use_angle_cls`, `show_log` đã bị bỏ ở v3. Nếu pin v2.x thì dùng cấu hình cũ. Một wrapper duy nhất trong `ocr_engine.py` che khác biệt này; test đảm bảo trả về `list[Word]`.
- Khởi tạo engine một lần cho cả batch (khởi tạo lại mỗi file rất chậm).
- Ngôn ngữ: xác nhận có hóa đơn tiếng Việt trong 215 file hay không. Nếu có, thêm nhánh `lang="vi"` hoặc model đa ngữ, chọn theo phát hiện ngôn ngữ trang.
- Xử lý lỗi OCR theo file: engine ném exception thì file vào danh sách lỗi, batch tiếp tục.

### 2.2 Preprocessing
Áp dụng có điều kiện, đo bằng golden set xem bước nào thật sự giúp (không bật mù quáng):
- **Deskew góc nhỏ** (cv2): ước lượng góc bằng `minAreaRect` hoặc Hough trên vùng chữ, xoay nếu |góc| > 0.5°. Orientation classifier của Paddle chỉ xử lý 0°/90°/180°/270°, không sửa nghiêng nhẹ.
- **Giấy nhiệt mờ**: chuyển xám, CLAHE (`clipLimit` ~2.0, tile 8x8), có thể thêm adaptive threshold nhẹ. Chỉ bật khi độ tương phản đo được thấp (độ lệch chuẩn xám dưới ngưỡng).
- **Biên lai khổ hẹp/dài**: ảnh có tỉ lệ cao/rộng > 3: cắt thành các đoạn chồng lấn nhau theo chiều dọc, OCR từng đoạn, ghép lại và loại trùng ở vùng chồng lấn.
- Biên lai nhăn: chấp nhận độ chính xác thấp hơn, dựa vào cờ confidence ở 2.5 để đẩy sang REVIEW thay vì cố sửa ảnh.

### 2.3 Gom dòng (line reconstruction)
Tách riêng trong `layout.py` để test thuần hình học, không cần chạy OCR.
- Ngưỡng gom theo **median chiều cao box** của trang (ví dụ hai box cùng dòng nếu độ lệch tâm Y < 0.5 × median chiều cao), không dùng số pixel cố định.
- Sắp xếp trong dòng theo X tâm trái sang phải. Dòng sắp theo Y.
- Xử lý nghiêng còn sót: dùng chiều cao tương đối và tâm box, không dùng cạnh trên.

### 2.4 Gom cột
- Giữ khoảng trắng theo khoảng cách X: giữa các box trong một dòng có khoảng cách lớn hơn ngưỡng (ví dụ > 1.5 × chiều rộng ký tự trung bình) thì chèn dấu phân cột ` | `.
- Phát hiện biên cột chung theo cụm X của các ô số ở nhiều dòng liên tiếp (ổn định cho bảng line items). Ghi nhận chỉ số cột cho mỗi ô; LLM nhìn thấy `|` còn tại máy giữ chỉ số cột để hỗ trợ kiểm tra chéo (mục 5.4).
- Kết quả: `Line(page, y, cells[(text, bbox, conf, col_idx)])`.

### 2.5 Cờ confidence
- Mỗi ô giữ `conf`. Số nào có `conf < 0.90` (ngưỡng chỉnh bằng golden set) được đánh dấu "low-confidence number" trong `Vault`; nếu số đó được dùng trong hóa đơn, status không được là `VERIFIED` dù phép tính khớp (xem 5.5).

**Tiêu chí xong:** test `layout.py` với bbox tổng hợp (nghiêng, hai cột, dòng gãy); chạy 4 ca điển hình, kiểm tra bằng mắt dòng và cột; đo tốc độ giây/trang.

## Phase 3. Tokenizer cục bộ (bảo vệ dữ liệu)

Nguyên tắc thiết kế: **tokenizer không cố hiểu vai trò số.** Regex không biết số nào nằm ở cột nào, nên mọi số bị mask thành token trung tính `<N_k>`; vai trò (qty, đơn giá, thành tiền) do LLM gán. Việc "đoán sai vai trò" biến thành lỗi mà validator bắt được, thay vì lỗi im lặng.

### 3.1 Thứ tự xử lý trên mỗi tài liệu
1. Redact PII (3.2).
2. Mask số (3.3).
3. Dựng chuỗi để gửi, kèm dấu phân cột (3.4).
4. Leak Guard (3.5).

### 3.2 PII redaction (`redactor.py`)
Thay bằng thẻ không mang thông tin: `<ADDR>`, `<PHONE>`, `<EMAIL>`, `<URL>`, `<CARD>`, `<PERSON>`.
- Email, URL, SĐT (nhiều định dạng US/VN/quốc tế), số thẻ (`**** 1234`, `xxxx1234`, `Visa ending 6411`), mã vạch dài.
- Địa chỉ: dòng có số nhà + tên đường (`\d+\s+\w+\s+(St|Ave|Blvd|Rd|...)`), mã bang + zip, "Suite/Floor/Unit". Từ khóa người: `Server|Cashier|Cust(omer)?|Guest|Member|Name on card`.
- Tên người sau các nhãn trên bị thay thế.
- Đây là heuristic. Có test cho từng mẫu và có test "không mask nhầm tên hàng" (ví dụ "Smith's Butter"). Không cố đạt 100%: lớp bảo vệ chính cho số là 3.3, PII là best-effort và được ghi rõ trong tài liệu rủi ro.

### 3.3 Mask số
- Mọi chuỗi chứa chữ số được thay bằng `<N_k>` (k tuần tự theo thứ tự đọc: trang, dòng, cột). Tuần tự và xác định để cache theo hash chuỗi đã mask có tác dụng.
- Bắt cả: `$33.99`, `33.99`, `1,234.56`, `1.234,56`, `(12.50)`, `12.50-`, `12.50 CR`, `-12.50`, `33.99T` (cờ thuế), `1.25 lb`, `2 @ 3.50`, `3 x 4.00`.
- Ký hiệu dấu (`$`, `(`, `)`, `-`, `CR`) được **tách ra giữ lại trong vault** (ghi `raw`), và để lộ cho LLM chỉ một **gợi ý hình dạng không chứa giá trị**: `<N_7:neg>` cho giá trị có ngoặc/âm/CR, `<N_8>` còn lại. Lý do: mất dấu âm là lỗi nghiêm trọng của discount/credit memo (mục audit 3).
- Ngày tháng: định dạng `MM/DD/YYYY`, `DD.MM.YYYY`, `Aug 01, 2026`, `2026-08-01`, `01-Aug-26` được thay bằng `<D_k>`. Nhãn đứng cạnh ("Invoice Date", "Due") còn nguyên nên LLM phân biệt được.
- Số định danh (số hóa đơn, PO, tài khoản) thực chất đã nằm trong `<N_k>`, vì vậy không cần loại riêng; LLM gán vai trò `invoice_no` bằng cách tham chiếu token. Mã chữ+số như `INV-2026-0831` mask toàn chuỗi thành `<ID_k>`.

### 3.4 Ngoại lệ: số quy cách (giữ nguyên, không mask)
Chỉ giữ khi khớp **chặt**, vì nếu loại nhầm một quantity thì nó rò ra ngoài:
- Dạng dính liền: `750ML`, `5LB`, `12OZ`, `A4`, `500G`.
- Dạng nhân: `6X32 OZ`, `12x1 L`, `24/12 OZ`.
- Dạng gạch: `12-PACK`, `6-CT`, `10-INCH`.
- **Không** giữ dạng tách rời kiểu `2 lb`, `3 ea`, `1 case`: đây là số lượng thật, bị mask.
- Danh sách đơn vị lấy từ `config.py` (OZ, LB, ML, L, G, KG, CT, PK, PACK, CS, EA, GAL...). Mọi ngoại lệ có test dương và âm.
- Số quy cách còn giữ lại là rủi ro thấp (không phải số tiền/số lượng giao dịch); ghi vào tài liệu rủi ro còn lại.

### 3.5 Leak Guard (`leak_guard.py`), cổng bắt buộc
Chạy trên đúng chuỗi sắp gửi:
- Từ chối nếu còn dãy số dạng tiền (`\d+[.,]\d{2}\b`), dãy ≥ 4 chữ số liên tiếp (không nằm trong ngoại lệ 3.4), mẫu email/SĐT/thẻ/URL.
- Nếu guard từ chối: file chuyển `REVIEW_NEEDED` với lý do `leak_guard`, **không gửi** LLM. Không in nội dung vi phạm ra log, chỉ ghi loại mẫu và vị trí dòng.
- Giới hạn kích thước payload (số ký tự), chặn tài liệu quá dài.
- Có test "nhồi" số vào đủ kiểu định dạng và khẳng định guard bắt được.

### 3.6 Vault
- `Vault`: dict `token -> VaultEntry(raw: str, kind, page, bbox, conf, neg_hint)`. Lưu trong đối tượng sống theo từng tài liệu; xóa ngay khi xử lý xong (`vault.clear()`).
- Không `__repr__` ra giá trị, không pickle, không đưa vào exception. Test khẳng định `repr(vault)` và log không chứa giá trị.
- Bounding box và trang trong vault dùng để điền trường tham chiếu nguồn ở schema (mục 4.3).

**Tiêu chí xong:** bộ test tokenizer (>= 40 case: định dạng số, âm, ngày, ngoại lệ, PII), property test "mọi số trong input hoặc ở vault hoặc nằm trong ngoại lệ", test Leak Guard.

## Phase 4. Trích xuất ngữ nghĩa qua LLM

### 4.1 Client
- OpenAI client trỏ `http://127.0.0.1:8045/v1`; token đọc từ `.env.ggproproxyserver` bằng python-dotenv, không log, không đưa vào config.
- `temperature=0`, JSON mode / structured output, timeout rõ ràng (ví dụ 60s), retry tối đa 3 lần với backoff cho lỗi mạng/429/5xx. Lỗi cấu trúc JSON: thử lại 1 lần kèm thông báo lỗi validate (không kèm dữ liệu).
- Giới hạn song song (ví dụ 2-4 luồng) và rate limit để không làm sập proxy.
- Cache: khóa là `sha256(chuỗi đã mask + phiên bản prompt/schema)`; giá trị là phản hồi LLM. Cache chứa chuỗi mask và token, không chứa số thật nên an toàn hơn, nhưng vẫn nằm trong `cache/` đã ignore. Chạy lại cả batch gần như miễn phí.

### 4.2 Prompt
- Mô tả: "Văn bản dưới đây đã bị che toàn bộ số và định danh bằng token `<N_k>`, `<D_k>`, `<ID_k>`. Bạn chỉ được tham chiếu token theo ID. Tuyệt đối không viết ra con số, không suy luận giá trị. Mỗi token dùng tối đa một lần. Nếu không chắc vai trò của một token, đặt `null` và thêm vào `unassigned`."
- Cung cấp vài ví dụ ngắn, ẩn danh, gồm cả hóa đơn không có qty×price (tiện ích) và dòng chiết khấu.
- Phân loại chi phí là danh sách đóng (enum) cấu hình ở `config.py` (Nguyên vật liệu thực phẩm, Bao bì/vật dụng, Điện nước, Dịch vụ, Khác); ngoài danh sách thì `Khác` + cờ `needs_review`.
- Prompt được version hóa (`PROMPT_VERSION`) và nằm trong khóa cache.

### 4.3 Schema (hai tầng)
**`LLMInvoice` (đầu ra của LLM, chỉ chứa tham chiếu token):**
- `doc_type`: `goods_invoice | receipt | utility_bill | credit_memo | statement | other`.
- Header: `vendor_name`, `invoice_no_ref`, `invoice_date_ref`, `due_date_ref`, `currency` (mã ISO hoặc ký hiệu, suy từ văn bản `$`/`USD`), `category`.
- `line_items[]`: `item_name`, `qty_ref`, `unit_price_ref`, `line_total_ref`, `unit` (nếu có), `extra_refs` (các cột số khác như ordered/shipped/backordered, đánh nhãn), `kind`: `goods | fee | discount | tax_line | deposit | shipping`.
- `charges[]` (dùng cho tiện ích như Con Edison): `description`, `amount_ref`.
- `summary`: `subtotal_ref`, `tax_ref`, `discount_ref`, `shipping_ref`, `tip_ref`, `fees_ref[]`, `grand_total_ref`, `amount_due_ref`.
- `unassigned[]`: token LLM không gán được.
- Mỗi trường `_ref` chỉ nhận đúng định dạng `<N_k>`/`<D_k>`/`<ID_k>` hoặc `null` (validator Pydantic regex).

**`CanonicalInvoice` (sau rehydrate, dùng để xuất):**
- Số dùng `Decimal`, kèm `Provenance(page, bbox, ocr_conf, source)` cho từng trường số để JSONL thực sự có "tọa độ gốc".
- `source_file`, `source_sha256`, `status`, `review_reasons[]`, `schema_version`.
- Nhiều dòng tiền, thiếu subtotal, dòng giảm trừ đều biểu diễn được; không ép mọi hóa đơn có qty×price.

### 4.4 Phân tách tài liệu có nhiều hóa đơn
- Phát hiện nhiều hóa đơn trong một file bằng nhiều nhãn "Invoice"/"Invoice #" hoặc nhiều tổng cuối khác nhau. Nếu nghi: `REVIEW_NEEDED` với lý do `multi_invoice_suspected`; không tự tách ở bản đầu (YAGNI), nhưng ghi nhận số lượng để quyết định ở Phase 7.
- `doc_type = statement` hoặc `other`: không đưa vào tổng hợp chi phí tự động, chuyển sang Sheet cảnh báo.

**Tiêu chí xong:** test với client giả (mock) cho đủ trường hợp: JSON hỏng, timeout, token ma, trả về số thật (bị chặn ở 5.1); 1 lần gọi thật trên file trong golden set.

## Phase 5. Rehydrate và cổng xác thực toán học

### 5.1 Kiểm tra token trả về từ LLM (trước khi dùng)
Với mỗi `_ref`:
1. Token phải tồn tại trong vault; nếu không thì status `REVIEW_NEEDED` lý do `unknown_token` (LLM bịa).
2. Mỗi token chỉ được dùng một lần trong các trường số; trùng thì `duplicate_token`.
3. **Coverage:** mọi token kiểu tiền trong vault phải nằm ở đâu đó (trường gán hoặc `unassigned`). Token tiền bị bỏ rơi nghĩa là LLM đã sót dòng: `orphan_money_tokens` với danh sách vị trí (trang/dòng, không in giá trị).
4. Nếu LLM trả về chuỗi trông như số thật (`\d`) ở trường tham chiếu: loại bỏ cả phản hồi, retry một lần, rồi `REVIEW_NEEDED`.

### 5.2 Parse số (`numparse.py`)
- Phát hiện locale theo từng tài liệu: nếu có dạng `\d{1,3}(\.\d{3})+,\d{2}` thì châu Âu/VN (`1.234,56`), ngược lại Mỹ (`1,234.56`); số chỉ có một dấu và hai chữ số sau thì coi là thập phân; mơ hồ (`1,234`) và không có ngữ cảnh: đánh dấu `ambiguous_number`, đẩy REVIEW.
- Dấu âm: ngoặc `(x)`, dấu `-` đầu/cuối, `CR`, hoặc gợi ý `neg` từ vault → `Decimal` âm.
- Loại ký hiệu tiền tệ và cờ thuế (`T`, `F`) ra khỏi giá trị nhưng giữ trong `raw`.
- Luôn `Decimal`, không `float`.

### 5.3 Rehydrate
- Với mỗi `_ref` hợp lệ: `Decimal` = `parse(vault[token].raw)`, kèm provenance từ vault.
- Ngày: parse local bằng danh sách định dạng, ngày không hợp lệ hoặc mơ hồ (`03/04/2026`) thì đánh `ambiguous_date`, dùng quy ước cấu hình (`MM/DD` mặc định vì thị trường Mỹ) và vẫn REVIEW nếu vendor có nhiều ngày khác nhau.
- Số nào `conf` thấp (2.5) được gắn `low_conf=True`.

### 5.4 Kiểm tra toán học (bốn tầng)
Mọi dung sai đặt trong `config.py`, mặc định bên dưới.

- **Tầng 1: từng dòng hàng hóa** (`kind=goods` có qty và unit_price): `|qty × unit_price − line_total| ≤ 0.01 + 0.005 × |qty|`. Lý do: đơn giá làm tròn 2 số lẻ nhân khối lượng lẻ (1.25 lb) sai lệch tỉ lệ thuận với qty, dung sai cố định $0.02 gây báo động giả. Dòng thiếu qty hoặc unit_price thì bỏ qua tầng 1 cho dòng đó và ghi `line_not_checkable` (không tính là lỗi nhưng cũng hạ mức tin cậy nếu quá nhiều dòng như vậy, xem 5.5).
- **Tầng 2: tổng dòng**: `|Σ line_total (goods, fee, discount có dấu) − subtotal| ≤ 0.02 + 0.005 × số dòng`. Subtotal không có trong hóa đơn thì `no_subtotal` (REVIEW).
- **Tầng 3: tổng hóa đơn**: `|subtotal + tax + shipping + tip + Σ fees − discount − grand_total| ≤ 0.02`.
  Nếu hóa đơn có nhiều dòng thuế, cộng tất cả.
- **Tầng 4: hóa đơn tiện ích/biên lai không có subtotal**: `|Σ charges − amount_due| ≤ 0.02`, ngoài ra hỗ trợ "previous balance"/"payments" qua `kind` tương ứng.
- **Kiểm tra bổ sung:** grand_total > 0 trừ credit memo; ngày hóa đơn nằm trong tháng đang xử lý ± 45 ngày (cảnh báo); `due_date ≥ invoice_date`.

### 5.5 Trạng thái
- `VERIFIED` chỉ khi **tất cả**: ít nhất tầng 3 hoặc tầng 4 chạy được và đạt; tầng 1 và 2 chạy được với ≥ 80% dòng và không có dòng nào lệch; không `low_conf` trên số nằm trong các phép tính; không có cờ `unknown_token`, `duplicate_token`, `orphan_money_tokens`, `ambiguous_*`, `multi_invoice_suspected`; `doc_type` thuộc nhóm tự động xử lý.
- `REVIEW_NEEDED`: có phép tính lệch hoặc không kiểm tra được; `review_reasons` nêu rõ, ví dụ `Dòng 3 (trang 1): qty × price ≠ total (chênh 5.00), nghi OCR đọc nhầm`. Lý do ghi vị trí và độ lệch, **không nhất thiết lặp lại số thô vào log hệ thống**; số hiện trong file kết quả cho kế toán (T2) mới là nơi chứa số.
- `FAILED`: không đọc được file, OCR/LLM lỗi sau retry. Có `error_code`, không có dữ liệu.
- Dedup và status liên quan tới trùng: xem 6.3.

**Tiêu chí xong:** test `validator.py` theo bảng (hàng bán theo cân, discount, credit memo, tiện ích, thiếu subtotal, ngoặc âm); test `rehydrator` với token ma/trùng/bỏ rơi.

## Phase 6. Đầu ra và CLI batch

### 6.1 JSONL (`output/invoices.jsonl`)
- Mỗi dòng một `CanonicalInvoice` (Decimal dưới dạng chuỗi), kèm `Provenance` (trang, bbox, conf, nguồn) cho trường số và `source_sha256`.
- Ghi theo kiểu append + flush từng hóa đơn để crash giữa chừng không mất kết quả đã làm; tên file kết quả có thể có timestamp lần chạy.
- File lỗi ghi riêng `output/failures.jsonl` (tên file, `error_code`, không chứa nội dung).

### 6.2 Excel (`output/Summary_<YYYY>-<MM>.xlsx`, tên theo tham số `--month`, không hardcode)
- Sheet 1 *Invoice Overview*: Ngày, Số bill, Nhà cung cấp, Phân loại chi phí, Tiền trước thuế, Thuế, Tổng tiền, Trạng thái, Tên file nguồn.
- Sheet 2 *Line Items Detail*: mọi dòng của mọi hóa đơn; cột `invoice_ref` để nối về Sheet 1.
- Sheet 3 *Discrepancy Alerts*: các hóa đơn `REVIEW_NEEDED`/`FAILED` kèm `review_reasons` từng dòng, đường dẫn file gốc để kế toán mở nhanh. Thêm cột *Corrected by* và *Note* để kế toán điền.
- Sheet 4 *Duplicates*: các cặp nghi trùng (6.3).
- **Chống formula injection**: mọi ô văn bản bắt đầu bằng `= + - @` (hoặc tab/CR) được tiền tố `'`/ghi ở dạng chuỗi tường minh. Số tiền ghi dạng số với `number_format`, không ghi dạng chuỗi.
- Ghi ra file tạm rồi đổi tên (atomic) để tránh file Excel nửa chừng.

### 6.3 Dedup
- Khóa nghi trùng: `(vendor chuẩn hóa, invoice_no, grand_total)`; đồng thời `source_sha256` trùng nhau (cùng file). Chuẩn hóa vendor bằng rapidfuzz (ngưỡng ~90).
- Trùng thì giữ bản đầu, đánh dấu bản sau `DUPLICATE`, không cộng vào tổng hợp, liệt kê ở Sheet 4.

### 6.4 CLI (`main.py`, argparse + tqdm)
- `python main.py <path> [--month 2026-08] [--out output] [--only <file>] [--workers 2] [--no-cache] [--dry-run]`.
- `--only <file>`: chạy một file để debug, in từng bước (có che dữ liệu nhạy cảm ở log).
- `--dry-run`: chạy đến bước mask và Leak Guard, **in payload sẽ gửi** và dừng; kế toán/bạn kiểm tra được cái gì rời máy.
- Cô lập lỗi theo file; tổng kết cuối: số file, số VERIFIED, REVIEW_NEEDED, FAILED, trùng, tổng thời gian.
- Có thể chạy tiếp (resume) bằng cache theo hash file.
- Logging: mức mặc định chỉ ghi tên file, status, mã lý do, thời gian. Không ghi text OCR, không ghi payload, không ghi vault.

## Phase 7. Đánh giá, benchmark và edge case

### 7.1 Metric trên golden set (`eval/run_eval.py`)
- **False-verify rate**: tỉ lệ file `VERIFIED` nhưng có trường sai so với nhãn. Mục tiêu: 0 trên golden set. Đây là metric quan trọng nhất; một hóa đơn sai bị tự duyệt tệ hơn nhiều so với 10 hóa đơn bị đẩy sang review.
- Tỉ lệ `VERIFIED` (tự động hóa được bao nhiêu).
- Độ chính xác theo trường: vendor, invoice_no, ngày, subtotal, tax, grand_total; độ chính xác theo dòng (item/qty/price/total).
- Tỉ lệ đúng của `category`.
- Thời gian trung bình giây/trang, theo từng nhánh (pdf_text, ocr).
- Số lần Leak Guard từ chối và nguyên nhân.

### 7.2 Bốn ca điển hình
1. Baldor / The Chefs' Warehouse: nhiều mặt hàng, nhiều trang, nhiều cột số (ordered/shipped/backordered), dòng chiết khấu và phí giao hàng.
2. Whole Foods / Mr Plum: giấy nhiệt khổ hẹp, nhăn, mờ; hàng bán theo cân; coupon và dấu ngoặc âm; cờ thuế.
3. HEIC từ iPhone: xoay EXIF, nghiêng nhẹ, nền không đều.
4. Con Edison: dạng `utility_bill` (phí, không có qty×price), nhiều khoản phí con, previous balance/payments.

### 7.3 Ca bổ sung bắt buộc thử
Credit memo; PDF nhiều hóa đơn; PDF scan có text layer rác; hóa đơn dạng statement; hóa đơn không phải tiếng Anh; hai file trùng nhau; ảnh quá lớn; file hỏng; hóa đơn có số kiểu `1.234,56`.

### 7.4 Quy trình mở rộng ra 215 file
1. Chạy `--dry-run` trên toàn bộ folder, đọc ngẫu nhiên ≥ 10 payload để xác nhận không có rò rỉ.
2. Chạy thật trên golden set, đạt mục tiêu 7.1.
3. Chạy toàn batch; kế toán duyệt toàn bộ `REVIEW_NEEDED` và **lấy mẫu ngẫu nhiên 5-10% `VERIFIED`** để đo false-verify thực tế.
4. Cập nhật dung sai/ngưỡng theo kết quả, ghi lại thay đổi.

## Kiểm thử (xuyên suốt, không dồn cuối)

| Module | Test chính |
|---|---|
| ingestion | magic bytes, HEIC + EXIF, PDF hỗn hợp, text-layer rác |
| layout | bbox tổng hợp: nghiêng, nhiều cột, dòng gãy |
| numparse | locale, âm, ngoặc, CR, mơ hồ |
| redactor | từng mẫu PII, không mask nhầm tên hàng |
| tokenizer | ≥ 40 case, ngoại lệ dương/âm, property test độ phủ |
| leak_guard | nhồi số vào mọi định dạng, phải chặn |
| llm_parser | mock: JSON hỏng, timeout, 429, token ma, trả số thật |
| rehydrator | token ma, trùng, bỏ rơi, coverage |
| validator | bảng ca: cân, discount, credit memo, tiện ích, thiếu subtotal |
| exporters | formula injection, Decimal, atomic write |
| pipeline | cô lập lỗi theo file, resume bằng cache |

## Rủi ro còn lại (ghi nhận, không phải lỗi)
- Tier B (tên vendor và tên hàng) vẫn đến Google. Nếu không chấp nhận, phương án: chạy LLM cục bộ (Ollama) cho phần ngữ nghĩa; chất lượng thấp hơn, cần đo lại bằng golden set.
- PII redaction là heuristic, có thể sót địa chỉ lạ. Leak Guard chặn các mẫu chắc chắn; phần sót nằm ở mức chấp nhận hoặc cần bước review `--dry-run`.
- Số quy cách giữ nguyên (3.4) vẫn xuất hiện trong payload.
- OCR giấy nhiệt mờ có thể đọc sai số mà phép tính vô tình vẫn khớp (hiếm); giảm bằng cờ confidence và lấy mẫu VERIFIED.
- Proxy local là điểm lỗi duy nhất; có retry và cache, chưa có fallback.
- Bản kế hoạch và kết quả do AI tạo, cần người xem lại trước khi dùng cho quyết định tài chính hoặc đưa ra ngoài.

## Thứ tự thực hiện đề xuất
1. 0.1, 0.2, 0.4 (môi trường, .gitignore, golden set) song song với checklist pháp lý.
2. 0.5 lát cắt đầu-cuối trên 1 file text-PDF.
3. Phase 3 (tokenizer + Leak Guard) và Phase 5 (validator) vì rủi ro cao nhất, test kỹ trước.
4. Phase 1, 2 mở rộng đầu vào ảnh/scan/HEIC.
5. Phase 4 hoàn thiện schema, cache, retry.
6. Phase 6 xuất file, CLI, dedup.
7. Phase 7 đánh giá, chạy 215 file theo quy trình 7.4.
