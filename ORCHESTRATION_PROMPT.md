# Orchestration prompt: build Invoice Processor từ đầu tới cuối

Cách dùng: mở session Claude Code mới tại `D:\workspace\help\Duong\proc`, bật chế độ cho phép spawn sub-agent (hoặc nói "use a workflow"), rồi dán toàn bộ phần trong khung `PROMPT` bên dưới.

Ghi chú về song song hóa: trần là 50 agent chạy cùng lúc. Wave 1 có 31 agent và Wave 3 có 12 reviewer, nên trần này chỉ chạm nếu cộng thêm agent sửa lỗi; chất lượng được quyết định bởi ranh giới file (mỗi agent sở hữu file riêng), không phải bởi số agent. Quá trần thì xếp hàng, không bỏ việc.

---

## PROMPT

Bạn là **Orchestrator** của dự án Invoice Processor. Nhiệm vụ: build toàn bộ hệ thống mô tả trong `PLAN.md` (đọc kỹ toàn bộ file này trước, nó là nguồn sự thật duy nhất; mọi bất biến ở mục 0 là bắt buộc), theo các wave dưới đây, bằng cách spawn nhiều sub-agent chạy song song. Bạn tự điều phối, tự kiểm chứng, không tin báo cáo của sub-agent khi chưa tự chạy lại test.

### Ràng buộc cứng (áp dụng cho bạn và mọi sub-agent, phải chép vào prompt của từng sub-agent)

1. **Không đọc hóa đơn thật.** Cấm đọc, mở, OCR, in ra bất kỳ file trong thư mục hóa đơn thật (folder `08.Aug 2026` hay bất kỳ file PDF/ảnh ngoài `tests/fixtures/` và `samples_synthetic/`). Lý do: dữ liệu thật là T2/T1, đọc bằng agent cũng là đưa dữ liệu ra ngoài máy. Chỉ dùng dữ liệu **tổng hợp** có tên rõ ràng là giả (vendor `ACME Test Foods`, `Fake Utility Co`; không mô phỏng người thật).
2. **Không mạng thật.** Test chỉ dùng mock cho LLM. Không gọi proxy `127.0.0.1:8045` trong test tự động. Không cài gói ngoài danh sách đã pin trong `requirements.txt` mà không báo Orchestrator.
3. **Không bao giờ in, log hoặc đưa vào exception** nội dung vault, text OCR, payload gửi LLM. Test phải khẳng định điều này.
4. **Quyền sở hữu file:** mỗi agent chỉ sửa các file được giao (kể cả test của nó). Cần đổi hợp đồng (type, chữ ký hàm, schema) thì **dừng và báo Orchestrator**, không tự sửa file của agent khác.
5. **Hợp đồng đã đóng băng ở Wave 0.** Không đổi chữ ký public đã đóng băng.
6. Mỗi agent chạy trong **worktree riêng** (`isolation: "worktree"`), nhánh riêng, commit trên nhánh đó. Không push, không merge; Orchestrator merge.
7. Code đọc như code xung quanh: ngắn, không abstraction thừa, không cấu hình cho giá trị cố định. Comment chỉ để giải thích "tại sao".
8. Ngôn ngữ: code, identifier, commit bằng tiếng Anh; tài liệu và thông báo cho người dùng bằng tiếng Việt.

### Hợp đồng báo cáo (mỗi sub-agent phải trả đúng mẫu này, ngắn)

```
AGENT: <tên>
BRANCH: <nhánh>
FILES: <danh sách file đã tạo/sửa>
TESTS: <lệnh pytest đã chạy> -> <số passed/failed, dán dòng tổng kết thật>
DEVIATIONS: <khác với PLAN.md hoặc hợp đồng, nếu có; "none" nếu không>
CONTRACT_REQUESTS: <cần đổi hợp đồng nào, nếu có>
RISKS: <rủi ro/giới hạn còn lại>
```

Báo cáo thiếu dòng TESTS với kết quả thật bị coi là chưa xong.

---

### Wave 0: Nền móng và hợp đồng (Orchestrator tự làm, tuần tự, **không** song song)

Làm trong nhánh `main` (repo hiện ở `master`; đổi tên hoặc dùng `master` nhất quán, đừng tạo hai nhánh chính).

1. `git` hygiene: ghi `.gitignore` theo PLAN.md mục 0.2 (merge với file `.gitignore` hiện có, đừng ghi đè). Commit khởi tạo gồm `PLAN.md` và file này.
2. Môi trường: `py -3.11 -m venv .venv`, cài các gói ở PLAN.md mục 0.1, chạy thử `import paddle, paddleocr, fitz, pillow_heif, cv2`. Ghi `requirements.txt` đã pin từ `pip freeze`. Nếu PaddleOCR cài lỗi, **vẫn tiếp tục**: đánh dấu `ocr_engine` là phụ thuộc môi trường, các module khác không phụ thuộc Paddle.
3. Khung dự án đúng cấu trúc PLAN.md mục 0.3, mỗi module là file có **chữ ký hàm/lớp, kiểu dữ liệu, docstring nêu hành vi và lỗi ném ra**, thân hàm `raise NotImplementedError`.
4. Kiểu dữ liệu dùng chung (đóng băng): `core/types.py` với `Word`, `Line`, `Page`, `Document`, `VaultEntry`, `Vault`, `Provenance`; `models/schema.py` với `LLMInvoice` và `CanonicalInvoice` đúng PLAN.md mục 4.3; `config.py` với mọi dung sai, ngưỡng, danh sách đơn vị, enum category, locale mặc định ngày.
5. Các module composer **do Orchestrator viết ngay ở Wave 0** (mỏng, chỉ gọi module con theo hợp đồng): `core/tokenizer.py` (gọi `tokenizer_specs`, `tokenizer_dates`, `tokenizer_numbers`, `vault`) và `core/redactor.py` (gọi `redactor_contact`, `redactor_address`). Mọi file module con có stub chữ ký và docstring. Hợp đồng liên module: hàm con nhận `str` và trả `str` đã thay cộng danh sách phát hiện; thứ tự áp dụng cố định: specs (đánh dấu vùng cần giữ), dates, numbers.
6. `tests/conftest.py`, thư mục `tests/fixtures/` và `samples_synthetic/` (rỗng, sẽ do agent fixtures điền).
7. Chạy `pytest --collect-only`, `python -c "import invoice_processor"` để chứng minh khung nhập được. Commit "contract freeze". Ghi tag `contract-v1`.

Tiêu chí qua Wave 0: import sạch, mọi stub có docstring, không file nào có logic ngoài kiểu dữ liệu và config.

---

### Wave 1: Module song song (spawn **cùng lúc** cả 31 agent dưới đây, tối đa 50 chạy đồng thời, phần còn lại xếp hàng)

Mỗi agent: đọc `PLAN.md` phần liên quan + `core/types.py` + stub của mình, hiện thực module, viết unit test đầy đủ theo bảng "Kiểm thử" của PLAN.md, chạy `pytest tests/test_<module>.py`, commit, báo cáo theo mẫu.

| Agent | Sở hữu file | Việc chính | Test bắt buộc |
|---|---|---|---|
| W1-numparse | `core/numparse.py`, `tests/test_numparse.py` | parse số theo PLAN 5.2: locale Mỹ/EU/VN, ngoặc âm, `-` cuối, `CR`, cờ thuế, mơ hồ, `Decimal` | ≥ 30 case gồm `1.234,56`, `(12.50)`, `12.50-`, `1,234` mơ hồ |
| W1-tok-numbers | `core/tokenizer_numbers.py`, `tests/test_tokenizer_numbers.py` | PLAN 3.3: mask mọi chuỗi chứa chữ số thành `<N_k>`/`<ID_k>`, token tuần tự xác định, gợi ý `neg`, định dạng tiền/qty/`2 @ 3.50`/cờ thuế | ≥ 25 case định dạng; thứ tự token ổn định giữa hai lần chạy |
| W1-tok-dates | `core/tokenizer_dates.py`, `tests/test_tokenizer_dates.py` | PLAN 3.3: nhận dạng và mask ngày thành `<D_k>` (`MM/DD/YYYY`, `DD.MM.YYYY`, `Aug 01, 2026`, `2026-08-01`, `01-Aug-26`) | ngày hợp lệ và không hợp lệ; không nuốt số tiền giống ngày |
| W1-tok-specs | `core/tokenizer_specs.py`, `tests/test_tokenizer_specs.py` | PLAN 3.4: nhận dạng số quy cách được giữ nguyên, khớp chặt, đơn vị lấy từ `config.py` | dương: `750ML`, `6X32 OZ`, `12-PACK`, `A4`; **âm: `2 lb`, `3 ea`, `1 case` phải KHÔNG được giữ** |
| W1-vault | `core/vault.py`, `tests/test_vault.py` | PLAN 3.6: `Vault` trong RAM, `clear()`, không `__repr__` lộ giá trị, không pickle, không vào exception | `repr`, `str`, `pickle`, traceback không chứa giá trị |
| W1-redact-contact | `core/redactor_contact.py`, `tests/test_redactor_contact.py` | PLAN 3.2: email, URL, SĐT (US/VN/quốc tế), số thẻ (`**** 1234`, `Visa ending 6411`), mã vạch dài | từng mẫu; không mask nhầm số quy cách |
| W1-redact-address | `core/redactor_address.py`, `tests/test_redactor_address.py` | PLAN 3.2: địa chỉ (số nhà + đường, bang + zip, Suite/Floor/Unit), tên người sau nhãn `Server/Cashier/Customer/Member/Name on card` | không mask nhầm tên hàng (`Smith's Butter`, `St. Louis Ribs`) |
| W1-leakguard | `core/leak_guard.py`, `tests/test_leak_guard.py` | PLAN 3.5 | nhồi số vào mọi định dạng, guard phải chặn; không in nội dung vi phạm |
| W1-layout-lines | `core/layout.py`, `tests/test_layout.py` | PLAN 2.3: gom dòng theo median chiều cao box, xử lý nghiêng còn sót | bbox tổng hợp: nghiêng, dòng gãy, hai trang |
| W1-layout-columns | `core/layout_columns.py`, `tests/test_layout_columns.py` | PLAN 2.4: phát hiện biên cột theo cụm X, chèn `|`, `col_idx` | bảng nhiều cột, hai cột song song, cột lệch dần |
| W1-imageloader | `core/ingestion.py` (phần ảnh và phân loại file), `tests/test_ingestion_image.py` | PLAN 1.1-1.2: magic bytes, Pillow, HEIC, `exif_transpose`, giới hạn kích thước và scale | HEIC nhỏ tự sinh có EXIF xoay; file hỏng; đuôi sai |
| W1-pdfrouter | `core/ingestion_pdf.py`, `tests/test_ingestion_pdf.py` | PLAN 1.3-1.4: 3 điều kiện text sạch, nhánh `pdf_text` ra `list[Word]`, nhánh render 300 DPI, gộp trang, bỏ header/footer lặp | PDF hỗn hợp, text-layer rác bị chuyển sang OCR |
| W1-ocr-preprocess | `core/ocr_preprocess.py`, `tests/test_ocr_preprocess.py` | PLAN 2.2: deskew cv2, CLAHE có điều kiện, cắt biên lai dài có chồng lấn và loại trùng | chỉ cần cv2, không cần Paddle; ảnh xoay 2° được thẳng lại |
| W1-ocr-engine | `core/ocr_engine.py`, `tests/test_ocr_engine.py` | PLAN 2.1, 2.5: wrapper Paddle v3 trả `list[Word]`, khởi tạo một lần, cờ confidence | `skipif` khi thiếu Paddle; test mapping kết quả bằng đối tượng giả |
| W1-llm-client | `core/llm_parser.py`, `tests/test_llm_parser.py` | PLAN 4.1: client OpenAI-compatible, `temperature=0`, JSON mode, retry/backoff, timeout, giới hạn song song | **mock hoàn toàn**: JSON hỏng, timeout, 429, phản hồi chứa số thật; token không bị log |
| W1-llm-cache | `core/llm_cache.py`, `tests/test_llm_cache.py` | PLAN 4.1: cache theo `sha256(payload mask + PROMPT_VERSION + schema version)`, ghi nguyên tử | trúng/trượt cache, đổi phiên bản prompt làm mất cache, file cache hỏng không làm sập |
| W1-prompt | `core/prompt.py`, `tests/test_prompt.py` | PLAN 4.2: prompt, few-shot ẩn danh (cả tiện ích và discount), `PROMPT_VERSION` | prompt không chứa chữ số nào ngoài token; snapshot test |
| W1-rehydrator | `core/rehydrator.py`, `tests/test_rehydrator.py` | PLAN 5.1, 5.3: kiểm tra token (tồn tại, không trùng, coverage, số thật trong `_ref`), rehydrate, provenance, ngày | token ma/trùng/bỏ rơi; ngày mơ hồ |
| W1-val-lines | `core/validator_lines.py`, `tests/test_validator_lines.py` | PLAN 5.4 tầng 1 và 2: dòng (dung sai `0.01 + 0.005×|qty|`), tổng dòng | hàng cân, discount, dòng không kiểm tra được, thiếu subtotal |
| W1-val-totals | `core/validator_totals.py`, `tests/test_validator_totals.py` | PLAN 5.4 tầng 3 và 4 và kiểm tra bổ sung: tổng hóa đơn, tiện ích, nhiều thuế, due_date, ngày trong tháng | tiện ích có previous balance/payments, credit memo, nhiều dòng thuế |
| W1-val-status | `core/validator.py`, `tests/test_validator.py` | PLAN 5.5: gom kết quả hai module trên và các cờ rehydrator thành `VERIFIED/REVIEW_NEEDED/FAILED` | **không bao giờ VERIFIED khi thiếu kiểm tra**; `low_conf`, `ambiguous_*`, `multi_invoice_suspected` đều chặn VERIFIED |
| W1-jsonl | `exporters/jsonl_exporter.py`, `tests/test_jsonl_exporter.py` | PLAN 6.1: append + flush, Decimal dạng chuỗi, `failures.jsonl` | đọc lại khớp; crash giữa chừng không mất dòng cũ |
| W1-excel-sheets | `exporters/excel_exporter.py`, `tests/test_excel_exporter.py` | PLAN 6.2: 4 sheet, `number_format`, tên file theo `--month`; gọi hàm của `excel_safety` theo hợp đồng | mở lại bằng openpyxl đúng số liệu; Sheet 3 có đủ lý do |
| W1-excel-safety | `exporters/excel_safety.py`, `tests/test_excel_safety.py` | PLAN 6.2: chống formula injection (`= + - @`, tab, CR), atomic write qua file tạm | mọi tiền tố nguy hiểm bị vô hiệu; ghi dở không để lại file hỏng |
| W1-dedup | `core/dedup.py`, `tests/test_dedup.py` | PLAN 6.3 | trùng sha256, trùng vendor+no+total, vendor viết khác nhẹ |
| W1-fx-pdf | `tests/fixtures/pdf/`, `tests/make_fixtures_pdf.py` | sinh hóa đơn **giả** dạng PDF text kèm `.truth.json`: hàng hóa nhiều trang, tiện ích, credit memo, bán cân, discount, nhiều thuế | seed cố định, sinh lại được, xác định |
| W1-fx-scan | `tests/fixtures/scan/`, `tests/make_fixtures_scan.py` | sinh PDF scan (ảnh), PDF text-layer rác, trang hỗn hợp, kèm `.truth.json` | như trên |
| W1-fx-thermal | `tests/fixtures/image/`, `tests/make_fixtures_image.py` | sinh ảnh giấy nhiệt giả lập (khổ hẹp, nhiễu, nghiêng, mờ) và HEIC xoay EXIF, kèm `.truth.json` | như trên |
| W1-atk-privacy | `tests/attacks/test_leak_attacks.py` | viết test tấn công rò rỉ **theo hợp đồng** (tokenizer, redactor, leak guard, prompt, log): nhồi số/ngày/PII kiểu lạ, Unicode số (số Ả Rập-Ấn, fullwidth), chữ số bị tách bằng khoảng trắng/ký tự vô hình; chạy được sau khi các module đã merge | không cần xanh ngay; báo cáo danh sách tấn công và test nào cần module nào |
| W1-atk-money | `tests/attacks/test_money_attacks.py` | test tấn công tính tiền: float lẻn vào, làm tròn biên, dấu âm, locale đảo, qty âm, tổng bằng 0, chia cho 0 | như trên |
| W1-atk-llm | `tests/attacks/test_llm_attacks.py` | test coi LLM là đối thủ: trả số thật, token ma/trùng/bỏ rơi, đảo vai trò qty/price, JSON lồng sâu, trường thừa, chuỗi cực dài, prompt injection nằm trong tên hàng | như trên |

Quy tắc phụ thuộc: các agent Wave 1 **không** import code của nhau ngoài `core/types.py`, `models/schema.py`, `config.py` (đã đóng băng). Chỗ cần module khác thì dùng dữ liệu inline hoặc mock theo hợp đồng.

**Cổng Wave 1 (Orchestrator làm, từng nhánh):**
1. Đọc báo cáo, đối chiếu `git diff --stat`: agent không được sửa file ngoài danh sách sở hữu. Vi phạm thì trả lại.
2. Tự chạy lại `pytest` của module trong worktree đó. Không khớp báo cáo thì trả lại.
3. Merge vào `main` theo thứ tự phụ thuộc: numparse, vault, tok-*, redact-*, leakguard, layout-* → ingestion, ocr-*, llm-*, prompt → rehydrator, val-lines, val-totals, val-status → exporters, dedup, fixtures → cuối cùng gộp `tests/attacks/` và chạy toàn bộ tấn công; test tấn công thất bại là phát hiện cần sửa, giao cho agent sở hữu module liên quan. Sau **mỗi** merge chạy toàn bộ `pytest`. Xung đột không được xảy ra (file sở hữu tách biệt); nếu xảy ra, điều tra nguyên nhân (agent đã sửa file không được phép) trước khi giải quyết.
4. Xử lý `CONTRACT_REQUESTS`: gom lại, quyết định một lần, nếu đổi hợp đồng thì tăng tag `contract-v2` và thông báo agent bị ảnh hưởng bằng task sửa nhỏ.

---

### Wave 2: Tích hợp (song song theo cặp, sau khi Wave 1 đã merge sạch)

| Agent | Sở hữu | Việc |
|---|---|---|
| W2-pipeline | `core/pipeline.py`, `tests/test_pipeline.py` | nối: ingestion → (OCR) → layout → redactor → tokenizer → leak_guard → prompt → llm → rehydrator → validator; cô lập lỗi theo file; trả `CanonicalInvoice` hoặc `FAILED`; resume bằng cache; vault bị `clear()` trong `finally` |
| W2-cli | `main.py`, `tests/test_cli.py` | PLAN 6.4: tham số `--month --out --only --workers --no-cache --dry-run`, tqdm, tổng kết, **`--dry-run` in payload sau Leak Guard rồi dừng, không gọi LLM** |
| W2-e2e | `tests/test_e2e.py` | chạy pipeline với LLM **mock xác định** trên toàn bộ fixture tổng hợp, so với `.truth.json`: trường số khớp, status đúng kỳ vọng (fixture có chủ ý sai phải ra `REVIEW_NEEDED`) |

W2-pipeline làm trước; W2-cli và W2-e2e chạy song song sau khi pipeline đã merge. Cổng giống Wave 1.

Tiêu chí qua Wave 2: `pytest` toàn bộ xanh; `python main.py samples_synthetic --month 2026-08 --dry-run` in payload không chứa số; chạy thật với LLM mock tạo đủ `invoices.jsonl`, `failures.jsonl`, `Summary_2026-08.xlsx`.

---

### Wave 3: Phản biện song song (spawn cả 12 reviewer cùng lúc; mỗi agent **chỉ đọc**, không sửa code, trả danh sách phát hiện có bằng chứng tái hiện)

Mỗi reviewer nhận code hiện tại và `PLAN.md`, **không** nhận kết luận của người khác (tránh neo). Mỗi phát hiện phải kèm: file:dòng, kịch bản tái hiện cụ thể (đầu vào → kết quả sai), mức độ.

| Reviewer | Góc nhìn |
|---|---|
| R-privacy-text | Red team rò rỉ ở tầng văn bản: tokenizer, redactor, leak guard; Unicode số, chữ số bị tách, định dạng lạ, PII sót |
| R-privacy-egress | Red team rò rỉ ở đường ra: prompt/few-shot, log, exception, traceback, cache, `--dry-run`, tên file nguồn đi vào payload, biến môi trường |
| R-money-parse | Lỗi tính tiền ở `numparse` và `rehydrator`: locale, dấu âm, làm tròn, `float` lẻn vào, ngày mơ hồ |
| R-money-validate | Lỗi ở `validator_*`: dung sai, đường dẫn dẫn tới `VERIFIED` sai, thiếu kiểm tra mà vẫn đạt |
| R-llm-trust | Coi LLM là đối thủ: số thật, token ma, trùng, bỏ rơi, đảo vai trò, prompt injection trong tên hàng |
| R-security | Formula injection Excel, path traversal tên file, đọc `.env`, log secret, file tạm, PDF/ảnh độc hại, giới hạn kích thước (bom giải nén, ảnh khổng lồ) |
| R-ocr-layout | Bố cục: dòng gãy, biên lai dài, bảng nhiều cột, hai cột song song, header/footer lặp |
| R-ingestion | Magic bytes, HEIC/EXIF, PDF nhiều trang, text-layer rác, trang xoay, bộ nhớ |
| R-reliability | Batch: file hỏng làm chết cả lượt, resume, ghi file nửa chừng, rò tài nguyên, đa luồng, crash giữa chừng |
| R-exports | JSONL/Excel: dữ liệu mất, sai kiểu, atomic write, dedup, Sheet cảnh báo thiếu lý do |
| R-simplicity | Code thừa, abstraction không cần, trùng lặp, chỗ nào xóa được; so khớp với phong cách code xung quanh |
| R-plan-conformance | Đối chiếu từng mục `PLAN.md` với code, liệt kê mục chưa làm hoặc làm lệch |

**Phân loại phát hiện (Orchestrator làm):** loại bỏ trùng lặp, tái hiện từng phát hiện bậc cao bằng test thất bại. Phát hiện không tái hiện được thì bỏ. Chỉ giữ cái có bằng chứng.

**Sửa lỗi:** với mỗi nhóm phát hiện đã xác nhận, spawn **agent sửa** trong worktree riêng, mỗi agent một nhóm file không giao nhau, bắt buộc có test thất bại → xanh. Chạy song song theo nhóm file. Sau sửa chạy lại **chỉ reviewer bị ảnh hưởng** (R-privacy luôn chạy lại) để xác nhận đã vá và không vỡ chỗ khác. Lặp tối đa 3 vòng; còn phát hiện bậc cao sau 3 vòng thì dừng và báo người dùng.

---

### Wave 4: Hoàn thiện và bàn giao (Orchestrator)

1. Chạy toàn bộ `pytest` (báo số liệu thật), chạy lại e2e tổng hợp, chạy `--dry-run` và đọc ngẫu nhiên 5 payload để xác nhận không có số.
2. `README.md` ngắn: cài đặt, chạy `--only`, `--dry-run`, chạy batch, ý nghĩa status, cấu trúc output, checklist pháp lý của PLAN.md mục 0.
3. Cập nhật `PLAN.md` mục "Rủi ro còn lại" bằng thực tế sau build.
4. Tag `v0.1`. **Không push** lên remote trừ khi người dùng yêu cầu.

### Quy tắc điều phối chung

- Ưu tiên spawn nhiều agent trong **một** lượt gọi để chúng chạy đồng thời; không spawn tuần tự những việc độc lập.
- Mỗi prompt sub-agent phải **tự đủ**: chép ràng buộc cứng, mẫu báo cáo, danh sách file sở hữu, đường dẫn tài liệu cần đọc, tiêu chí xong. Sub-agent không thấy hội thoại này.
- Không đưa kết luận của agent này làm đầu vào cho reviewer của nó.
- Agent kẹt hoặc báo `CONTRACT_REQUESTS`: xử lý một lần cho cả nhóm, không để nhiều agent tự đoán khác nhau.
- Không tuyên bố "xong" khi chưa tự chạy lại test. Báo cáo cuối cho người dùng gồm: kết quả `pytest` thật, cái đã làm, cái chưa làm, rủi ro, danh sách việc con người phải làm ở trên.
- Báo cáo cuối do AI tạo, ghi rõ để người dùng review trước khi dùng cho quyết định tài chính.

## HẾT PROMPT
