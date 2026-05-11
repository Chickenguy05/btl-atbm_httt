from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from werkzeug.security import generate_password_hash

from .blockchain import Block, DocumentBlockchain
from .crypto_utils import generate_key_pair_pem, save_issuer_keys


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "documents.db"
BLOCKCHAIN_FILE = ROOT_DIR / "data" / "blockchain.json"
ROLES = {"admin", "issuer", "verifier"}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL NOT NULL,
                document_hash TEXT NOT NULL,
                document_name TEXT NOT NULL,
                owner TEXT NOT NULL,
                signature TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                certificate_id TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                file_path TEXT DEFAULT '',
                qr_path TEXT DEFAULT '',
                nonce INTEGER NOT NULL,
                hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'issuer', 'verifier')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issuers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                public_key TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        migrate_blocks(conn)
        migrate_user_roles(conn)
        admin_exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            ("admin",),
        ).fetchone()
        if not admin_exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin"),
            )


def migrate_blocks(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(blocks)").fetchall()}
    migrations = {
        "certificate_id": "ALTER TABLE blocks ADD COLUMN certificate_id TEXT DEFAULT ''",
        "metadata": "ALTER TABLE blocks ADD COLUMN metadata TEXT DEFAULT '{}'",
        "file_path": "ALTER TABLE blocks ADD COLUMN file_path TEXT DEFAULT ''",
        "qr_path": "ALTER TABLE blocks ADD COLUMN qr_path TEXT DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)


def migrate_user_roles(conn: sqlite3.Connection) -> None:
    columns = conn.execute("PRAGMA table_info(users)").fetchall()
    if not columns:
        return

    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    sql = table_sql["sql"] if table_sql is not None else ""
    needs_rebuild = table_sql is not None and "'issuer'" not in (sql or "")

    if needs_rebuild:
        conn.execute("ALTER TABLE users RENAME TO users_old")
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'issuer', 'verifier')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO users (id, username, password_hash, role, created_at)
            SELECT id, username, password_hash,
                   CASE role
                       WHEN 'user' THEN 'issuer'
                       WHEN 'isser' THEN 'issuer'
                       WHEN 'viewer' THEN 'verifier'
                       ELSE role
                   END,
                   created_at
            FROM users_old
            """
        )
        conn.execute("DROP TABLE users_old")
    else:
        conn.execute("UPDATE users SET role = 'issuer' WHERE role IN ('user', 'isser')")
        conn.execute("UPDATE users SET role = 'verifier' WHERE role = 'viewer'")
        invalid_roles = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role NOT IN ('admin', 'issuer', 'verifier')"
        ).fetchone()[0]
        if invalid_roles:
            raise ValueError("Invalid role exists in users table")


def load_blockchain() -> DocumentBlockchain:
    BLOCKCHAIN_FILE.parent.mkdir(exist_ok=True)
    if BLOCKCHAIN_FILE.exists():
        with open(BLOCKCHAIN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        blocks = [
            Block(
                index=block_data["index"],
                timestamp=block_data["timestamp"],
                document_hash=block_data["document_hash"],
                document_name=block_data["document_name"],
                owner=block_data["owner"],
                signature=block_data["signature"],
                previous_hash=block_data["previous_hash"],
                certificate_id=block_data.get("certificate_id", ""),
                metadata=block_data.get("metadata"),
                file_path=block_data.get("file_path", ""),
                qr_path=block_data.get("qr_path", ""),
                nonce=block_data["nonce"],
                hash=block_data["hash"],
                issuer_id=block_data.get("issuer_id", 0),
            )
            for block_data in data
        ]
        blockchain = DocumentBlockchain(blocks=blocks)
    else:
        # Try to migrate from SQLite
        init_db()
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM blocks ORDER BY block_index").fetchall()
        if rows:
            blocks = [
                Block(
                    index=row["block_index"],
                    timestamp=row["timestamp"],
                    document_hash=row["document_hash"],
                    document_name=row["document_name"],
                    owner=row["owner"],
                    signature=row["signature"],
                    previous_hash=row["previous_hash"],
                    certificate_id=row["certificate_id"] or "",
                    metadata=json.loads(row["metadata"] or "{}"),
                    file_path=row["file_path"] or "",
                    qr_path=row["qr_path"] or "",
                    nonce=row["nonce"],
                    hash=row["hash"],
                    issuer_id=getattr(row, "issuer_id", 0) or 0,
                )
                for row in rows
            ]
            blockchain = DocumentBlockchain(blocks=blocks)
            save_blockchain(blockchain)
            print("Migrated blockchain from SQLite to JSON")
        else:
            blockchain = DocumentBlockchain()
            save_blockchain(blockchain)
    return blockchain


def save_block(block: Block) -> None:
    blockchain = load_blockchain()
    # Ensure the block is added if not already present
    if not any(b.index == block.index for b in blockchain.chain):
        blockchain.chain.append(block)
    save_blockchain(blockchain)


def save_blockchain(blockchain: DocumentBlockchain) -> None:
    BLOCKCHAIN_FILE.parent.mkdir(exist_ok=True)
    data = [block.__dict__ for block in blockchain.chain]
    with open(BLOCKCHAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_blocks() -> list[dict]:
    blockchain = load_blockchain()
    return [json.loads(json.dumps(block.__dict__)) for block in reversed(blockchain.chain)]


def list_blocks_for_user(user: dict[str, Any]) -> list[dict]:
    blocks = list_blocks()
    if user["role"] == "admin":
        return blocks
    if user["role"] == "issuer":
        return [block for block in blocks if block["owner"] == user["username"]]
    return []


def find_user_by_username(username: str) -> sqlite3.Row | None:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE username = ?",
            (username,),
        ).fetchone()


def find_user_by_id(user_id: int) -> sqlite3.Row | None:
    init_db()
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, role, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def list_users() -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def create_user(username: str, password: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError("Invalid role")
    init_db()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )


def update_user(user_id: int, username: str, role: str, password: str | None = None) -> None:
    if role not in ROLES:
        raise ValueError("Invalid role")
    init_db()
    with get_connection() as conn:
        if password:
            conn.execute(
                """
                UPDATE users
                SET username = ?, role = ?, password_hash = ?
                WHERE id = ?
                """,
                (username, role, generate_password_hash(password), user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET username = ?, role = ? WHERE id = ?",
                (username, role, user_id),
            )
        if conn.total_changes == 0:
            raise LookupError("User not found")


def delete_user(user_id: int) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if conn.total_changes == 0:
            raise LookupError("User not found")


def create_issuer(name: str) -> dict[str, Any]:
    """Create a new issuer with unique public/private key pair."""
    init_db()
    
    # Generate key pair
    private_pem, public_pem = generate_key_pair_pem()
    
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO issuers (name, public_key) VALUES (?, ?)",
            (name, public_pem),
        )
        issuer_id = cursor.lastrowid
    
    # Save keys to files
    save_issuer_keys(issuer_id, private_pem, public_pem)
    
    return {
        "id": issuer_id,
        "name": name,
        "public_key": public_pem,
        "created_at": None,
    }


def list_issuers() -> list[dict[str, Any]]:
    """List all issuers."""
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, public_key, created_at FROM issuers ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def get_issuer_by_id(issuer_id: int) -> dict[str, Any] | None:
    """Get issuer by ID."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, name, public_key, created_at FROM issuers WHERE id = ?",
            (issuer_id,),
        ).fetchone()
    return dict(row) if row else None


def get_issuer_public_key(issuer_id: int) -> str | None:
    """Get issuer's public key."""
    issuer = get_issuer_by_id(issuer_id)
    return issuer["public_key"] if issuer else None


def delete_issuer(issuer_id: int) -> None:
    """Delete an issuer."""
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM issuers WHERE id = ?", (issuer_id,))
        if conn.total_changes == 0:
            raise LookupError("Issuer not found")
