# DocumentChain

Ứng dụng demo cấp và xác thực chứng chỉ số bằng SHA-256, chữ ký số RSA và blockchain cục bộ.

## Cấu trúc mới

```text
.
├── backend/
│   ├── main.py              # FastAPI app
│   ├── blockchain.py        # Block + blockchain proof-of-work
│   ├── certificate_utils.py # Sinh PDF và QR code
│   ├── crypto_utils.py      # SHA-256 + RSA signature
│   └── storage.py           # SQLite persistence
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── main.jsx
│       └── styles.css
├── data/
│   └── documents.db
├── keys/
│   ├── private_key.pem
│   └── public_key.pem
└── requirements.txt
```

## Luồng cấp chứng chỉ

1. Issuer đăng nhập.
2. Issuer nhập thông tin sinh viên và chứng chỉ trên React frontend.
3. FastAPI backend sinh `certificate_id`, QR code và file PDF chứng chỉ.
4. Backend tính hash SHA-256 của file PDF.
5. Backend ký hash bằng private key RSA của issuer demo.
6. File PDF và QR được lưu trong `data/`.
7. Hash, chữ ký số, `certificate_id` và metadata được lưu lên blockchain cục bộ.
8. Frontend trả link tải PDF cho issuer; QR trỏ tới trang xác thực `/verify/<certificate_id>`.

## Chạy backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

API chạy tại:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Chạy frontend

Mở terminal khác:

```bash
cd frontend
npm install
npm run dev
```

Frontend chạy tại:

```text
http://127.0.0.1:5173
```

Vite proxy tự chuyển các request `/api/*` sang backend `http://127.0.0.1:8000`.

## Tài khoản mặc định

Khi chạy lần đầu, backend tự tạo tài khoản admin:

```text
username: admin
password: admin123
```

Admin có thể tạo thêm user với các role:

| Role | Quyền |
| --- | --- |
| `admin` | Quản lý người dùng, xem blockchain |
| `issuer` | Cấp chứng chỉ, chỉ xem tài liệu do mình xuất bản |
| `verifier` | Xác thực chứng chỉ bằng file PDF, không xem danh sách tài liệu |

## API chính

| Method | Endpoint | Mục đích |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Đăng nhập |
| `POST` | `/api/auth/logout` | Đăng xuất |
| `GET` | `/api/auth/me` | Lấy user hiện tại |
| `GET` | `/api/chain` | Xem blockchain |
| `POST` | `/api/certificates` | Issuer cấp chứng chỉ |
| `GET` | `/api/certificates/{certificate_id}` | Xác thực theo Certificate ID |
| `GET` | `/api/certificates/{certificate_id}/download` | Tải PDF chứng chỉ |
| `POST` | `/api/verify-file` | Verifier upload PDF để xác thực |
| `GET` | `/api/users` | Admin xem user |
| `POST` | `/api/users` | Admin tạo user |
| `PUT` | `/api/users/{user_id}` | Admin sửa user |
| `DELETE` | `/api/users/{user_id}` | Admin xóa user |

## Lưu ý bảo mật

Đây là dự án demo học thuật. Khi triển khai thật cần đổi `SECRET_KEY`, bỏ mật khẩu admin mặc định, thêm CSRF hoặc token auth phù hợp, chính sách mật khẩu, audit log, kiểm soát file, backup database và quản lý private key bằng vault/HSM.
