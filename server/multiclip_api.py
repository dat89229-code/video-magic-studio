"""Local rendering service for Master Clip's multi-clip music workflow.

Run with: .venv\\Scripts\\python.exe server\\multiclip_api.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import sqlite3
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
EXPORTS = ROOT / "output" / "multiclip"
EXPORTS.mkdir(parents=True, exist_ok=True)
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
DATABASE = DATA / "studio.db"

PLANS = {
    "starter": {"name": "Starter", "amount": 49000, "credits": 10},
    "pro": {"name": "Pro", "amount": 129000, "credits": 35},
    "studio": {"name": "Studio", "amount": 349000, "credits": 120},
}

app = FastAPI(title="Master Clip local renderer")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/exports", StaticFiles(directory=EXPORTS), name="exports")


def connection() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE)
    database.row_factory = sqlite3.Row
    return database


def initialize_database() -> None:
    with connection() as database:
        database.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 3
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
                plan_key TEXT NOT NULL, amount INTEGER NOT NULL, credits INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS payment_transactions (
                provider_id TEXT PRIMARY KEY, order_code TEXT NOT NULL,
                amount INTEGER NOT NULL, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)


initialize_database()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split(":", 1)
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return secrets.compare_digest(candidate.hex(), digest_hex)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


def serialize_user(row: sqlite3.Row) -> dict[str, object]:
    return {"id": row["id"], "email": row["email"], "credits": row["credits"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connection() as database:
        database.execute("INSERT INTO sessions(token, user_id) VALUES (?, ?)", (token, user_id))
    return token


def current_user(authorization: str | None = Header(default=None)) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Hãy đăng nhập để dùng công năng này.")
    with connection() as database:
        user = database.execute(
            "SELECT users.id, users.email, users.credits FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token=?",
            (authorization.removeprefix("Bearer "),),
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập đã hết hạn.")
    return user


@app.post("/auth/register")
def register(credentials: Credentials) -> dict[str, object]:
    try:
        with connection() as database:
            cursor = database.execute(
                "INSERT INTO users(email, password_hash) VALUES (?, ?)",
                (credentials.email.lower(), hash_password(credentials.password)),
            )
            user = database.execute("SELECT id, email, credits FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Email này đã được đăng ký.") from error
    return {"token": create_session(user["id"]), "user": serialize_user(user)}


@app.post("/auth/login")
def login(credentials: Credentials) -> dict[str, object]:
    with connection() as database:
        user = database.execute("SELECT id, email, credits, password_hash FROM users WHERE email=?", (credentials.email.lower(),)).fetchone()
    if user is None or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng.")
    return {"token": create_session(user["id"]), "user": serialize_user(user)}


@app.get("/auth/me")
def profile(user: sqlite3.Row = Depends(current_user)) -> dict[str, object]:
    return serialize_user(user)


def bank_configuration() -> dict[str, str]:
    required = {"bank": os.getenv("PAYMENT_BANK_CODE", ""), "account": os.getenv("PAYMENT_ACCOUNT_NUMBER", ""), "name": os.getenv("PAYMENT_ACCOUNT_NAME", "")}
    if not all(required.values()):
        raise HTTPException(status_code=503, detail="Chưa cấu hình tài khoản nhận thanh toán.")
    return required


@app.get("/plans")
def plans() -> dict[str, object]:
    return {"plans": [{"key": key, **plan} for key, plan in PLANS.items()]}


@app.post("/orders/{plan_key}")
def create_order(plan_key: str, user: sqlite3.Row = Depends(current_user)) -> dict[str, object]:
    plan = PLANS.get(plan_key)
    if plan is None:
        raise HTTPException(status_code=404, detail="Gói không tồn tại.")
    bank = bank_configuration()
    code = f"VMS{uuid.uuid4().hex[:8].upper()}"
    with connection() as database:
        database.execute("INSERT INTO orders(code, user_id, plan_key, amount, credits) VALUES (?, ?, ?, ?, ?)", (code, user["id"], plan_key, plan["amount"], plan["credits"]))
    query = urlencode({"amount": plan["amount"], "addInfo": code, "accountName": bank["name"]})
    qr_url = f"https://img.vietqr.io/image/{bank['bank']}-{bank['account']}-compact2.jpg?{query}"
    return {"code": code, "plan": plan, "bank": bank, "qr_url": qr_url}


@app.post("/payments/sepay/webhook")
async def receive_sepay_webhook(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict[str, bool]:
    webhook_key = os.getenv("SEPAY_WEBHOOK_API_KEY", "")
    if not webhook_key or (authorization != f"Bearer {webhook_key}" and x_api_key != webhook_key):
        raise HTTPException(status_code=401, detail="Webhook không hợp lệ.")
    payload = await request.json()
    provider_id = str(payload.get("id") or payload.get("transaction_id") or "")
    content = str(payload.get("content") or payload.get("transfer_content") or "").upper()
    amount = int(payload.get("transferAmount") or payload.get("amount_in") or payload.get("amount") or 0)
    if not provider_id or amount <= 0:
        raise HTTPException(status_code=400, detail="Dữ liệu giao dịch thiếu mã hoặc số tiền.")
    with connection() as database:
        if database.execute("SELECT 1 FROM payment_transactions WHERE provider_id=?", (provider_id,)).fetchone():
            return {"ok": True}
        order = database.execute("SELECT * FROM orders WHERE status='pending' AND ? LIKE '%' || code || '%'", (content,)).fetchone()
        if order is None or amount < order["amount"]:
            return {"ok": True}
        database.execute("INSERT INTO payment_transactions(provider_id, order_code, amount) VALUES (?, ?, ?)", (provider_id, order["code"], amount))
        database.execute("UPDATE orders SET status='paid', paid_at=CURRENT_TIMESTAMP WHERE id=?", (order["id"],))
        database.execute("UPDATE users SET credits=credits+? WHERE id=?", (order["credits"], order["user_id"]))
    return {"ok": True}


def run(*command: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-2000:])


def music_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(completed.stdout.strip())


def render(clips: list[Path], music: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="master-clip-") as directory:
        workspace = Path(directory)
        duration = min(max(music_duration(music), 8), 60)
        segment_duration = max(1.5, min(4.0, duration / len(clips)))
        segments: list[Path] = []
        for index, clip in enumerate(clips):
            segment = workspace / f"segment-{index:02d}.mp4"
            run(
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip), "-t", f"{segment_duration:.3f}",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,eq=contrast=1.08:saturation=1.08",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(segment),
            )
            segments.append(segment)
        manifest = workspace / "concat.txt"
        manifest.write_text("".join(f"file '{segment.as_posix()}'\\n" for segment in segments), encoding="utf-8")
        video_only = workspace / "video-only.mp4"
        run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(video_only))
        filename = f"multiclip-{uuid.uuid4().hex[:8]}.mp4"
        destination = EXPORTS / filename
        run(
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(music), "-i", str(video_only),
            "-filter:a", "volume=0.9", "-map", "1:v:0", "-map", "0:a:0", "-shortest",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(destination),
        )
        return filename


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/render")
async def render_multiclip(clips: list[UploadFile] = File(...), music: UploadFile = File(...), user: sqlite3.Row = Depends(current_user)) -> dict[str, object]:
    if not clips or not music.filename:
        raise HTTPException(status_code=400, detail="Cần ít nhất một clip và một file nhạc.")
    if user["credits"] < 1:
        raise HTTPException(status_code=402, detail="Bạn đã hết credit. Hãy mua thêm để tiếp tục dựng video.")
    with tempfile.TemporaryDirectory(prefix="master-upload-") as directory:
        uploads = Path(directory)
        clip_paths = []
        for index, clip in enumerate(clips):
            path = uploads / f"clip-{index}{Path(clip.filename or '.mp4').suffix}"
            path.write_bytes(await clip.read())
            clip_paths.append(path)
        music_path = uploads / f"music{Path(music.filename).suffix}"
        music_path.write_bytes(await music.read())
        try:
            filename = await asyncio.to_thread(render, clip_paths, music_path)
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Không thể dựng video: {error}") from error
    with connection() as database:
        database.execute("UPDATE users SET credits=credits-1 WHERE id=?", (user["id"],))
        credits = database.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()["credits"]
    return {"url": f"http://127.0.0.1:8787/exports/{filename}", "credits": credits}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
