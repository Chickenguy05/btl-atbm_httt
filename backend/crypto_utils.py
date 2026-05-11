from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


ROOT_DIR = Path(__file__).resolve().parent.parent
KEY_DIR = ROOT_DIR / "keys"
PRIVATE_KEY_PATH = KEY_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEY_DIR / "public_key.pem"


def ensure_key_pair() -> None:
    KEY_DIR.mkdir(exist_ok=True)
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PUBLIC_KEY_PATH.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def generate_key_pair_pem() -> tuple[str, str]:
    """Generate a new RSA key pair and return as PEM strings."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def save_issuer_keys(issuer_id: str, private_key_pem: str, public_key_pem: str) -> None:
    """Save issuer's key pair to files."""
    issuer_dir = KEY_DIR / str(issuer_id)
    issuer_dir.mkdir(exist_ok=True)
    
    private_path = issuer_dir / "private_key.pem"
    public_path = issuer_dir / "public_key.pem"
    
    private_path.write_text(private_key_pem)
    public_path.write_text(public_key_pem)


def load_issuer_private_key(issuer_id: str):
    """Load private key for a specific issuer."""
    issuer_dir = KEY_DIR / str(issuer_id)
    private_path = issuer_dir / "private_key.pem"
    
    if not private_path.exists():
        raise FileNotFoundError(f"Private key not found for issuer {issuer_id}")
    
    return serialization.load_pem_private_key(private_path.read_bytes(), password=None)


def load_issuer_public_key_from_pem(public_key_pem: str):
    """Load public key from PEM string."""
    return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_private_key():
    ensure_key_pair()
    return serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)


def load_public_key():
    ensure_key_pair()
    return serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())


def sign_hash(document_hash: str, issuer_id: str | None = None) -> str:
    """Sign a document hash with the system key or issuer's key."""
    if issuer_id:
        private_key = load_issuer_private_key(issuer_id)
    else:
        private_key = load_private_key()
    
    signature = private_key.sign(
        document_hash.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify_signature(document_hash: str, signature_b64: str, public_key_pem: str | None = None) -> bool:
    """Verify a signature with the system key or provided issuer public key."""
    if public_key_pem:
        public_key = load_issuer_public_key_from_pem(public_key_pem)
    else:
        public_key = load_public_key()
    
    try:
        public_key.verify(
            base64.b64decode(signature_b64.encode("ascii")),
            document_hash.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError):
        return False
