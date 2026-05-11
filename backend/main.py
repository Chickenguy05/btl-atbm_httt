from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from werkzeug.security import check_password_hash

from .certificate_utils import build_certificate_pdf, generate_certificate_qr
from .crypto_utils import ensure_key_pair, sha256_bytes, sign_hash, verify_signature
from .storage import (
    create_issuer,
    create_user,
    delete_issuer,
    delete_user,
    find_user_by_id,
    find_user_by_username,
    get_issuer_public_key,
    list_blocks_for_user,
    list_issuers,
    list_users,
    load_blockchain,
    save_block,
    update_user,
)


app = FastAPI(title="DocumentChain API")
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://127.0.0.1:5173").rstrip("/")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "document-auth-demo-secret"),
    same_site="lax",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str


class UpdateUserRequest(BaseModel):
    username: str
    role: str
    password: str | None = None


class CreateIssuerRequest(BaseModel):
    name: str


class IssueCertificateRequest(BaseModel):
    student_name: str
    student_id: str
    course_name: str
    issued_at: str
    issuer_id: int


class UploadCertificateRequest(BaseModel):
    student_name: str
    student_id: str
    course_name: str
    issued_at: str
    issuer_id: int


class VerifyRequest(BaseModel):
    issuer_id: int


def row_to_user(user: Any) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


def get_current_user(request: Request) -> dict[str, Any]:
    user_id = request.session.get("user_id")
    user = find_user_by_id(user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return row_to_user(user)


def require_roles(*roles: str):
    def dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return user

    return dependency


@app.on_event("startup")
def startup() -> None:
    ensure_key_pair()
    load_blockchain()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    user = find_user_by_username(payload.username.strip())
    if user is None or not check_password_hash(user["password_hash"], payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    request.session.clear()
    request.session["user_id"] = user["id"]
    return {"user": row_to_user(user)}


@app.post("/api/auth/logout")
def logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"message": "Logged out"}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"user": user}


@app.get("/api/chain")
def chain(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    blockchain = load_blockchain()
    valid, message = blockchain.verify_chain()
    return {
        "chain_valid": valid,
        "chain_message": message,
        "blocks": list_blocks_for_user(user),
        "user": user,
    }


@app.post("/api/certificates")
def issue_certificate(
    payload: IssueCertificateRequest,
    request: Request,
    user: dict[str, Any] = Depends(require_roles("issuer")),
) -> dict[str, Any]:
    fields = [
        payload.student_name.strip(),
        payload.student_id.strip(),
        payload.course_name.strip(),
        payload.issued_at.strip(),
    ]
    if any(not value for value in fields):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing certificate fields")

    certificate_id = f"CERT-{uuid4().hex[:12].upper()}"
    metadata = {
        "certificate_id": certificate_id,
        "student_name": fields[0],
        "student_id": fields[1],
        "course_name": fields[2],
        "issued_at": fields[3],
        "issuer": user["username"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    verify_url = f"{FRONTEND_BASE_URL}/verify/{certificate_id}"
    qr_path = generate_certificate_qr(certificate_id, verify_url)
    pdf_path, data = build_certificate_pdf(metadata, qr_path)
    document_hash = sha256_bytes(data)
    signature = sign_hash(document_hash, issuer_id=payload.issuer_id)

    blockchain = load_blockchain()
    existing = blockchain.find_by_document_hash(document_hash)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document already exists at block #{existing.index}",
        )

    block = blockchain.add_document(
        document_hash=document_hash,
        document_name=pdf_path.name,
        owner=user["username"],
        signature=signature,
        certificate_id=certificate_id,
        metadata=metadata,
        file_path=str(pdf_path),
        qr_path=str(qr_path),
        issuer_id=payload.issuer_id,
    )
    save_block(block)
    return {
        "certificate_id": certificate_id,
        "block": block.__dict__,
        "download_url": f"/api/certificates/{certificate_id}/download",
        "verify_url": f"/api/certificates/{certificate_id}",
    }


@app.post("/api/certificates/upload")
async def upload_certificate(
    certificate_file: UploadFile = File(...),
    student_name: str = Form(...),
    student_id: str = Form(...),
    course_name: str = Form(...),
    issued_at: str = Form(...),
    issuer_id: str = Form(...),
    user: dict[str, Any] = Depends(require_roles("issuer")),
) -> dict[str, Any]:
    fields = [
        student_name.strip(),
        student_id.strip(),
        course_name.strip(),
        issued_at.strip(),
    ]
    if any(not value for value in fields):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing certificate fields")

    # Read uploaded file
    data = await certificate_file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    issuer_id_int = int(issuer_id)
    certificate_id = f"CERT-{uuid4().hex[:12].upper()}"
    metadata = {
        "certificate_id": certificate_id,
        "student_name": fields[0],
        "student_id": fields[1],
        "course_name": fields[2],
        "issued_at": fields[3],
        "issuer": user["username"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    verify_url = f"{FRONTEND_BASE_URL}/verify/{certificate_id}"
    qr_path = generate_certificate_qr(certificate_id, verify_url)

    # Save uploaded file
    certificates_dir = Path("data/certificates")
    certificates_dir.mkdir(exist_ok=True)
    pdf_path = certificates_dir / f"{certificate_id}.pdf"
    with open(pdf_path, "wb") as f:
        f.write(data)

    document_hash = sha256_bytes(data)
    signature = sign_hash(document_hash, issuer_id=issuer_id_int)

    blockchain = load_blockchain()
    existing = blockchain.find_by_document_hash(document_hash)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document already exists at block #{existing.index}",
        )

    block = blockchain.add_document(
        document_hash=document_hash,
        document_name=pdf_path.name,
        owner=user["username"],
        signature=signature,
        certificate_id=certificate_id,
        metadata=metadata,
        file_path=str(pdf_path),
        qr_path=str(qr_path),
        issuer_id=issuer_id_int,
    )
    save_block(block)
    return {
        "certificate_id": certificate_id,
        "block": block.__dict__,
        "download_url": f"/api/certificates/{certificate_id}/download",
        "verify_url": f"/api/certificates/{certificate_id}",
    }


@app.post("/api/verify-file")
async def verify_file(
    document: UploadFile = File(...),
    issuer_id: int = Form(...),
    user: dict[str, Any] = Depends(require_roles("verifier")),
) -> dict[str, Any]:
    data = await document.read()
    document_hash = sha256_bytes(data)
    return build_verification_result(document_hash, issuer_id=issuer_id, user=user)


@app.get("/api/certificates/{certificate_id}")
def verify_certificate_by_id(certificate_id: str) -> dict[str, Any]:
    blockchain = load_blockchain()
    chain_valid, chain_message = blockchain.verify_chain()
    block = blockchain.find_by_certificate_id(certificate_id)
    if not block:
        return {
            "status": "invalid",
            "title": "Không tìm thấy chứng chỉ",
            "detail": "Certificate ID không tồn tại trên blockchain cục bộ.",
            "document_hash": "",
            "chain_valid": chain_valid,
            "chain_message": chain_message,
            "block": None,
            "signature_valid": False,
        }

    return build_verification_result(block.document_hash, issuer_id=block.issuer_id if block.issuer_id else None)


@app.get("/api/certificates/{certificate_id}/download")
def download_certificate(
    certificate_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> FileResponse:
    block = load_blockchain().find_by_certificate_id(certificate_id)
    if not block or not block.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
    if user["role"] == "verifier" or (user["role"] == "issuer" and block.owner != user["username"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")

    path = Path(block.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate file not found")

    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/users")
def users(user: dict[str, Any] = Depends(require_roles("admin"))) -> dict[str, Any]:
    return {"users": list_users(), "roles": ["admin", "issuer", "verifier"]}


@app.post("/api/users")
def add_user(payload: CreateUserRequest, user: dict[str, Any] = Depends(require_roles("admin"))) -> dict[str, str]:
    if not payload.username.strip() or not payload.password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username and password are required")
    try:
        create_user(payload.username.strip(), payload.password, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role") from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    return {"message": f"Created user {payload.username.strip()}"}


@app.put("/api/users/{user_id}")
def edit_user(
    user_id: int,
    payload: UpdateUserRequest,
    user: dict[str, Any] = Depends(require_roles("admin")),
) -> dict[str, str]:
    username = payload.username.strip()
    password = payload.password.strip() if payload.password else None
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    try:
        update_user(user_id, username, payload.role, password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    return {"message": f"Updated user {username}"}


@app.delete("/api/users/{user_id}")
def remove_user(
    user_id: int,
    user: dict[str, Any] = Depends(require_roles("admin")),
) -> dict[str, str]:
    if user_id == user["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete current user")
    try:
        delete_user(user_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    return {"message": "Deleted user"}


@app.get("/api/issuers")
def list_all_issuers(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """List all available issuers. Anyone can view the list, but admin can manage them."""
    return {"issuers": list_issuers()}


@app.post("/api/issuers")
def create_issuer_endpoint(
    payload: CreateIssuerRequest,
    user: dict[str, Any] = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Create a new issuer with unique public/private key pair. Admin only."""
    if not payload.name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Issuer name is required")
    try:
        issuer = create_issuer(payload.name.strip())
        return {
            "message": f"Created issuer {payload.name.strip()}",
            "issuer": issuer,
        }
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Issuer name already exists") from exc


@app.delete("/api/issuers/{issuer_id}")
def delete_issuer_endpoint(
    issuer_id: int,
    user: dict[str, Any] = Depends(require_roles("admin")),
) -> dict[str, str]:
    """Delete an issuer. Admin only."""
    try:
        delete_issuer(issuer_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Issuer not found") from exc
    return {"message": "Deleted issuer"}


def build_verification_result(document_hash: str, user: dict[str, Any] | None = None, issuer_id: int | None = None) -> dict[str, Any]:
    blockchain = load_blockchain()
    chain_valid, chain_message = blockchain.verify_chain()
    block = blockchain.find_by_document_hash(document_hash)
    if not block:
        return {
            "status": "invalid",
            "title": "Không tìm thấy tài liệu",
            "detail": "Hash của tài liệu không tồn tại trên blockchain cục bộ.",
            "document_hash": document_hash,
            "chain_valid": chain_valid,
            "chain_message": chain_message,
            "block": None,
            "signature_valid": False,
        }

    # Get issuer's public key if issuer_id is provided
    public_key_pem = None
    if issuer_id:
        public_key_pem = get_issuer_public_key(issuer_id)
        if not public_key_pem:
            return {
                "status": "invalid",
                "title": "Issuer không tồn tại",
                "detail": f"Issuer với ID {issuer_id} không được tìm thấy.",
                "document_hash": document_hash,
                "chain_valid": chain_valid,
                "chain_message": chain_message,
                "block": None,
                "signature_valid": False,
            }
    # If no issuer specified, use the one from block
    elif block.issuer_id:
        public_key_pem = get_issuer_public_key(block.issuer_id)

    signature_valid = verify_signature(document_hash, block.signature, public_key_pem=public_key_pem)
    valid = chain_valid and signature_valid
    return {
        "status": "valid" if valid else "invalid",
        "title": "Chứng chỉ hợp lệ" if valid else "Chứng chỉ không hợp lệ",
        "detail": (
            "Hash tài liệu khớp với bản ghi blockchain và chữ ký số hợp lệ."
            if valid
            else "Tìm thấy hash, nhưng blockchain hoặc chữ ký số không vượt qua kiểm tra."
        ),
        "document_hash": document_hash,
        "chain_valid": chain_valid,
        "chain_message": chain_message,
        "block": block.__dict__,
        "signature_valid": signature_valid,
    }
