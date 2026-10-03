ClawCV Phase 2 Supervised Interview — Windows Portable
======================================================

1. Giải nén toàn bộ ZIP vào một thư mục local.
2. Chạy start.bat. Trình duyệt mở http://127.0.0.1:8787.
3. Lần chạy đầu, đặt Committee PIN gồm 4–12 chữ số.
4. Dữ liệu nằm tại %LOCALAPPDATA%\ClawCV, không nằm trong thư mục cài đặt.

AI là tùy chọn. Nếu chưa cấu hình, ứng dụng chuyển task sang FAILED an toàn và
cho phép dùng bộ câu hỏi/Interview Brief manual. Để cấu hình approved gateway,
đặt AI_ENDPOINT, AI_MODEL và AI_API_KEY trong environment trước khi chạy.

Backup thủ công nằm dưới %LOCALAPPDATA%\ClawCV\backups. Hãy tạo backup trước
khi xóa case hoặc chuyển dữ liệu. Không chia sẻ backup/export khi chưa kiểm tra
chính sách dữ liệu của tổ chức.

Ứng dụng chỉ bind 127.0.0.1. Không sửa APP_HOST sang địa chỉ LAN/public.
