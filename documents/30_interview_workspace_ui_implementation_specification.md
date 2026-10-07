# 30. Interview Workspace — UI Implementation Specification

## 1. Thông tin và mục đích

| Thuộc tính | Giá trị |
| --- | --- |
| Dự án | Interview-assistance / ClawCV — Phase 2 Mini Tool |
| Phiên bản | 1.0 |
| Ngày | 2026-10-06 |
| Loại tài liệu | Specification giao diện và hướng dẫn triển khai cho Codex |
| Concept | Interview Workspace — không gian xử lý theo từng hồ sơ |
| Người dùng chính | HĐCM / điều phối viên có Committee session |
| Phạm vi | Flow JD/CV → sinh câu hỏi → xuất Excel → nhập Excel → AI đánh giá |
| Trạng thái | Sẵn sàng làm đầu vào triển khai UI; các khác biệt contract phải được kiểm tra tại repository |
| Kết quả cần bàn giao | UI thật tích hợp API hiện có, các trạng thái lỗi/khôi phục, kiểm thử và hướng dẫn vận hành |

Tài liệu chuyển concept UI đã trao đổi thành yêu cầu triển khai cụ thể. Codex phải tạo giao diện có thể vận hành bằng dữ liệu backend, không chỉ tạo ảnh hoặc một mockup với các nút giả lập thành công.

Specification này chốt cách trình bày và tương tác UI. Nó không tự sửa migration, giới hạn Excel, schema AI, prompt hoặc quy tắc state machine của backend. Người dùng đã yêu cầu tạo specification để triển khai; không cần hỏi lại các lựa chọn thẩm mỹ đã quy định ở đây.

## 2. Tài liệu nguồn và cách xử lý khác biệt

### 2.1. Đầu vào cần đọc

Tên bên dưới là tên gốc trong repository; tìm theo tên nếu thư mục thực tế khác.

| Tài liệu | Vai trò |
| --- | --- |
| `2026-10-05-excel-question-answer-flow-design.md` | Phạm vi active, Excel contract, snapshot bất biến, evaluation v2 |
| `2026-10-05-excel-question-answer-flow.md` | API binary, snapshot service, refined flow và kế hoạch tích hợp |
| `prompt-statistics.md` | Prompt active/legacy và phân nhóm câu hỏi đang được mô tả |
| `2026-10-05-gemini-provider-integration-design.md` | Ranh giới Gemini, secret phía backend, task bất đồng bộ |
| `18_phase2_supervised_interview_technology_specification.md` | Python Standard Library, HTML/CSS/Vanilla JS, localhost |
| `20_domain_and_database_specification.md` | Entity, version, snapshot và lifecycle dữ liệu nền |
| `21_workflow_state_machine.md` | Transition, retry và recovery nền; đối chiếu refined flow |
| `22_ai_assessment_specification.md` | Rubric, evidence, confidence; evaluation v2 thay phần live/brief |
| `23_api_contract_specification.md` | API nền, envelope, auth, lỗi và idempotency |
| `24_frontend_ui_specification.md` | Accessibility, rendering an toàn và các chức năng nền |
| `25_security_and_audit_specification.md` | Committee session, bảo vệ secret, audit, dữ liệu nhạy cảm |
| `26_document_processing_specification.md` | Import JD/CV, PDF fallback và xác nhận văn bản |
| `27_test_and_acceptance_specification.md` | Acceptance và hồi quy |
| `28_implementation_task_breakdown.md` | Quy tắc batch, test và checkpoint |

### 2.2. Quy tắc ưu tiên

1. Flow Excel bổ sung xác định phạm vi active của UI mới. Không khôi phục Candidate Mode, Interview Brief, Live Interview hoặc Final Evaluation vào navigation.
2. Technology Specification xác định runtime. Không chuyển sang WPF, React, Vue hoặc thêm build pipeline.
3. Tài liệu này xác định layout, token, component, copy, interaction và acceptance của UI mới.
4. Payload và endpoint phải khớp implementation đã kiểm chứng và contract đã được áp dụng. Sai khác giữa code và tài liệu phải ghi trong báo cáo tích hợp; không âm thầm coi code sai là contract mới.
5. Concept tương tác trước đó chỉ là minh họa bố cục. Số liệu, kết quả, thao tác xác nhận và thông báo giả lập của concept không phải logic production.

### 2.3. Conflict C-01 — số lượng và phân nhóm câu hỏi

Hiện tồn tại hai mô tả:

- Excel design và contract nền: 5–8 câu, thứ tự 1–8, thời lượng 600–900 giây.
- Bảng prompt: đúng 9 câu, gồm 3 `FOUNDATION`, 4 `APPLICATION`, 2 `DEEP_DIVE`; bổ sung `questionCategory` và `nextStepObjective`.

Quy tắc UI bắt buộc:

- Render `N = questions.length`, không hardcode 8 hoặc 9 ở tiêu đề, progress, counter hay layout.
- Render nhóm theo `questionCategory` chỉ khi backend thực sự trả trường này. Không tự gán nhóm theo thứ tự câu hoặc suy đoán từ nội dung.
- Nếu không có category, dùng danh sách phẳng đánh số; bỏ dòng tỷ lệ 3/4/2.
- `nextStepObjective`, nếu có, được hiển thị riêng với `purpose`; không tự đồng nhất hai trường.
- Request sinh câu hỏi và thao tác export/import tuân theo policy được backend hỗ trợ và contract đã áp dụng. Không tự sửa parser Excel, prompt hoặc migration để hợp thức hóa 9 câu.
- Nếu backend sinh 9 câu nhưng Excel contract vẫn giới hạn 8, giữ dữ liệu để review, hiển thị lỗi tương thích và chặn thao tác không hợp lệ. Không cắt câu, đổi ID, thêm cột Excel hoặc giả báo xuất thành công.
- Codex ghi rõ kết quả kiểm tra C-01. Có thể hoàn thành shell, component và các luồng hợp lệ độc lập; không cần dừng toàn bộ công việc UI.

### 2.4. Conflict C-02 — dữ liệu lịch sử

Plan hiện nêu endpoint đọc kết quả AI current và đọc snapshot theo ID, chưa chốt API liệt kê mọi version.

- Version selector chỉ xuất hiện nếu API hiện có cung cấp các version và nội dung tương ứng.
- Nếu chỉ có current result, hiển thị nhãn version và một kết quả; không tạo selector giả.
- Không tự bổ sung endpoint history, không tải SQLite trực tiếp từ frontend.
- Dữ liệu legacy còn được bảo toàn ở backend; không đưa navigation workflow cũ trở lại chỉ để xem lịch sử.

## 3. Phạm vi sản phẩm

### 3.1. Bao gồm

- Committee unlock/session theo cơ chế hiện có.
- Danh sách hồ sơ, tạo hồ sơ và mở đúng bước xử lý.
- Nhập JD/CV bằng file hoặc văn bản; xem extracted text và trạng thái xác nhận.
- Sinh câu hỏi bất đồng bộ; review bộ câu hỏi, purpose, expected evidence và rubric.
- Xuất `.xlsx` theo canonical contract từ backend.
- Chọn và nhập `.xlsx` đã trả lời, đọc snapshot backend tạo.
- Yêu cầu đánh giá AI riêng sau import; polling và kết quả v2 chỉ đọc.
- Xem answer gốc cạnh reasoning/evidence; hiển thị confidence và limitations.
- Settings an toàn và backup/export theo API đã có.
- Loading, empty, validation, disabled, error, retry, immutable và mất kết nối.

### 3.2. Ngoài phạm vi UI active

- Trang làm bài cho ứng viên, timer, autosave answer trên trình duyệt, check-in.
- Interview Brief, câu hỏi follow-up, workspace live interview, nút chốt PASS/FAIL.
- SSO, tài khoản doanh nghiệp, gửi email, lịch đồng bộ, tích hợp AMIS.
- Structured CV parser của recruitment system khác, OCR hoặc gửi file gốc sang Gemini.
- Dashboard KPI tuyển dụng, tổng điểm tuyển dụng tự tính, bảng xếp hạng ứng viên.
- Inline editing answer hoặc snapshot đã import; sửa kết quả AI tại chỗ.

## 4. Nguyên tắc trải nghiệm

| ID | Nguyên tắc | Yêu cầu |
| --- | --- | --- |
| UX-01 | Một workspace cho một case | Giữ candidate code, vị trí và target level ở header trong bốn bước |
| UX-02 | Hành động tiếp theo rõ ràng | Mỗi vùng thao tác có một CTA chính; giải thích điều kiện chưa đủ |
| UX-03 | Thông tin có lớp | Câu hỏi/câu trả lời ưu tiên; rubric, technical metadata mở theo nhu cầu |
| UX-04 | Evidence trước kết luận | Reasoning và evidence gắn với câu trả lời; không biến confidence thành độ phù hợp tuyển dụng |
| UX-05 | Backend quyết định trạng thái | UI refetch sau mutation; không tự ghi trạng thái thành công |
| UX-06 | Version có nguồn gốc | Kết quả luôn gắn case, snapshot và question set tương ứng |
| UX-07 | Lỗi không làm mất việc | Giữ draft chưa gửi trong memory, không xóa snapshot/result đã có |
| UX-08 | Đọc tốt trên desktop | Tối ưu 1280–1440 px; reflow trên màn nhỏ, không thu nhỏ chữ để ép layout |

Ngôn ngữ mặc định: tiếng Việt. Giữ nguyên thuật ngữ cần thiết như JD, CV, Gemini, rubric. Tránh hiển thị raw enum làm nhãn chính. Những enum chưa biết phải có nhãn an toàn và chặn action phụ thuộc, không suy đoán quyền thao tác.

## 0A. Approved active assessment bridge

This addendum supersedes the earlier Excel-only wording for the active assessment bridge. The implemented primary flow is:

`Question Set approved on machine B -> export candidate-html.v1 -> candidate works offline on machine A -> response HTML downloaded -> machine B imports response -> immutable snapshot -> AI evaluation.`

Machine B remains localhost-only. Machine A does not connect to the app, does not receive a token or internal data, and only opens the self-contained file. Excel export/import remains the visible operational fallback. The accepted protection target is ordinary operational errors rather than deliberate tampering.

## 5. Visual design system

### 5.1. Phong cách

Giao diện làm việc chuyên nghiệp, nền trung tính sáng, điểm nhấn indigo, ít hiệu ứng. Tránh gradient lớn, glassmorphism, mascot, banner trang trí hoặc thẻ KPI không phục vụ thao tác. Không đưa illustration vào vùng đọc dữ liệu.

Light theme là baseline cần hoàn thành. Không thêm dark theme toggle trong batch đầu. Nếu ứng dụng có sẵn dark theme, giữ cơ chế và bổ sung token tương ứng; không hardcode light color trong component dùng chung.

### 5.2. Color tokens

| Token CSS | Giá trị baseline | Công dụng |
| --- | --- | --- |
| `--ui-bg` | `#F5F6F9` | Nền workspace |
| `--ui-surface` | `#FFFFFF` | Sidebar, card, dialog |
| `--ui-text` | `#202338` | Nội dung chính |
| `--ui-muted` | `#666D80` | Nội dung phụ |
| `--ui-border` | `#E5E7EE` | Divider/border trung tính |
| `--ui-primary` | `#6250C4` | CTA và selected state |
| `--ui-primary-hover` | `#5141A7` | Hover CTA |
| `--ui-primary-text` | `#FFFFFF` | Chữ trên CTA |
| `--ui-primary-soft` | `#F0EDFC` | Tab/list item được chọn |
| `--ui-success` / `--ui-success-soft` | `#22664E` / `#EAF6EF` | Hoàn thành/xác nhận |
| `--ui-warning` / `--ui-warning-soft` | `#8B5A13` / `#FFF5E5` | Chờ xử lý/thiếu dữ liệu |
| `--ui-danger` / `--ui-danger-soft` | `#B42318` / `#FEF3F2` | Lỗi/mâu thuẫn cần chú ý |
| `--ui-focus` | `#6250C4` | Focus ring |

Không chỉ dùng màu để phân biệt trạng thái. Mỗi badge có text, ví dụ “Đang xử lý”, “Chờ xác nhận”, “Nhập thất bại”.

### 5.3. Typography, spacing và kích thước

- Font: `"Segoe UI", Arial, sans-serif`; không tải font qua CDN khi runtime.
- Base: 14 px, line-height 1.55; nội dung đọc dài 15–16 px.
- Page title: 26 px/600; section title: 18 px/600; label: 13–14 px/500.
- Metadata: 12 px; không dùng chữ dưới 12 px cho thông tin cần đọc.
- Spacing scale: 4, 8, 12, 16, 20, 24, 32 px.
- Page padding: 24–32 px desktop, 16 px mobile.
- Card radius: 12 px; input/button radius: 8 px; badge radius: 6 px.
- Input/button height tối thiểu 40 px desktop, touch target tối thiểu 44 px mobile.
- Divider 1 px; không dùng shadow đậm trên mọi card. Dialog được phép shadow nhẹ.
- Icon 16–20 px với label. Dùng asset local có sẵn hoặc SVG nội bộ; không thêm icon package/CDN runtime.
- CTA có icon phụ trợ khi phù hợp; nút icon-only phải có accessible name.

## 6. Application shell và responsive

### 6.1. Desktop shell

- Sidebar rộng 200 px, chứa brand `ClawCV / Interview Assistant`.
- Navigation chính: “Hồ sơ phỏng vấn”, “Cấu hình”, “Sao lưu”.
- Cuối sidebar: “Không gian HĐCM”, trạng thái session và nút “Khóa phiên”. Không hiển thị account giả.
- Topbar cao khoảng 56 px: breadcrumb bên trái; trạng thái kết nối an toàn bên phải.
- Main content chiếm phần còn lại, max-width 1280 px, không ép thành một cột hẹp ở giữa màn hình.
- Case header: candidate code, tên ứng viên, vị trí, target level và badge workflow.
- Case navigation có bốn step/tab: “1. JD & CV”, “2. Bộ câu hỏi”, “3. Câu trả lời”, “4. Đánh giá AI”.

### 6.2. Responsive rules

| Viewport | Quy tắc |
| --- | --- |
| ≥1200 px | Sidebar đầy đủ; documents hai cột; questions master/detail; answer và reasoning hai cột |
| 900–1199 px | Sidebar có thể giảm còn 176 px; list câu hỏi rộng 240 px; giảm padding |
| 600–899 px | Navigation chính lên hàng trên hoặc drawer; columns xếp dọc khi nội dung không đủ chỗ |
| <600 px | Một cột; stepper chia hai hàng; list thành cards; CTA full width khi cần |

Không dùng fixed viewport height cho toàn trang. Không tạo hai vùng scroll dọc lồng nhau để đọc cùng một answer. Bảng chỉ scroll ngang trong container nếu không có cách reflow phù hợp. Nội dung dài phải wrap; filename, UUID và hash không được làm tràn page.

### 6.3. Stepper behavior

- Step đang xem có selected state; bước đã đủ dữ liệu có nhãn/icon hoàn thành.
- Có thể mở bước trước để xem dữ liệu. Không dùng việc đổi tab để tự thực hiện transition.
- Bước chưa có dữ liệu có empty state giải thích prerequisite, thay vì chỉ trả trang trắng.
- Khi mở case lần đầu, chọn bước cần hành động kế tiếp theo backend state. Nếu URL chỉ định bước hợp lệ, giữ bước đó.
- Không tự điều hướng khi user đang nhập draft. Khi AI xong ở tab khác, thông báo và cho nút “Xem kết quả”.

## 7. Route map

Đây là route UI, không phải endpoint REST. Giữ router native đang có; nếu repository dùng hash routing thì map logical path dưới đây qua hash. Không thêm router package.

| Logical route | Màn hình | Quyền / điều kiện |
| --- | --- | --- |
| `/cases` | Danh sách hồ sơ | Committee session |
| `/cases/new` | Tạo hồ sơ | Committee session |
| `/cases/:caseId` | Redirect tới bước phù hợp | Case tồn tại, Committee session |
| `/cases/:caseId/documents` | JD & CV | Committee session |
| `/cases/:caseId/questions` | Sinh/review/xuất câu hỏi | Committee session |
| `/cases/:caseId/answers` | Import và xem answer snapshot | Committee session |
| `/cases/:caseId/ai` | Task/kết quả AI v2 | Committee session |
| `/settings` | Cấu hình an toàn | Committee session |
| `/backups` | Backup/export | Committee session |

Refresh phải tải lại được case và server state. Nếu History API đang được dùng, kiểm tra server fallback cho UI routes. Không sửa backend router nếu chưa cần; giữ routing hiện có là ưu tiên.

## 8. Specification từng màn hình

### S-01. Committee unlock

- Dùng cơ chế PIN và session hiện có. Codex phải đọc implementation bootstrap/auth trước khi nối UI; tài liệu này không đặt endpoint unlock mới.
- Form có label “PIN HĐCM”, input password, nút “Mở phiên làm việc”, lỗi an toàn và trạng thái submitting.
- PIN không autofill bằng dữ liệu mẫu, không lưu trong storage/URL/log.
- Khi session hết hạn: giữ vị trí case/step không nhạy cảm trong memory, khóa nội dung và yêu cầu mở phiên lại. Không tự retry mutation sau unlock.
- Nút “Khóa phiên” gọi cơ chế revoke/lock hiện có và xóa capability khỏi memory. Nếu backend chưa hỗ trợ revoke, ghi dependency; không giả báo đã khóa session server.

### S-02. Danh sách hồ sơ — `/cases`

**Mục tiêu:** nhìn được hồ sơ cần xử lý và mở tiếp đúng bước.

- Header: “Hồ sơ phỏng vấn”; CTA “Tạo hồ sơ”.
- Bảng có cột: Ứng viên/mã; Vị trí/level; Lịch phỏng vấn nếu có; Trạng thái; Bước tiếp theo.
- Primary row action “Mở hồ sơ”; row link vào bước phù hợp, không mở dialog nội dung lớn.
- Dùng pagination backend; không tải toàn bộ database để giả lập search toàn hệ thống.
- Filter trạng thái dùng các giá trị backend hỗ trợ. Nếu list API chưa hỗ trợ refined status filter, không gửi enum mới vào filter legacy.
- Search dùng query được API hỗ trợ. Nếu chỉ lọc client trên dữ liệu trang đã tải, label rõ “Tìm trong trang hiện tại”.
- Empty state: “Chưa có hồ sơ phỏng vấn” + “Tạo hồ sơ đầu tiên”.
- Loading: skeleton table; error: banner + “Tải lại”, giữ filter.
- Delete nằm trong secondary menu nếu API có sẵn; dialog nêu candidate code, yêu cầu lý do và backup theo backend rule. Không đặt nút xóa cạnh CTA chính.
- Hồ sơ legacy không có refined state không được tự đưa vào flow mới bằng thay đổi trạng thái client; hiển thị cảnh báo tương thích nếu chưa có backend mapping.

### S-03. Tạo hồ sơ — `/cases/new`

Form hai cột desktop, một cột mobile.

| Field | Behavior |
| --- | --- |
| Ứng viên | Chọn Candidate đã có hoặc tạo từ candidate code + full name |
| Vị trí | Chọn Job đã có hoặc tạo từ position title + target level |
| Lịch phỏng vấn | Optional theo API/domain hiện có; datetime-local chuyển sang UTC khi gửi |
| Thời lượng dự kiến | Default 900 giây nếu contract vẫn áp dụng; UI hiển thị phút, gửi giây |
| Thành viên HĐCM | Chỉ hiển thị nếu API hiện có hỗ trợ; tối đa một LEAD theo contract |

- Không yêu cầu email, số điện thoại hoặc ảnh nếu không thuộc domain đã chốt.
- Các policy legacy bắt buộc trong POST được điền từ default hợp lệ đã có; không đưa timer/auto-submit thành cấu hình Candidate Mode active.
- CTA “Tạo hồ sơ và thêm JD/CV”; secondary “Hủy”.
- Tạo Candidate/Job/Case là các thao tác tuần tự nếu chưa có aggregate endpoint. Lưu ID response để retry phần còn thiếu; không tạo lại Candidate/Job đã thành công khi Case thất bại.
- Form validation có inline error; duplicate candidate code phải cho chọn record hiện có, không tạo code mới âm thầm.
- Chỉ điều hướng khi server trả case ID thật.

### S-04. JD & CV — `/cases/:caseId/documents`

Hai card tương đương: “Mô tả công việc” và “CV ứng viên”.

Mỗi card có:

- File/text mode với label “Chọn file” và “Dán văn bản”.
- File name, format, size, version, trạng thái extraction và confirmation.
- Extracted text dạng plain text trong panel đọc được; nút mở rộng khi nội dung dài.
- Action “Nhập tài liệu”, “Xác nhận nội dung”, “Thay bằng phiên bản mới” tùy server state.
- Technical metadata như hash nằm trong details, không chiếm header hoặc lộ absolute path.

Format: TXT, Markdown, DOCX; PDF chỉ dùng extractor được backend cấu hình hoặc fallback dán text. DOC, DOCM và PDF scan không được UI hứa hẹn hỗ trợ/OCR. Không dùng browser Office viewer để mở file.

Backend document specification nêu file decoded tối đa 7.5 MiB và upload body tối đa 10 MiB. Codex kiểm tra giới hạn thực tế của document route: route upload phải khác giới hạn JSON thường 1 MiB. UI precheck theo limit được xác minh, backend vẫn là validation cuối. Nếu route thực tế mâu thuẫn, báo dependency; không tự tăng limit.

Manual text phải xem và confirm. PDF extraction thành công có thể đã auto-confirm: hiển thị “Đã xác nhận tự động” khi response thể hiện điều đó; không buộc gọi confirm lần nữa.

CTA “Sinh câu hỏi” enabled khi JD/CV hiện hành đủ điều kiện AI và policy hợp lệ. Disable phải có lý do đọc được: “Cần xác nhận nội dung CV”. Sau confirm refetch document/case trước khi enable.

Replace tài liệu tạo version mới, không sửa snapshot đã dùng. Nếu thay đổi ảnh hưởng Question Set hiện tại, UI nêu rõ bộ câu hỏi đang dựa trên version nào; chỉ backend quyết định cần regenerate/chặn transition.

### S-05. Bộ câu hỏi — `/cases/:caseId/questions`

**Header:** “Bộ câu hỏi chuyên môn”; N câu thực tế; version; thời lượng dự kiến nếu được trả; CTA phụ thuộc trạng thái.

**Empty / generation:**

- Chưa có Question Set: CTA “Sinh câu hỏi bằng AI”.
- Running: panel task “Đang sinh câu hỏi”, thời gian đã chờ, trạng thái; không giả % tiến độ.
- Failed: lỗi an toàn, “Thử lại” khi cho phép và “Tạo câu hỏi thủ công” nếu service/API hiện có hỗ trợ.
- Thiếu AI configuration: hiển thị hướng dẫn cấu hình an toàn; giữ thao tác thủ công đã có.

**Review layout:**

- Master list rộng 260–300 px desktop; panel chi tiết phần còn lại.
- List item có display order, tiêu đề ngắn/nội dung tóm tắt, trạng thái selected. Nội dung đầy đủ trong detail.
- Group theo category nếu thực sự có; count được tính từ dữ liệu, không ép cơ cấu 3/4/2.
- Detail: nội dung câu hỏi, competency, source, type/difficulty, purpose, nextStepObjective nếu có, expected evidence, required và estimated seconds nếu có.
- Rubric 0–4 nằm trong accordion “Tiêu chí chấm 0–4”. Không hiển thị JSON raw làm giao diện chính.
- Source label phản ánh field thực tế; không đổi `AI` thành “JD + CV” nếu backend không có provenance chi tiết.

**Edit:** dùng PATCH hiện có cho GENERATED/DRAFT nếu được phép. Form edit có Save/Cancel; không autosave mutation theo mỗi phím. Add/delete/reorder chỉ xuất hiện khi backend cho phép và vẫn giữ ID/version rule. Khi set khóa, hiển thị chỉ đọc và giải thích. Không thêm mandatory approval/check-in vào flow Excel; export GENERATED hoặc APPROVED theo contract hiện tại.

**Export:**

- CTA chính “Xuất Excel” khi set hợp lệ và đủ prerequisites.
- POST export qua binary helper; chỉ báo thành công sau HTTP success và nhận body xlsx hợp lệ về MIME/size cơ bản.
- Tạo Blob URL và anchor download với safe filename; revoke URL sau khi đã dùng. Không parse bytes như JSON.
- HTTP error được đọc theo JSON error envelope; không tải error JSON thành file `.xlsx`.
- Copy hướng dẫn: “Dùng lại file này để nhập câu trả lời. Giữ nguyên mã hồ sơ, mã bộ câu hỏi và mã từng câu.”
- Sau export thành công: refetch state, CTA tiếp theo “Nhập Excel đã trả lời”.
- Download lại dùng đúng set/version mà server cho phép; không tạo workbook ở browser.

### S-06. Câu trả lời — `/cases/:caseId/answers`

**Trước import:**

- File chooser `accept=".xlsx"`, drag/drop chỉ là enhancement của chooser.
- Hiển thị tên file, size và kiểm tra extension/limit trước gửi. `.xls`/`.xlsm` bị từ chối rõ ràng.
- CTA “Nhập và kiểm tra Excel”. Thao tác này gửi bytes và có thể tạo snapshot ngay; không gọi đây là preview không ghi dữ liệu.
- Chọn file mới chỉ thay local selection, chưa thay snapshot server.
- Giữ separate pending/imported UI để không hiển thị file vừa chọn như bản nhập thành công.

**Sau import thành công:**

- Hiển thị snapshot ID dạng nhãn ngắn, version, importedAt, Question Set version và số câu answered/total từ snapshot thật.
- Bảng câu hỏi và câu trả lời chỉ đọc. Chọn hàng mở detail đầy đủ, rubric snapshot và answer status.
- Câu hỏi đã chỉnh trong Excel dùng nội dung của imported snapshot; không đọc nhầm Question Set hiện hành.
- Nếu backend có diff, hiển thị “Câu hỏi đã thay đổi trong bản nhập”; nếu không có diff thì không bịa số lượng thay đổi.
- Blank + `isAnswered=false`: “Chưa trả lời”, không tự điền câu trả lời/điểm.
- CTA riêng “Đánh giá bằng AI” gửi snapshotId cụ thể. Import không tự khởi chạy evaluation trừ khi contract backend đã chốt khác và ghi nhận rõ.
- “Nhập file khác” nêu rõ tạo bản nhập mới; không hứa hẹn ghi đè bản cũ.
- Same file/same idempotency key trả cùng snapshot; UI không nhân đôi hàng/version.

**Import failure:**

- Sai case/set/version: “File không khớp hồ sơ hoặc bộ câu hỏi đang xử lý”.
- Header/row lỗi: hiển thị sheet/row/field và safe message nếu backend cung cấp; không tự đọc OOXML ở browser.
- Formula/macro/link/embedded object/ZIP/XML lỗi: “File không đáp ứng định dạng an toàn. Hãy dùng mẫu được xuất từ hệ thống.”
- Flag answer không nhất quán: yêu cầu sửa file; không tự đổi flag để pass validation.
- Giữ snapshot/result đã có khi import mới thất bại.

### S-07. Đánh giá AI — `/cases/:caseId/ai`

Màn này chứa ba state: chưa đánh giá, task đang chạy, kết quả đã hoàn thành.

**Chưa đánh giá:** hiển thị bản nhập được chọn, answered count và CTA “Đánh giá bằng AI”. Nếu thiếu snapshot: hướng dẫn quay lại bước Câu trả lời.

**Đang chạy:** task status, operation, thời gian chờ; cho phép về bước khác. Không tạo task trùng do refresh, đổi tab hoặc nhấn nút hai lần. Khi có result cũ, vẫn có thể xem result đó với provenance cũ và banner tác vụ mới đang chạy.

**Kết quả v2:**

1. Header “Kết quả đánh giá AI”; result version, snapshot version/ID, question set version, thời gian hoàn thành và provider/model an toàn nếu API có trả.
2. Completion: answered/total của chính snapshot được đánh giá.
3. Confidence: hiển thị số 0–1 dạng `0,82 / 1`, label “Độ chắc chắn của phân tích”. Null/missing hiện “Không có thông tin”.
4. Hai vùng “Điểm mạnh” và “Khoảng thiếu bằng chứng”. List rỗng hiện “Không có nội dung được ghi nhận”, không tự tạo nhận xét tích cực.
5. Ma trận năng lực: competency, evidence status, concerns nếu có và liên kết tới câu hỏi/bằng chứng được trả trong output.
6. Mâu thuẫn và rủi ro hiển thị riêng; không trộn gap với conflict.
7. Per-answer: danh sách câu; chọn câu mở câu hỏi + answer gốc bên trái, score/reasoning/evidenceFound/concerns/cvConsistency bên phải. Mobile xếp answer trước analysis.
8. Limitations luôn có vùng đọc được, không ẩn tất cả cảnh báo quan trọng vào tooltip.
9. Dòng cuối: “AI hỗ trợ đối chiếu bằng chứng. Quyết định tuyển dụng thuộc HĐCM.”

Không tự tạo weighted overall score, phần trăm phù hợp, PASS/FAIL hay recommendedLiveQuestions. Không chỉnh sửa AiResult ở UI. Không render Interview Brief từ field legacy.

Score null hiển thị “— / Chưa đánh giá”, không `0/4`. Score 0 hiển thị đúng 0 và reasoning tương ứng. Không dùng phép ép kiểu khiến null thành 0.

Version selector tuân theo C-02. Khi đổi version phải thay toàn bộ provenance, question/answer snapshot, score, reasoning, strengths, gaps và confidence đồng bộ. Nếu dữ liệu đang tải, không ghép answer của version mới với reasoning cũ.

Nếu current snapshot khác snapshot của current result, banner: “Kết quả này thuộc bản nhập X. Bản nhập Y chưa được đánh giá.” Không gọi kết quả cũ là đánh giá của bản nhập mới.

Failed: lỗi an toàn, retry/rerun theo backend, liên kết “Xem câu trả lời gốc để đánh giá thủ công”. Đây là fallback đọc dữ liệu; không tự tạo module chấm manual/final evaluation.

### S-08. Cấu hình — `/settings`

- Đọc provider, model, timeout, retry và defaults an toàn từ health/settings/bootstrap đang có.
- “Đã cấu hình” chỉ nghĩa config có mặt; không ghi “Gemini đang online” khi chưa có bằng chứng kết nối.
- Không có input API key trong UI cho Gemini environment-only design; không đọc file `.env` từ browser.
- Field editable chỉ dành cho key đã có trong PATCH settings allowlist. Environment-driven values chỉ đọc.
- Endpoint nếu được hiển thị phải là safe summary không query/key. Không hiển thị local absolute path.
- Nếu không có safe provider metadata trong API, ghi “Chưa có thông tin cấu hình”; không gọi endpoint mới hay đưa secret xuống frontend.

### S-09. Sao lưu — `/backups`

- Form: label, includeDocuments và case scope nếu export API cho phép.
- “Tạo bản sao lưu” gọi backups; “Xuất gói hồ sơ” gọi exports theo contract hiện có.
- Dialog trước export nêu gói có dữ liệu ứng viên và cần bảo vệ.
- Chỉ báo hoàn thành theo server response/task COMPLETED.
- Hiển thị safe file/path summary. Không thêm download link nếu backend không có endpoint được phép phục vụ file.
- Không tự bổ sung restore-from-browser hoặc dọn retention tự động.

## 9. Workflow và action gating

Tên refined status dưới đây xuất phát từ Excel implementation plan. Map response camelCase/snake_case vào view model bằng adapter; không gửi enum mới chỉ vì UI có label.

| Backend state | Label UI | Bước mở mặc định | CTA chính |
| --- | --- | --- | --- |
| `DRAFT` | Chuẩn bị tài liệu | JD & CV | Nhập/xác nhận tài liệu |
| `DOCUMENTS_READY` | Tài liệu sẵn sàng | Bộ câu hỏi | Sinh câu hỏi |
| `QUESTIONS_GENERATING` | Đang sinh câu hỏi | Bộ câu hỏi | Xem trạng thái |
| `QUESTIONS_GENERATED` | Bộ câu hỏi đã tạo | Bộ câu hỏi | Xuất Excel nếu hợp lệ |
| `QUESTIONS_EXPORTED` | Chờ nhập câu trả lời | Câu trả lời | Nhập Excel |
| `ANSWERS_IMPORTED` | Đã nhập câu trả lời | Câu trả lời | Đánh giá bằng AI |
| `AI_ANALYZING` | Đang đánh giá AI | Đánh giá AI | Xem trạng thái |
| `AI_EVALUATED` | AI đã đánh giá | Đánh giá AI | Xem kết quả |
| `QUESTION_GENERATION_FAILED` | Sinh câu hỏi thất bại | Bộ câu hỏi | Retry/manual khi được phép |
| `AI_ANALYSIS_FAILED` | Đánh giá AI thất bại | Đánh giá AI | Retry/xem answer gốc |

- Parse failure nằm trong document state hoặc backend case state thực có; không thêm refined enum tùy ý.
- Gating dùng state + resource readiness + session + task status + backend permission nếu có. Không chỉ kiểm tra một chuỗi status.
- Không chuyển `AI_EVALUATED` thành “Đã tuyển” hoặc “Đã chốt”.
- Backend trả conflict: refetch resources và hiển thị nguyên nhân; không retry mutation bằng cách sửa state client.

## 10. API integration contract

### 10.1. Endpoints

| Action | Method/path theo tài liệu nguồn | Body/response |
| --- | --- | --- |
| List/create case | GET/POST `/api/v1/interview-cases` | JSON envelope |
| Read/update case | GET/PATCH `/api/v1/interview-cases/{caseId}` | JSON envelope |
| Candidate/Job lookup/create | GET/POST `/api/v1/candidates`, `/api/v1/jobs` | JSON envelope |
| List/import documents | GET/POST `/api/v1/interview-cases/{caseId}/documents` | Manual text hoặc metadata/base64 theo document contract |
| Confirm document | POST `/api/v1/interview-cases/{caseId}/documents/{documentId}/confirm` | confirmed + textSha256 |
| Generate/read/edit set | POST/GET/PATCH `/api/v1/interview-cases/{caseId}/question-set` | Generate trả 202/taskId; read/edit trả JSON |
| Export workbook | POST `/api/v1/interview-cases/{caseId}/question-set/export` | Binary xlsx response |
| Import workbook | POST `/api/v1/interview-cases/{caseId}/assessment-snapshots/import` | Binary xlsx request; JSON snapshot response |
| Read snapshot | GET `/api/v1/interview-cases/{caseId}/assessment-snapshots/{snapshotId}` | JSON summary/payload theo implementation |
| Evaluate snapshot | POST `/api/v1/interview-cases/{caseId}/ai/evaluate` | snapshotId, optional forceRerun; 202/taskId |
| Read current AI result | GET `/api/v1/interview-cases/{caseId}/ai/evaluation` | JSON result theo v2 |
| Poll task | GET `/api/v1/tasks/{taskId}` | JSON task state |
| Settings | GET/PATCH `/api/v1/settings` | Allowlisted non-secret values |
| Health | GET `/api/v1/health` | Safe status/config summary |
| Backup/export package | POST `/api/v1/backups`, `/api/v1/exports` | Immediate result hoặc taskId |

Các payload bên trong `data` của refined endpoints chưa được mô tả đầy đủ trong tài liệu gốc. Trước khi code, kiểm tra router, controller, service, tests và ghi field mapping đã xác minh. Không phát minh field như `allVersions`, `permissions` hoặc `latestSnapshot` rồi coi API đã có.

### 10.2. HTTP helpers

- Giữ/hoàn thiện `apiRequest` cho JSON success/error envelope.
- `apiDownload(path, options)`: nhận Blob + response headers; lỗi đọc safe JSON khi phù hợp.
- `apiUpload(path, fileOrBlob, options)`: gửi raw xlsx bytes; không JSON.stringify Blob, không chuyển Excel thành base64 cho route binary.
- MIME workbook: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- Auth và mutation headers theo route: `X-Committee-Session`, `X-Startup-Token`, `X-Idempotency-Key`. Header auth không được đặt vào query string.
- RequestId được giữ trong safe error để người vận hành tra cứu; không đưa stack trace, SQL hoặc full payload ra UI.
- Không gọi Gemini trực tiếp từ frontend; `fetch` chỉ gọi same-origin API.

### 10.3. Normalized view models

Đây là model nội bộ frontend, không phải schema request mới:

| View model | Dữ liệu tối thiểu |
| --- | --- |
| CaseView | id, candidate code/name, job title/level, schedule, effective/refined state |
| DocumentView | id/type/version, extraction state, confirmation/eligibility, extracted text, content hash |
| QuestionSetView | id/version/status, duration, ordered questions, actual total |
| QuestionView | stable id/order/text, competency, purpose, evidence, rubric, optional category/objective |
| SnapshotView | id/version/case/set references, document provenance, copied questions, answers, import time |
| TaskView | id/type/status, safe error, timestamps, result reference nếu có |
| EvaluationView | result id/version, snapshot reference, schema version, validated v2 fields |

Adapter phải giữ distinct source Question Set và imported questions. Không gộp hai nguồn chỉ vì cùng question ID. Array nào thiếu là unknown/loading/error theo contract, không tự đổi thành empty success để che lỗi schema.

## 11. Async, idempotency và recovery

### 11.1. Polling

- Poll mặc định 2 giây; nếu backend có retry hint hợp lệ thì dùng trong khoảng 2–30 giây.
- Mỗi task chỉ có một poller active. Không tạo interval chồng lặp khi render lại component.
- `PENDING`: “Đang chờ xử lý”; `RUNNING`: “Đang xử lý”; `PENDING_RETRY`: “Đang thử lại”; `COMPLETED`: “Hoàn thành”; `FAILED`: “Thất bại”.
- Poll thất bại do network không đồng nghĩa task FAILED. Hiển thị “Chưa cập nhật được trạng thái”, giữ taskId và cho thử tải lại.
- Dừng poll khi terminal, session invalid hoặc không còn subscriber; tab hidden tạm ngừng request và refetch khi trở lại.
- Refresh đọc task/resource đã persist để resume; không enqueue lại AI job.
- Abort stale GET khi đổi case/version. Response về trễ không được overwrite view của case khác.
- Không dùng progress % hoặc thời gian hoàn thành dự đoán nếu backend không trả dữ liệu tương ứng.

### 11.2. Mutation và retry

- Disable nút đang gửi, tránh double-click. Loading không khóa toàn bộ app shell.
- Tạo một idempotency key cho một intent/payload; retry sau mất response dùng lại key đó nếu payload không đổi.
- Payload/file thay đổi phải có key mới. Conflict cùng key/payload khác phải hiển thị, không tự retry vô hạn.
- Force rerun là intent mới: confirmation nêu tạo version mới, key mới và reason chỉ khi API hỗ trợ field reason.
- Không tự gọi lại mutation sau reconnect/session unlock vì user có thể không biết thao tác đã thành công ở server.

### 11.3. Dữ liệu local

- Session/token chỉ trong memory; không localStorage/sessionStorage/IndexedDB/URL.
- JD/CV/answer draft chưa gửi chỉ trong memory. Nếu rời form có thay đổi chưa gửi, hiện confirmation.
- Không hứa draft chưa gửi được khôi phục sau refresh. Dữ liệu đã commit được refetch từ backend.
- Không ghi nội dung ứng viên hay workbook vào console để debug.

## 12. Evidence, scoring và microcopy

| Enum | Nhãn UI |
| --- | --- |
| `VERIFIED` | Có bằng chứng theo AI |
| `PARTIALLY_VERIFIED` | Có bằng chứng một phần |
| `UNVERIFIED` | Chưa đủ bằng chứng xác minh |
| `CONFLICTING` | Có mâu thuẫn |
| `NOT_MET` | Chưa đáp ứng tiêu chí |
| `NOT_ASSESSED` | Chưa đánh giá |

Đây là nhận định của AI từ input, không phải xác minh độc lập. Tooltip/helper text không được biến VERIFIED thành bảo đảm kinh nghiệm thật.

| Tình huống | Copy chính |
| --- | --- |
| Chờ xác nhận CV | “Cần xác nhận nội dung CV trước khi sinh câu hỏi.” |
| Đang sinh câu hỏi | “Đang tạo bộ câu hỏi từ JD và CV đã xác nhận.” |
| Đang đánh giá | “Đang đánh giá câu trả lời theo rubric của bản nhập này.” |
| Answer trống | “Chưa trả lời — chưa đánh giá.” |
| AI lỗi | “AI chưa hoàn thành đánh giá. Câu trả lời đã nhập vẫn được lưu.” |
| Import mới | “File thay đổi sẽ tạo bản nhập mới và giữ nguyên kết quả trước đó.” |
| Import không khớp | “File không khớp hồ sơ hoặc bộ câu hỏi đang xử lý.” |
| Server không kết nối | “Không kết nối được ứng dụng cục bộ. Hãy kiểm tra ứng dụng đang chạy và tải lại.” |
| C-01 | “Số câu của bộ câu hỏi chưa tương thích với định dạng Excel đang áp dụng.” |

Chỉ dùng “đã lưu”, “đã xuất”, “hoàn thành” khi server/transport xác nhận. Có thể viết “Đã nhận file xuất từ hệ thống”; không đảm bảo file đã được người dùng lưu vào ổ đĩa nếu browser không cung cấp bằng chứng.

## 13. Accessibility và security UI

- Semantic landmarks, table headers, input labels và tên nút đầy đủ.
- Step tabs có aria-selected và panel association; hỗ trợ keyboard phù hợp kiểu tabs hoặc dùng links điều hướng rõ ràng.
- Visible focus tối thiểu 2 px; selected state khác focus state.
- Error gắn aria-describedby; lỗi quan trọng có role=alert; task update dùng aria-live=polite, không announce mỗi lần poll nếu nội dung không đổi.
- Dialog giữ focus, có nút Cancel, trả focus về trigger khi đóng. Escape không giả hủy tác vụ backend đã enqueue.
- Không ép tắt outline; không yêu cầu hover mới xem được nội dung quan trọng.
- Normal text contrast tối thiểu 4.5:1; controls/non-text essentials tối thiểu 3:1. Kiểm tra token trên đúng nền sử dụng.
- Respect prefers-reduced-motion; không có animation vô hạn hoặc hiệu ứng typing AI.
- Tất cả document/AI/candidate text dùng textContent/DOM text nodes. Không innerHTML, eval, new Function, dynamic scripts hoặc render Markdown HTML từ AI.
- Không expose key/PIN/token, query URL provider, raw workbook trong JSON, local absolute path hoặc protected settings.
- UI disable/hide chỉ là hướng dẫn trải nghiệm; backend auth/state validation vẫn bắt buộc.
- Dữ liệu thật không có badge “Dữ liệu minh họa”. Sample mode, nếu dùng cho review, phải tách fixture và luôn ghi “Dữ liệu mẫu — chưa kết nối backend”.

## 14. Component và source organization

Ưu tiên mở rộng cấu trúc frontend hiện có. Các tên module dưới đây là gợi ý, không yêu cầu tạo đủ file nếu repository đã có abstraction tương đương.

| Area | Component / module |
| --- | --- |
| Shell | AppShell, Sidebar, Topbar, CaseHeader, CaseSteps |
| Shared | StatusBadge, EmptyState, ErrorBanner, TaskProgress, ConfirmDialog, LoadingSkeleton |
| Case | CaseList, CaseForm |
| Documents | DocumentCard, TextPreview, DocumentImportForm |
| Questions | QuestionList, QuestionDetail, RubricAccordion, QuestionEditor |
| Workbook | WorkbookPicker, ImportSummary, SnapshotAnswerList |
| Evaluation | ResultHeader, CompetencyTable, AnswerEvidenceDetail, LimitationsPanel |
| API/state | api.js, store.js, route helpers, view-model adapter, task polling service |
| Styles | token stylesheet, shell/layout styles, component styles |

- Không nhét SQL, provider call hoặc rule state machine vào web/js.
- Không sao chép HTML prototype với script giả lập vào production rồi giữ alert thay cho API.
- Business validation trong frontend chỉ hỗ trợ user; backend authoritative.
- Dọn navigation/route legacy active, giữ backend data theo retention rule; không xóa table để làm UI gọn.
- Không thêm third-party runtime dependencies, npm/package.json hoặc CDN asset.

## 15. Hướng dẫn Codex triển khai theo batch

### Batch UI-A — Kiểm tra contract và dựng nền giao diện

1. Đọc AGENTS.md nếu có và các nguồn tại mục 2.
2. Kiểm tra router, API response, current frontend, fixtures; ghi mapping và dependency còn thiếu.
3. Xác minh C-01 và C-02; không sửa backend contract ngoài phạm vi.
4. Thêm tokens, shell, route navigation, shared states và Committee unlock integration.
5. Dùng dữ liệu mẫu đã tách riêng để review layout nếu cần; mặc định production gọi API thật.
6. Test/checkpoint trước batch tiếp theo.

### Batch UI-B — Case và documents

- Hoàn thành S-02/S-03/S-04; pagination/filter tương thích; file/text import và confirm.
- Kiểm tra partial creation failure, PDF/manual fallback, eligibility gating và refresh.
- Test/checkpoint.

### Batch UI-C — Questions và workbook

- Hoàn thành S-05/S-06; dynamic count/category; review; export Blob và import binary.
- Kiểm tra 5–8 câu hợp lệ theo baseline; render fixture 9 câu chỉ để chứng minh layout dynamic, không tuyên bố export 9 câu hợp lệ.
- Kiểm tra workbook mismatch, errors, double submit, idempotency và immutable snapshot.
- Test/checkpoint.

### Batch UI-D — AI result và vận hành

- Hoàn thành S-07/S-08/S-09; enqueue/poll/refetch, evidence comparison, version provenance.
- Version history chỉ triển khai nếu đã có read API đúng contract.
- Test/checkpoint.

### Batch UI-E — Acceptance và handoff

- Rà soát full flow, accessibility, responsive, security và legacy navigation removal.
- Chạy full test suite repository theo phạm vi thay đổi.
- Nếu có browser tooling sẵn, kiểm tra DOM behavior/layout. Không tự thêm dependency runtime để test.
- Kiểm tra trên Windows client theo khả năng môi trường. Nếu không có Windows, ghi “chưa kiểm tra trên Windows”, không báo pass thay.
- Bàn giao changed files, test evidence, screenshots nếu có, dependency/gap và hướng dẫn chạy.

Mỗi batch phải hoàn thành và test trước khi sang batch kế tiếp. Không gom toàn bộ thành một thay đổi lớn. Nếu test của batch thất bại, sửa hoặc ghi blocker cụ thể trước khi đi tiếp. Nếu repository có git, tạo checkpoint commit theo quyền đã được giao; không push/merge/deploy trong nhiệm vụ triển khai UI này.

Khi API bắt buộc chưa tồn tại, hoàn thành các phần UI độc lập và ghi blocker endpoint/field/test cần thiết; không báo flow production đã xong bằng mock. Không tự triển khai toàn bộ backend Excel/Gemini như phần phụ của UI task.

## 16. Test và acceptance criteria

### 16.1. Functional acceptance

| ID | Scenario | Expected |
| --- | --- | --- |
| UI-AC-001 | Tạo Candidate/Job/Case và lỗi bước cuối | Retry không tạo trùng entity đã thành công |
| UI-AC-002 | Nhập và confirm JD/CV | UI hiển thị đúng version/eligibility; chỉ enable generation khi đủ |
| UI-AC-003 | PDF không có extractor | Fallback dán text; không giả native PDF/OCR |
| UI-AC-004 | Generate trả 202 | Poll task thật, không fabricate questions, không chặn navigation |
| UI-AC-005 | Questions có 5, 8 hoặc fixture 9 phần tử | Counter/list dynamic; fixture 9 không vượt contract export |
| UI-AC-006 | Backend không có category/objective | List phẳng; không suy đoán grouping |
| UI-AC-007 | Export hợp lệ | MIME/body download đúng, error JSON không thành xlsx |
| UI-AC-008 | Import xlsx đúng | Snapshot thật hiển thị; evaluate dùng chính snapshotId đó |
| UI-AC-009 | Import sai ID/header/flag/type | Lỗi rõ; không giả snapshot; snapshot/result cũ vẫn đọc được |
| UI-AC-010 | Double-click hoặc mất response | Không nhân đôi mutation khi cùng intent/key |
| UI-AC-011 | Answer rỗng | NOT_ASSESSED, score null; không hiển thị 0 |
| UI-AC-012 | Import sửa question text/rubric | Result detail dùng imported snapshot, không mutable generated set |
| UI-AC-013 | AI thành công | Toàn bộ v2 fields được trình bày an toàn, có answer gốc và reasoning |
| UI-AC-014 | AI fail/timeout | Giữ answers và result cũ; retry/manual-read path rõ |
| UI-AC-015 | Refresh khi task chạy | Resume từ state/task persist; không enqueue lại |
| UI-AC-016 | Version/history được API hỗ trợ | Đổi toàn bộ provenance và nội dung đồng bộ |
| UI-AC-017 | Chỉ có current result | Không xuất hiện history selector giả |
| UI-AC-018 | Snapshot mới, result cũ | Banner phân biệt nguồn; không gắn nhầm version |
| UI-AC-019 | Session hết hạn | Nội dung khóa, mở phiên lại; không tự gửi lại mutation |
| UI-AC-020 | Backup/export failure | Không báo completed hoặc download link giả |
| UI-AC-021 | Mở navigation active | Không Candidate/Brief/Live/Final/PASS-FAIL actions |
| UI-AC-022 | Mở case/version khác khi GET về trễ | Response cũ không overwrite case/version đang xem |

### 16.2. Visual/accessibility acceptance

- Kiểm tra ít nhất 1440, 1280, 1024, 768 và 390 px; không tràn trang, không overlap CTA, text dài wrap được.
- Bốn step có consistent selected/complete/empty state.
- List câu hỏi và detail liên kết đúng; mobile vẫn xem được cả hai.
- Answer gốc và reasoning đọc được, không bị thu nhỏ thành text metadata.
- Focus keyboard, dialog return focus, labels/errors/aria-live hoạt động.
- Contrast đạt mục 13; states không phụ thuộc màu.
- Empty/loading/error/locked/network/session state có giao diện thật, không chỉ test happy path.

### 16.3. Security/regression acceptance

- HTML/script trong CV, question, answer hoặc AI output chỉ render thành text.
- Không API key/PIN/token/CV/answer xuất hiện trong console, URL, browser persistent storage hoặc thông báo lỗi.
- Không gọi provider URL/CDN trong production frontend.
- Binary helpers và auth headers không phá JSON API hiện có.
- Legacy DB/results được bảo toàn; UI không dùng route cũ để hoàn tất flow Excel.
- Full tests theo repository chạy pass; automated AI tests dùng fake provider, không gọi Google thật.

## 17. Definition of Done và báo cáo bàn giao

UI hoàn thành khi:

1. Shell và toàn bộ màn hình active được implement bằng HTML/CSS/Vanilla JS theo layout này.
2. Các action chính dùng API thật, có loading/error/retry và state gating.
3. Export/import xlsx và evaluate snapshot chạy xuyên suốt bằng backend contract đã áp dụng.
4. C-01/C-02 có kết quả kiểm tra rõ; không có hardcode 9 câu, selector lịch sử giả hoặc mutation thành công giả.
5. Snapshot/result provenance chính xác; answer trống giữ semantics NOT_ASSESSED.
6. Accessibility, responsive và security acceptance có evidence tương ứng.
7. Không thêm thư viện runtime hoặc mở rộng ngoài scope.
8. Có checkpoint từng batch và báo cáo hạn chế chưa kiểm tra.

Báo cáo cuối cho người dùng phải nêu: màn hình đã hoàn thành, contract thực tế về số câu, endpoint/field đã nối, test đã chạy và kết quả, phần chưa thể kiểm tra hoặc dependency còn thiếu. Không ghi “hoàn thành end-to-end” nếu chỉ chạy mock UI hoặc chưa có Excel/evaluation API.

## 18. Chỉ dẫn thực thi ngắn để dùng cùng tài liệu

> Đọc AGENTS.md, các specification nguồn và `30_interview_workspace_ui_implementation_specification.md`. Sau đó implement UI Interview Workspace theo các batch UI-A đến UI-E. Giữ Python Standard Library và HTML/CSS/Vanilla JS, dùng API thật, không mở rộng nghiệp vụ hoặc sửa contract Excel/AI để làm UI pass. Kiểm tra khác biệt 5–8/9 câu, render số lượng động và phân nhóm chỉ khi có dữ liệu backend. Hoàn thành/test/checkpoint từng batch trước khi sang batch tiếp theo. Cuối cùng chạy full flow, kiểm tra responsive/accessibility/security và báo cáo kết quả cùng các dependency còn thiếu. Không dùng mock để tuyên bố production flow hoàn tất.
