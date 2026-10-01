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

from server.database import connection as database_connection
from server.database import is_postgres

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

app = FastAPI(title="Master Clip renderer")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:5174").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/exports", StaticFiles(directory=EXPORTS), name="exports")


def connection():
    return database_connection(DATABASE)


def initialize_database() -> None:
    with connection() as database:
        schema = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 3
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS payment_orders (
                id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
                order_type TEXT NOT NULL DEFAULT 'CREDIT_TOPUP' CHECK(order_type IN ('SKILL_PURCHASE','CREDIT_TOPUP')),
                plan_key TEXT, skill_slug TEXT, amount INTEGER NOT NULL, credits INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                paid_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS payment_transactions (
                provider_id TEXT PRIMARY KEY, order_code TEXT NOT NULL,
                amount INTEGER NOT NULL, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS skill_categories (
                id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL, slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL, tag TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 50000, status TEXT NOT NULL DEFAULT 'active',
                legacy_tool TEXT, sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(category_id) REFERENCES skill_categories(id)
            );
            CREATE TABLE IF NOT EXISTS skill_purchases (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, skill_id INTEGER NOT NULL,
                order_code TEXT UNIQUE NOT NULL, purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, skill_id), FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(skill_id) REFERENCES skills(id)
            );
            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, delta INTEGER NOT NULL,
                reason TEXT NOT NULL, order_code TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """
        if is_postgres():
            schema = schema.replace("id INTEGER PRIMARY KEY", "id BIGSERIAL PRIMARY KEY")
        database.executescript(schema)
        # This is deliberately additive: an already-running staging database can
        # gain the explicit order type without losing any existing test data.
        if is_postgres():
            database.execute(
                "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS order_type TEXT NOT NULL DEFAULT 'CREDIT_TOPUP'"
            )
        else:
            columns = database.execute("PRAGMA table_info(payment_orders)").fetchall()
            if "order_type" not in {column["name"] for column in columns}:
                database.execute(
                    "ALTER TABLE payment_orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'CREDIT_TOPUP'"
                )
        database.execute(
            "UPDATE payment_orders SET order_type='SKILL_PURCHASE' "
            "WHERE skill_slug IS NOT NULL AND order_type != 'SKILL_PURCHASE'"
        )
        seed_skills(database)


def seed_skills(database) -> None:
    categories = [
        ("photo-ai", "Sửa ảnh AI", "Biến ảnh sản phẩm và chân dung chỉ trong vài bước."),
        ("image-ai", "Tạo ảnh AI", "Tạo visual đẹp, đồng nhất với thương hiệu."),
        ("video-edit", "Edit Video", "Cắt, dựng và đóng gói video bán hàng."),
        ("video-viral", "Video AI/Viral", "Thiết kế nội dung ngắn có khả năng lan tỏa."),
        ("marketing", "Marketing & Social Media", "Xây kênh và vận hành nội dung thông minh."),
    ]
    for index, (slug, name, description) in enumerate(categories):
        database.execute(
            "INSERT INTO skill_categories(slug,name,description,sort_order) VALUES (?,?,?,?) ON CONFLICT(slug) DO NOTHING",
            (slug, name, description, index),
        )
    skills = [
        ("thuong-hieu-ca-nhan","photo-ai","Thương hiệu cá nhân & Text Overlay","Tạo lớp chữ và hình ảnh nhất quán cho thương hiệu.","Ảnh",None),
        ("poster-san-pham","photo-ai","Poster sản phẩm","Thiết kế poster sản phẩm thu hút cho chiến dịch.","Ảnh",None),
        ("xoa-nen-anh","photo-ai","Xóa nền ảnh","Tách chủ thể sạch sẽ, sẵn sàng cho mọi bối cảnh.","Ảnh",None),
        ("xoa-logo-anh","photo-ai","Xóa logo, vật thể","Làm sạch chi tiết thừa trong ảnh sản phẩm.","Ảnh",None),
        ("chinh-sua-anh","photo-ai","Chỉnh sửa ảnh","Làm nét, cân sáng và nâng chất lượng ảnh.","Ảnh",None),
        ("tang-chat-luong-4k","photo-ai","Tăng chất lượng 4K","Nâng độ phân giải ảnh một cách tự nhiên.","Ảnh",None),
        ("multishot","image-ai","Multishot","Tạo nhiều góc hình đồng bộ cho một ý tưởng.","AI Image",None),
        ("hoan-doi-nhan-vat","image-ai","Hoán đổi nhân vật","Thay đổi nhân vật trong bố cục hình ảnh.","AI Image",None),
        ("dang-1-thoai-thumbnail","video-edit","Talking-head cơ bản","Cắt gọn video nói chuyện và tạo thumbnail mở đầu.","Video","talking-head"),
        ("dang-2-hieu-ung-cao-cap","video-edit","Talking-head hiệu ứng cao cấp","Nâng cấp nhịp dựng, zoom, overlay và caption.","Video",None),
        ("dang-3-huong-dan-toi-gian","video-edit","Video hướng dẫn tối giản","Định dạng guide tinh gọn, tập trung vào nội dung.","Video",None),
        ("dang-4-infographic-trang","video-edit","Talking-head infographic","Video nói chuyện cùng các lớp infographic sáng.","Video",None),
        ("cap-do-1-khung-don","video-edit","Video dài → Short","Tìm và cắt các đoạn hay từ video dài thành short.","Video","long-to-short"),
        ("cap-do-2-postcard-2-nguoi","video-edit","Podcast 2 người → Short","Khung postcard linh hoạt cho podcast hai người.","Video",None),
        ("multiclip-ghep-nhac-trend","video-edit","Nhiều clip + Nhạc trend","Ghép nhiều clip thành video dọc theo nhịp nhạc.","Video","multiclip"),
        ("multiclip-1-video-highlight","video-edit","AI cắt highlight theo nhạc","Tự chọn highlight đẹp và đồng bộ nhịp nhạc.","Video",None),
        ("edit-video-zoom","video-edit","Edit video Zoom tự động","Đóng gói buổi Zoom dài thành series rõ ràng.","Video",None),
        ("video-tu-dong-google-flow","video-viral","Tạo video AI với Flow","Biến ý tưởng và tư liệu thành video AI.","AI Video",None),
        ("tao-video-viral","video-viral","Tạo video viral","Tạo video dọc viral cho quảng cáo và kênh bán hàng.","AI Video",None),
        ("reel-facebook-viral","video-viral","Xây kênh Facebook Reels","Quy trình tạo Reels có chiến lược cho thương hiệu.","Viral",None),
        ("subagent-cham-soc","marketing","Subagent chăm sóc khách hàng","Trợ lý AI hỗ trợ vận hành và chăm sóc khách.","Agent",None),
        ("subagent-nghien-cuu","marketing","Subagent nghiên cứu","Thu thập insight để chuẩn bị nội dung nhanh hơn.","Agent",None),
        ("seo-video-youtube","marketing","SEO video YouTube","Tối ưu tiêu đề, mô tả và cơ hội tìm kiếm.","SEO",None),
        ("dang-bai-tu-dong-da-kenh","marketing","Viết & đăng bài đa kênh","Viết đúng giọng và chuẩn bị nội dung đa nền tảng.","Social",None),
    ]
    for index, (slug, category, title, description, tag, legacy) in enumerate(skills):
        category_id = database.execute("SELECT id FROM skill_categories WHERE slug=?", (category,)).fetchone()["id"]
        database.execute(
            "INSERT INTO skills(category_id,slug,title,description,tag,legacy_tool,sort_order) VALUES (?,?,?,?,?,?,?) ON CONFLICT(slug) DO NOTHING",
            (category_id, slug, title, description, tag, legacy, index),
        )


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


def serialize_user(row) -> dict[str, object]:
    return {"id": row["id"], "email": row["email"], "credits": row["credits"]}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with connection() as database:
        database.execute("INSERT INTO sessions(token, user_id) VALUES (?, ?)", (token, user_id))
    return token


def current_user(authorization: str | None = Header(default=None)):
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
            user = database.execute(
                "INSERT INTO users(email, password_hash) VALUES (?, ?) RETURNING id, email, credits",
                (credentials.email.lower(), hash_password(credentials.password)),
            ).fetchone()
    except Exception as error:
        if "unique" not in str(error).lower():
            raise
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
def profile(user=Depends(current_user)) -> dict[str, object]:
    return serialize_user(user)


def bank_configuration() -> dict[str, str]:
    required = {"bank": os.getenv("PAYMENT_BANK_CODE", ""), "account": os.getenv("PAYMENT_ACCOUNT_NUMBER", ""), "name": os.getenv("PAYMENT_ACCOUNT_NAME", "")}
    if not all(required.values()):
        raise HTTPException(status_code=503, detail="Chưa cấu hình tài khoản nhận thanh toán.")
    return required


@app.get("/plans")
def plans() -> dict[str, object]:
    return {"plans": [{"key": key, **plan} for key, plan in PLANS.items()]}


@app.get("/skills")
def list_skills() -> dict[str, object]:
    with connection() as database:
        rows = database.execute(
            "SELECT skills.slug,skills.title,skills.description,skills.tag,skills.price,skills.status,"
            "skills.legacy_tool,skill_categories.name AS hall FROM skills JOIN skill_categories "
            "ON skills.category_id=skill_categories.id WHERE skills.status!='hidden' ORDER BY skills.sort_order"
        ).fetchall()
    return {"skills": [dict(row) for row in rows]}


@app.get("/skills/mine")
def my_skills(user=Depends(current_user)) -> dict[str, object]:
    with connection() as database:
        rows = database.execute(
            "SELECT skills.slug,skills.title,skills.description,skills.tag,skills.price,skills.status,"
            "skills.legacy_tool,skill_categories.name AS hall FROM skill_purchases "
            "JOIN skills ON skills.id=skill_purchases.skill_id JOIN skill_categories "
            "ON skills.category_id=skill_categories.id WHERE skill_purchases.user_id=? ORDER BY skill_purchases.purchased_at DESC",
            (user["id"],),
        ).fetchall()
    return {"skills": [dict(row) for row in rows]}


@app.post("/skills/{slug}/orders")
def create_skill_order(slug: str, user=Depends(current_user)) -> dict[str, object]:
    bank = bank_configuration()
    with connection() as database:
        skill = database.execute("SELECT * FROM skills WHERE slug=? AND status='active'", (slug,)).fetchone()
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill không tồn tại hoặc đang tạm ẩn.")
        owned = database.execute(
            "SELECT 1 FROM skill_purchases WHERE user_id=? AND skill_id=?", (user["id"], skill["id"])
        ).fetchone()
        if owned:
            raise HTTPException(status_code=409, detail="Bạn đã sở hữu Skill này.")
        code = f"MCS{uuid.uuid4().hex[:8].upper()}"
        database.execute(
            "INSERT INTO payment_orders(code,user_id,order_type,skill_slug,amount,credits) VALUES (?,?,'SKILL_PURCHASE',?,?,0)",
            (code, user["id"], slug, skill["price"]),
        )
    query = urlencode({"amount": skill["price"], "addInfo": code, "accountName": bank["name"]})
    return {"code": code, "skill": {"slug": slug, "title": skill["title"], "price": skill["price"]}, "bank": bank,
            "qr_url": f"https://img.vietqr.io/image/{bank['bank']}-{bank['account']}-compact2.jpg?{query}"}


@app.post("/orders/{plan_key}")
def create_order(plan_key: str, user=Depends(current_user)) -> dict[str, object]:
    plan = PLANS.get(plan_key)
    if plan is None:
        raise HTTPException(status_code=404, detail="Gói không tồn tại.")
    bank = bank_configuration()
    code = f"VMS{uuid.uuid4().hex[:8].upper()}"
    with connection() as database:
        database.execute(
            "INSERT INTO payment_orders(code,user_id,order_type,plan_key,amount,credits) VALUES (?,?,'CREDIT_TOPUP',?,?,?)",
            (code, user["id"], plan_key, plan["amount"], plan["credits"]),
        )
    query = urlencode({"amount": plan["amount"], "addInfo": code, "accountName": bank["name"]})
    qr_url = f"https://img.vietqr.io/image/{bank['bank']}-{bank['account']}-compact2.jpg?{query}"
    return {"code": code, "plan": plan, "bank": bank, "qr_url": qr_url}


@app.post("/payments/sepay/webhook")
async def receive_sepay_webhook(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> dict[str, bool]:
    webhook_key = os.getenv("SEPAY_WEBHOOK_API_KEY", "")
    accepted_authorization = {f"Bearer {webhook_key}", f"Apikey {webhook_key}"}
    if not webhook_key or (authorization not in accepted_authorization and x_api_key != webhook_key):
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
        order = database.execute("SELECT * FROM payment_orders WHERE status='pending' AND ? LIKE '%' || code || '%'", (content,)).fetchone()
        if order is None or amount < order["amount"]:
            return {"ok": True}
        if order["order_type"] not in {"SKILL_PURCHASE", "CREDIT_TOPUP"}:
            raise HTTPException(status_code=409, detail="Loại đơn thanh toán không hợp lệ.")
        database.execute("INSERT INTO payment_transactions(provider_id, order_code, amount) VALUES (?, ?, ?)", (provider_id, order["code"], amount))
        database.execute("UPDATE payment_orders SET status='paid', paid_at=CURRENT_TIMESTAMP WHERE id=?", (order["id"],))
        if order["order_type"] == "SKILL_PURCHASE":
            if not order["skill_slug"]:
                raise HTTPException(status_code=409, detail="Đơn mua Skill thiếu Skill cần mở khóa.")
            skill = database.execute("SELECT id FROM skills WHERE slug=?", (order["skill_slug"],)).fetchone()
            if skill is None:
                raise HTTPException(status_code=409, detail="Skill trong đơn không còn tồn tại.")
            database.execute(
                "INSERT INTO skill_purchases(user_id,skill_id,order_code) VALUES (?,?,?) ON CONFLICT(user_id,skill_id) DO NOTHING",
                (order["user_id"], skill["id"], order["code"]),
            )
        elif order["order_type"] == "CREDIT_TOPUP":
            database.execute("UPDATE users SET credits=credits+? WHERE id=?", (order["credits"], order["user_id"]))
            database.execute("INSERT INTO credit_transactions(user_id, delta, reason, order_code) VALUES (?, ?, ?, ?)", (order["user_id"], order["credits"], "credit_purchase", order["code"]))
    return {"ok": True}


@app.get("/orders/{code}")
def order_status(code: str, user=Depends(current_user)) -> dict[str, object]:
    with connection() as database:
        order = database.execute(
            "SELECT code,order_type,skill_slug,amount,credits,status,paid_at FROM payment_orders WHERE code=? AND user_id=?",
            (code, user["id"]),
        ).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn thanh toán.")
    return dict(order)


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


def has_audio_stream(path: Path) -> bool:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(completed.stdout.strip())


def render(clips: list[Path], music: Path) -> str:
    if not has_audio_stream(music):
        raise ValueError("File nhạc không có âm thanh. Hãy chọn MP3, WAV hoặc M4A có tiếng.")
    with tempfile.TemporaryDirectory(prefix="master-clip-") as directory:
        workspace = Path(directory)
        duration = min(max(music_duration(music), 8), 60)
        segment_duration = max(1.5, min(4.0, duration / len(clips)))
        segments: list[Path] = []
        for index, clip in enumerate(clips):
            segment = workspace / f"segment-{index:02d}.mp4"
            run(
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(clip), "-t", f"{segment_duration:.3f}",
                # Staging runs on Render's small free instance. Keep this output
                # vertical and pleasant while avoiding a memory spike from 1080p
                # encoding. Production workers can raise this to 1080x1920.
                "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=24,eq=contrast=1.08:saturation=1.08",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "28", "-threads", "1", str(segment),
            )
            segments.append(segment)
        manifest = workspace / "concat.txt"
        manifest.write_text("".join(f"file '{segment.as_posix()}'\n" for segment in segments), encoding="utf-8")
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
def health() -> dict[str, object]:
    try:
        with connection() as database:
            database.execute("SELECT 1").fetchone()
    except Exception as error:
        raise HTTPException(status_code=503, detail="Không thể kết nối cơ sở dữ liệu.") from error
    return {"ok": True, "database": "postgres" if is_postgres() else "sqlite"}


@app.post("/render")
async def render_multiclip(
    request: Request,
    clips: list[UploadFile] = File(...),
    music: UploadFile = File(...),
    user=Depends(current_user),
) -> dict[str, object]:
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
        debited = database.execute("UPDATE users SET credits=credits-1 WHERE id=? AND credits>=1", (user["id"],))
        if debited.rowcount != 1:
            raise HTTPException(status_code=402, detail="Bạn không đủ credit. Hãy nạp credit để tiếp tục.")
        database.execute(
            "INSERT INTO credit_transactions(user_id,delta,reason) VALUES (?,?,'multiclip_render')",
            (user["id"], -1),
        )
        credits = database.execute("SELECT credits FROM users WHERE id=?", (user["id"],)).fetchone()["credits"]
    return {"url": f"{str(request.base_url).rstrip('/')}/exports/{filename}", "credits": credits}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8787)
