"""Local rendering service for Master Clip's multi-clip music workflow.

Run with: .venv\\Scripts\\python.exe server\\multiclip_api.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
            CREATE TABLE IF NOT EXISTS skill_content (
                skill_id INTEGER PRIMARY KEY, content_state TEXT NOT NULL DEFAULT 'CONTENT_MISSING'
                    CHECK(content_state IN ('READY','CONTENT_MISSING')),
                preview_text TEXT, workflow_text TEXT, prompt_text TEXT, input_notes TEXT, output_notes TEXT,
                steps_text TEXT, notes_text TEXT,
                owned_sections_json TEXT,
                resource_url TEXT, tutorial_url TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
            for column in ("preview_text", "steps_text", "notes_text", "owned_sections_json"):
                database.execute(f"ALTER TABLE skill_content ADD COLUMN IF NOT EXISTS {column} TEXT")
        else:
            columns = database.execute("PRAGMA table_info(payment_orders)").fetchall()
            if "order_type" not in {column["name"] for column in columns}:
                database.execute(
                    "ALTER TABLE payment_orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'CREDIT_TOPUP'"
                )
            content_columns = {column["name"] for column in database.execute("PRAGMA table_info(skill_content)").fetchall()}
            for column in ("preview_text", "steps_text", "notes_text", "owned_sections_json"):
                if column not in content_columns:
                    database.execute(f"ALTER TABLE skill_content ADD COLUMN {column} TEXT")
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
        skill_id = database.execute("SELECT id FROM skills WHERE slug=?", (slug,)).fetchone()["id"]
        # No purchased resource was imported into this repository. Mark that fact
        # explicitly rather than manufacturing a workflow or prompt for customers.
        database.execute(
            "INSERT INTO skill_content(skill_id,content_state) VALUES (?,'CONTENT_MISSING') ON CONFLICT(skill_id) DO NOTHING",
            (skill_id,),
        )
    seed_brand_overlay_content(database)
    seed_verified_source_content(database)


def seed_brand_overlay_content(database) -> None:
    """Seed the customer-authorized source content for the first Skill.

    Account-specific links, seller contacts and payment UI are intentionally
    excluded; the purchased workflow itself is retained verbatim.
    """
    skill_id = database.execute(
        "SELECT id FROM skills WHERE slug='thuong-hieu-ca-nhan'"
    ).fetchone()["id"]
    preview = (
        "Từ một ảnh chân dung rõ mặt, tạo bộ 4 ảnh thương hiệu cá nhân với "
        "góc chụp, tư thế và ánh sáng đồng nhất để dùng cho mạng xã hội hoặc gian hàng."
    )
    workflow = (
        "Từ một tấm ảnh chân dung, tạo cả bộ ảnh thương hiệu cá nhân nhiều góc/tư thế "
        "khác nhau nhưng vẫn đúng một người. Thực hiện trực tiếp trên ChatGPT hoặc Gemini, "
        "không cần cài ComfyUI."
    )
    prompt = (
        "Đây là ảnh chân dung của tôi. Từ ảnh này, vẽ thêm cho tôi 4 tấm ảnh thương hiệu cá nhân khác góc/tư thế, "
        "GIỮ ĐÚNG khuôn mặt, kiểu tóc và trang phục như ảnh gốc:\n"
        "1. Chính diện, cười nhẹ, phông nền văn phòng mờ\n"
        "2. Nghiêng 3/4, tay khoanh trước ngực, phông nền xám trơn\n"
        "3. Toàn thân, đứng thẳng, phông nền ngoài trời\n"
        "4. Cận mặt, ánh sáng studio, phông nền đen\n\n"
        "Yêu cầu bắt buộc:\n"
        "- Giữ đúng khuôn mặt như ảnh gốc — đây là ảnh THẬT của tôi, không phải nhân vật hư cấu, sai mặt là không dùng được.\n"
        "- Đồng nhất tông màu và ánh sáng giữa 4 tấm, như chụp cùng một buổi.\n"
        "- Không đội thêm phụ kiện, không đổi màu tóc/da nếu tôi không yêu cầu.\n"
        "Sau khi ra 4 tấm, cho tôi biết tấm nào giữ mặt giống nhất và tấm nào bị lệch để tôi biết mà yêu cầu sửa lại."
    )
    steps = (
        "Bước 1 — Chọn ảnh chân dung rõ mặt nhất\n"
        "Chọn ảnh nhìn thẳng mặt, đủ sáng, không bị che — ảnh gốc càng rõ thì cả bộ ảnh sau càng giữ đúng mặt.\n\n"
        "Bước 2 — Tải ảnh lên rồi dán câu lệnh\n"
        "Bấm biểu tượng kẹp giấy để tải ảnh chân dung lên ChatGPT hoặc Gemini. Dán Prompt Master Clip rồi gửi.\n\n"
        "Bước 3 — Kiểm từng tấm, sửa riêng tấm bị lệch\n"
        "So từng tấm với ảnh gốc. Nếu một tấm lệch mặt, nhắn riêng trong cùng hội thoại: “Vẽ lại tấm số 3, giữ đúng mặt như ảnh gốc hơn.” Đừng làm lại cả bộ 4 tấm."
    )
    notes = (
        "AI giữ mặt tốt nhất trong khoảng 3–4 ảnh liên tiếp. Cần thêm góc thì làm thêm một lượt mới trong cùng hội thoại, "
        "không gộp quá nhiều ảnh vào một lần."
    )
    # These blocks are the customer-authorized source material, retained in
    # its original order.  Personal account links, seller contact details and
    # payment UI from the source are intentionally not imported.
    owned_sections = [
        {
            "number": "01",
            "title": "Skill này gồm những gì",
            "body": "Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có\n\nBản cài về máy cho ai cần\nMuốn xử lý hàng loạt trăm ảnh thì có sẵn hướng dẫn cài công cụ chuyên dụng",
        },
        {
            "number": "02",
            "title": "Chuẩn bị trước khi bắt đầu",
            "body": "Chọn ảnh nhìn thẳng mặt, đủ sáng, không bị che — ảnh gốc càng rõ thì cả bộ ảnh sau càng giữ đúng mặt. Dán câu lệnh vào ChatGPT hoặc Gemini kèm ảnh của bạn. Không cài gì, làm được cả trên điện thoại.",
        },
        {
            "number": "04",
            "title": "Làm theo 3 bước",
            "body": "Bước 1 — Chọn ảnh chân dung rõ mặt nhất\nChọn ảnh nhìn thẳng mặt, đủ sáng, không bị che — ảnh gốc càng rõ thì cả bộ ảnh sau càng giữ đúng mặt.\n\nBước 2 — Tải ảnh lên rồi dán câu lệnh\nBấm biểu tượng kẹp giấy để tải ảnh chân dung lên. Rồi dán câu lệnh vào, gửi.\n\nLưu ý: Chat AI giữ mặt tốt nhất trong khoảng 3-4 tấm liền một lượt — sinh nhiều hơn dễ bị trôi mặt dần. Cần thêm góc thì làm thêm một lượt mới trong CÙNG hội thoại, đừng gộp quá nhiều vào một lần.\n\nBước 3 — Kiểm từng tấm, sửa riêng tấm bị lệch\nSo từng tấm với ảnh gốc. Tấm nào lệch mặt thì nhắn riêng trong cùng hội thoại: 'Vẽ lại tấm số 3, giữ đúng mặt như ảnh gốc hơn.' Đừng làm lại cả bộ 4 tấm.",
        },
        {
            "number": "05",
            "title": "Làm thử ngay",
            "body": "Tạo bộ 4 ảnh thương hiệu cá nhân để đăng lên trang mạng xã hội bán hàng\n\n1. Chọn một ảnh chân dung rõ mặt nhất bạn có\n2. Làm theo 3 bước trên\n3. Xếp 4 ảnh cạnh nhau xem đã ra một bộ đồng nhất về mặt và tông màu chưa\n4. Đăng thử một tấm lên trang cá nhân hoặc gian hàng\n\nXong sẽ có: Bốn tấm ảnh khác góc/tư thế nhưng rõ ràng cùng một người, tông màu và ánh sáng đồng nhất như chụp cùng một buổi studio.",
        },
    ]
    database.execute(
        "UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, "
        "input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, "
        "updated_at=CURRENT_TIMESTAMP WHERE skill_id=?",
        (preview, workflow, prompt, "Một ảnh chân dung nhìn thẳng mặt, đủ sáng, không bị che.",
         "04 ảnh thương hiệu cá nhân đồng nhất về nhận diện, góc chụp và ánh sáng.", steps, notes,
         json.dumps(owned_sections, ensure_ascii=False), "https://github.com/comfyanonymous/ComfyUI", skill_id),
    )


def seed_verified_source_content(database) -> None:
    """Import only source Skills whose purchased content was verified verbatim.

    Source account links, payment information, seller contacts and licence codes
    are intentionally excluded.  This function is idempotent so existing owners
    keep their purchases while the owned lesson content is updated.
    """
    skill_id = database.execute("SELECT id FROM skills WHERE slug='poster-san-pham'").fetchone()["id"]
    prompt = """Tôi gửi ảnh sản phẩm của tôi. Hãy dựng cho tôi một bộ 10 poster quảng cáo đồng bộ, làm đúng như một art director quảng cáo thật.

Làm theo đúng thứ tự, ĐỪNG tạo ảnh ngay:

1. PHÂN TÍCH SẢN PHẨM trước. Mô tả cho tôi: loại sản phẩm, hình dáng, chất liệu, màu, chữ trên nhãn, góc nhìn nào là an toàn. Ghi rõ những gì BẮT BUỘC phải giữ nguyên.

2. VẠCH BẢN ĐỒ 10 CONCEPT khác nhau rồi đưa tôi xem trước. Mỗi concept ghi rõ: bối cảnh, ánh sáng, bảng màu, góc máy, có người mẫu hay không. Mười concept phải KHÁC NHAU rõ rệt, không được 10 tấm cùng một kiểu đặt giữa khung.

3. Chờ tôi duyệt rồi mới tạo ảnh.

Quy tắc không được phá:
- Giữ nguyên hình dáng, tỷ lệ, màu, chất liệu, nhãn mác và số lượng sản phẩm đúng như ảnh tôi gửi.
- Không thêm chữ, giá, khuyến mãi, logo hay watermark nào tôi không đưa. Nếu concept nào cần chữ, hỏi tôi chữ chính xác trước khi tạo.
- Không thêm thành phần, công dụng hay lời quảng cáo mà sản phẩm của tôi không có.

Tạo xong, tự soi lại từng tấm: tấm nào sản phẩm bị sai so với ảnh gốc thì làm lại tấm đó."""
    steps = """Bước 1 — Chuẩn bị một ảnh sản phẩm rõ
Máy nhìn được đúng sản phẩm của bạn.

Chụp hoặc chọn một ảnh thấy rõ toàn bộ sản phẩm, đọc được chữ trên nhãn, không bị loá sáng. Nền gì cũng được — bối cảnh sẽ thay hết.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
AI phân tích sản phẩm và đề xuất 10 concept.

Bấm kẹp giấy tải ảnh sản phẩm lên, bấm nút Chép ở đầu trang rồi dán câu lệnh vào, gửi.

Bước 3 — Duyệt bản đồ concept rồi cho chạy
Mười tấm khác nhau thật, đúng ý bạn.

Đọc 10 concept, thấy cái nào không hợp thì nói thẳng: “Concept 4 và 7 quá giống nhau, đổi concept 7 sang bối cảnh ngoài trời.” Ưng rồi thì bảo tạo ảnh.

Bước 4 — Soi lại sản phẩm trên từng tấm
Không tấm nào bịa sai sản phẩm.

Phóng to phần sản phẩm trên từng tấm, so với ảnh gốc: đúng màu chưa, đúng hình dáng chưa, chữ trên nhãn có bị bịa không."""
    notes = """Ảnh gốc mờ hoặc thiếu sáng thì mọi tấm poster đều thừa hưởng cái sai đó. Ảnh chưa rõ thì chạy Skill 'Tăng chất lượng 4k' trước.

AI sẽ KHÔNG tạo ảnh ngay — đúng như thiết kế. Nó phân tích và đưa bản đồ 10 concept trước. Đây là bước quyết định bộ ảnh có khác nhau hay không, đọc kỹ đừng bỏ qua.

Chữ trên nhãn là chỗ máy sai nhiều nhất. Tấm nào chữ bị méo hoặc bịa thì bảo làm lại riêng tấm đó, đừng làm lại cả bộ."""
    sections = [
        {"number": "01", "title": "Skill này gồm những gì", "body": "Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có\n\nBản cài về máy cho ai cần\nMuốn xử lý hàng loạt trăm ảnh thì có sẵn hướng dẫn cài công cụ chuyên dụng"},
        {"number": "02", "title": "Chuẩn bị trước khi bắt đầu", "body": "Chụp hoặc chọn một ảnh thấy rõ toàn bộ sản phẩm, đọc được chữ trên nhãn, không bị loá sáng. Nền gì cũng được — bối cảnh sẽ thay hết."},
        {"number": "04", "title": "Làm theo 4 bước", "body": steps},
        {"number": "05", "title": "Làm thử ngay", "body": "Dựng bộ 10 poster cho một sản phẩm bạn đang bán\n\n1. Chọn một sản phẩm bạn đang bán, chụp một ảnh rõ\n2. Làm theo 4 bước trên\n3. Đếm xem 10 tấm có thật sự khác nhau không, hay chỉ đổi màu nền\n4. Chọn 3 tấm ưng nhất, phóng to soi kỹ phần nhãn sản phẩm\n\nXong sẽ có: Mười poster khác nhau rõ rệt về bối cảnh và bố cục, nhưng sản phẩm trên cả mười tấm đều đúng như ảnh gốc."},
    ]
    database.execute(
        "UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=NULL, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?",
        ("Một ảnh sản phẩm ra nguyên bộ 10 poster quảng cáo đồng bộ, không cần cài gì", "Đưa MỘT ảnh sản phẩm, nhận về MỘT BỘ 10 poster quảng cáo khác nhau nhưng cùng một chất. Không cài gì — chạy thẳng trên ChatGPT hoặc Gemini bạn đang có.", prompt, "Một ảnh sản phẩm rõ: thấy toàn bộ sản phẩm, đọc được nhãn, không loá sáng.", "10 poster quảng cáo khác nhau về bối cảnh và bố cục, với sản phẩm giữ đúng ảnh gốc.", steps, notes, json.dumps(sections, ensure_ascii=False), skill_id),
    )

    skill_id = database.execute("SELECT id FROM skills WHERE slug='xoa-nen-anh'").fetchone()["id"]
    prompt = """Xoá nền bức ảnh này, chỉ giữ lại sản phẩm.

Yêu cầu bắt buộc:
- GIỮ NGUYÊN 100% sản phẩm: màu sắc, hình dáng, chi tiết, chữ trên bao bì. Không làm đẹp thêm, không chỉnh màu, không thêm bớt gì.
- Cắt viền sạch, không sót mảng nền. Chú ý kỹ chỗ khó: tóc, lông, quai xách, phần trong suốt như chai lọ thuỷ tinh.
- Xuất ra file PNG nền trong suốt.

Sau đó làm thêm bản thứ hai từ chính ảnh đã tách:
- Đặt sản phẩm lên nền trắng thuần, mã màu #FFFFFF
- Sản phẩm nằm chính giữa, chừa lề đều bốn phía khoảng 10%
- Ảnh vuông, tỉ lệ 1:1
- Đây là ảnh bìa để đăng Shopee/TikTok Shop nên đừng thêm chữ, khung viền hay hiệu ứng gì

Cuối cùng, nhìn lại hai ảnh vừa làm và nói cho tôi biết chỗ nào cắt chưa đẹp để tôi biết mà chụp lại lần sau."""
    steps = """Bước 1 — Mở ChatGPT hoặc Gemini
Sẵn sàng làm, không cài gì cả.

Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
AI làm ra hai ảnh: nền trong suốt và nền trắng.

Bấm biểu tượng kẹp giấy hoặc dấu cộng để tải ảnh sản phẩm lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Tải về và kiểm ba chỗ
Bấm vào ảnh kết quả để tải về. Trước khi đăng, phóng to kiểm ba chỗ AI hay làm hỏng:

• Viền sản phẩm — có bị ăn lẹm vào hay còn sót mảng nền không
• Chữ trên bao bì — có bị AI vẽ lại thành chữ sai không
• Màu sản phẩm — có bị lệch so với ảnh gốc không"""
    notes = """Gemini thường nhanh hơn cho việc xoá nền, ChatGPT cho màu sắc chuẩn hơn với ảnh sản phẩm. Có cả hai thì thử cả hai rồi chọn bản đẹp hơn.

Tải ảnh lên TRƯỚC rồi mới dán câu lệnh. Làm ngược lại thì AI không biết bạn nói về ảnh nào.

Chỗ nào chưa đạt thì nhắn tiếp trong cùng cuộc trò chuyện, ví dụ 'viền bên trái còn sót nền, cắt lại giúp tôi'. Đừng làm lại từ đầu."""
    sections = [
        {"number": "01", "title": "Skill này gồm những gì", "body": "Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có"},
        {"number": "02", "title": "Chuẩn bị trước khi bắt đầu", "body": "Một ảnh sản phẩm cần tách nền. Tải ảnh lên TRƯỚC rồi mới dán câu lệnh."},
        {"number": "04", "title": "Làm theo 3 bước", "body": steps},
        {"number": "05", "title": "Làm thử ngay", "body": "Làm bộ ảnh sản phẩm nền trắng đồng bộ để đăng bán\n\n1. Chọn 3 ảnh sản phẩm bạn đang bán, chụp ở 3 phông nền khác nhau — loại mà đăng lên trông lộn xộn\n2. Làm lần lượt từng ảnh theo 3 bước trên\n3. Xếp 3 ảnh nền trắng cạnh nhau xem đã ra một bộ đồng bộ chưa\n4. Đăng thử lên gian hàng, so với ảnh cũ\n\nXong sẽ có: Ba ảnh sản phẩm cùng nền trắng, sản phẩm căn giữa, nhìn như chụp cùng một buổi trong studio — gian hàng trông chuyên nghiệp hẳn so với ảnh gốc."},
    ]
    database.execute(
        "UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?",
        ("Xoá phông trong vài giây, ra ảnh nền trong suốt để ghép vào đâu cũng được", "Biến ảnh sản phẩm chụp ở bất kỳ đâu thành ảnh nền trong suốt và ảnh nền trắng chuẩn sàn — làm ngay trên ChatGPT hoặc Gemini bạn đang có, không cài gì, dùng được cả trên điện thoại.", prompt, "Một ảnh sản phẩm cần tách nền.", "Một file PNG nền trong suốt và một ảnh vuông nền trắng #FFFFFF.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://github.com/danielgatis/rembg", skill_id),
    )

    skill_id = database.execute("SELECT id FROM skills WHERE slug='xoa-logo-anh'").fetchone()["id"]
    prompt = """Xoá [mô tả CHÍNH XÁC thứ cần xoá và vị trí, ví dụ: dòng chữ watermark màu trắng mờ ở góc dưới bên phải] khỏi bức ảnh này, vẽ lấp lại chỗ đó bằng đúng những gì lẽ ra phải có ở đó (tiếp tục hoạ tiết/màu nền xung quanh).

Yêu cầu bắt buộc:
- CHỈ xoá đúng vùng tôi mô tả, GIỮ NGUYÊN 100% mọi phần khác của ảnh — không vẽ lại, không đổi màu, không đổi bố cục chỗ khác.
- Vùng vừa xoá phải liền mạch với phần ảnh xung quanh, không để lại viền, vết mờ hay khác tông màu.
- Không thêm watermark hay chữ ký nào khác vào ảnh.

Sau khi xong, phóng to đúng vùng vừa xoá và cho tôi biết có còn thấy vết chỉnh sửa không."""
    steps = """Bước 1 — Mở ChatGPT hoặc Gemini
Sẵn sàng làm, không cài gì cả.

Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên, mô tả CHÍNH XÁC vùng cần xoá
AI xoá đúng vùng cần, giữ nguyên phần còn lại.

Bấm biểu tượng kẹp giấy để tải ảnh lên. Điền rõ vị trí và mô tả thứ cần xoá vào câu lệnh (ví dụ 'logo hình tròn màu đỏ ở góc trên bên trái') rồi gửi.

Bước 3 — Phóng to kiểm đúng vùng vừa xoá
Không còn thấy vết chỉnh sửa.

Tải ảnh về, phóng to đúng vùng vừa xoá xem có còn viền, vết mờ hay lệch tông màu không. Kiểm luôn các phần khác của ảnh xem có bị vẽ lại ngoài ý muốn không."""
    notes = """Mô tả càng chính xác vị trí thì AI càng ít đụng nhầm vào phần khác. Mô tả mơ hồ như 'xoá watermark' mà ảnh có nhiều chữ dễ khiến AI xoá nhầm hoặc vẽ lại cả những phần không cần.

Thấy phần khác của ảnh bị đổi dù không yêu cầu thì nhắn lại: 'Chỉ sửa đúng vùng tôi nói, đừng đụng chỗ khác.' Vẫn không được thì cần chuyển sang cài IOPaint ở cuối trang."""
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh có watermark, logo chìm, chữ thừa hoặc vật thể cần xoá. Ghi chính xác vị trí và mô tả vùng cần xoá."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Xoá một watermark hoặc logo chìm khỏi ảnh sản phẩm để đăng bán lại\n\n1. Tìm một ảnh có watermark, logo chìm hoặc chữ thừa cần xoá\n2. Làm theo 3 bước trên, mô tả càng chính xác vị trí càng tốt\n3. Phóng to kiểm cả vùng vừa xoá lẫn phần còn lại của ảnh\n4. Đạt yêu cầu thì lưu lại dùng, không thì thử lại với mô tả rõ hơn\n\nXong sẽ có: Ảnh không còn dấu vết watermark/logo ở đúng vị trí đã xoá, phần còn lại của ảnh giữ nguyên như gốc, không lộ vết chỉnh sửa khi phóng to."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Xoá logo chìm, chữ thừa, người lạ khỏi ảnh mà không để lại vết", "Xoá watermark, logo chìm, người lạ hoặc chữ thừa khỏi ảnh mà không để lại vết — làm ngay trên ChatGPT hoặc Gemini, không cần cài gì.", prompt, "Một ảnh và mô tả chính xác thứ cần xoá cùng vị trí.", "Ảnh đã xoá đúng vùng cần xoá, phần còn lại giữ nguyên.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://github.com/Sanster/IOPaint", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='chinh-sua-anh'").fetchone()["id"]
    prompt = """Làm đẹp tấm ảnh chân dung này giúp tôi.

Yêu cầu bắt buộc, quan trọng nhất xếp trước:
- GIỮ ĐÚNG KHUÔN MẶT NGƯỜI TRONG ẢNH. Vẫn phải nhận ra là đúng người đó. Không làm trẻ ra, không đổi dáng mũi/mắt/miệng, không đổi kiểu tóc. Đây là yêu cầu số một, quan trọng hơn việc ảnh có đẹp hay không.
- Làm rõ nét phần bị mờ, khử nhiễu hạt.
- Cân bằng lại ánh sáng nếu ảnh thiếu sáng, khử ám vàng nếu ảnh bị ngả màu.
- Làm mịn da ở mức VỪA PHẢI, vẫn thấy được kết cấu da thật. Đừng làm phẳng lì như tượng sáp.
- Giữ nguyên bối cảnh phía sau, đừng thay nền.
- Không thêm trang điểm, không thêm hiệu ứng, không thêm watermark.

Làm xong, đặt ảnh mới cạnh ảnh gốc và nói cho tôi biết bạn đã đổi những gì trên khuôn mặt."""
    steps = """Bước 1 — Mở ChatGPT hoặc Gemini
Sẵn sàng làm, không cài gì cả.

Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
AI trả về ảnh đã làm đẹp.

Bấm biểu tượng kẹp giấy để tải ảnh lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Soi kỹ khuôn mặt trước khi dùng
Chắc chắn vẫn đúng người.

Phóng to phần mặt, đặt cạnh ảnh gốc mà so. Nhìn kỹ dáng mũi, khoảng cách hai mắt, nếp cười — đây là ba chỗ máy hay đổi nhất mà nhìn lướt không thấy."""
    notes = """Ảnh thờ, ảnh gia đình, ảnh hồ sơ xin việc — những ảnh BẮT BUỘC phải đúng mặt — thì đừng dùng cách này. Chat AI vẽ lại khuôn mặt nên rất hay ra người khác. Xuống thẳng phần 'Cài về máy' ở cuối trang.

Thấy khác người thì nhắn lại: 'Ảnh này ra người khác rồi. Làm lại, ưu tiên giữ đúng khuôn mặt gốc, chấp nhận ảnh kém đẹp hơn.'"""
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh chân dung cần làm rõ nét, cân sáng hoặc làm mịn da. Với ảnh bắt buộc đúng mặt, dùng dây chuyền cài về máy thay vì Chat AI."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cứu một ảnh chân dung mờ trong điện thoại thành ảnh dùng được\n\n1. Chọn một ảnh chân dung bị mờ hoặc thiếu sáng\n2. Làm theo 3 bước trên\n3. Đặt ảnh mới cạnh ảnh gốc, phóng to phần mặt mà so\n4. Vẫn đúng người và nét hơn hẳn thì lưu lại dùng\n\nXong sẽ có: Ảnh nét hơn, sáng hơn, da mịn vừa phải mà vẫn nhận ra đúng người — không thành một gương mặt lạ."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Nét, đẹp mặt mà vẫn đúng người thật, cân màu, mịn da — sáu bước một lượt", "Làm đẹp ảnh chân dung ngay trên ChatGPT hoặc Gemini, không cần cài gì. Cần GIỮ ĐÚNG khuôn mặt thật — ảnh thờ, ảnh gia đình, ảnh hồ sơ — thì cài dây chuyền 6 bước về máy, vì chat AI hay vẽ ra người khác.", prompt, "Một ảnh chân dung bị mờ, thiếu sáng hoặc cần cân màu.", "Ảnh nét hơn, sáng hơn và da mịn vừa phải, vẫn nhận ra đúng người.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://github.com/sczhou/CodeFormer", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='tang-chat-luong-4k'").fetchone()["id"]
    prompt = """Làm nét và phóng to bức ảnh sản phẩm này để tôi đăng bán và chạy quảng cáo.
Yêu cầu bắt buộc:
- GIỮ NGUYÊN sản phẩm: đúng hình dáng, đúng màu, đúng chữ trên bao bì. Chỉ làm rõ nét hơn, TUYỆT ĐỐI không vẽ lại, không thêm chi tiết không có trong ảnh gốc.
- Khử nhiễu hạt và vết mờ do chụp bằng điện thoại đời thấp.
- Làm rõ phần chữ và logo trên sản phẩm — đây là chỗ quan trọng nhất.
- Xuất ảnh ở độ phân giải cao nhất bạn làm được, tối thiểu gấp đôi ảnh gốc.
- Không thêm hiệu ứng, không chỉnh màu cho \"nghệ\", không thêm watermark.
Sau khi làm xong, so ảnh mới với ảnh gốc và nói cho tôi biết:
- Chỗ nào bạn phải đoán thêm chi tiết vì ảnh gốc quá mờ
- Ảnh này có đủ nét để in poster khổ lớn chưa, hay chỉ đủ đăng mạng"""
    steps = """Bước 1 — Mở ChatGPT hoặc Gemini
Sẵn sàng làm, không cài gì cả.

Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
AI làm ra ảnh nét hơn.

Bấm biểu tượng kẹp giấy để tải ảnh mờ lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Kiểm chữ trước khi dùng
Chắc chắn AI không bịa chi tiết.

Tải ảnh về, phóng to lên và soi kỹ phần chữ, logo, mã vạch. Đây là chỗ AI hay bịa nhất khi ảnh gốc mờ."""
    notes = "Ảnh gốc càng rõ thì kết quả càng thật. Ảnh quá mờ thì máy phải đoán, và đoán sai là ra chữ lạ trên bao bì. Chữ bị sai thì không dùng được, dù ảnh nhìn nét. Gặp vậy thì chụp lại ảnh gốc rõ hơn, hoặc dùng cách cài về máy ở cuối trang — công cụ chuyên phóng nét không tự bịa chữ."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh sản phẩm cũ, mờ hoặc thiếu độ phân giải."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cứu một ảnh sản phẩm cũ mờ thành ảnh đăng bán được\n\n1. Tìm một ảnh sản phẩm cũ bị mờ — loại mà bạn từng ngại đăng\n2. Làm theo 3 bước trên\n3. Mở hai ảnh cạnh nhau, phóng to phần chữ trên bao bì để so\n4. Nếu chữ vẫn đúng và ảnh nét hơn hẳn thì đăng thử lên gian hàng\n\nXong sẽ có: Một ảnh nét gấp đôi ảnh gốc, chữ trên bao bì vẫn đọc đúng, đủ rõ để chạy quảng cáo mà không bị vỡ hạt."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Ảnh nhỏ mờ thành ảnh lớn sắc nét chỉ bằng vài cú bấm chuột, in poster khổ lớn được", "Cứu ảnh sản phẩm mờ, ảnh cũ, ảnh chụp bằng điện thoại đời thấp thành ảnh nét đủ để chạy quảng cáo và in poster — làm ngay trên ChatGPT hoặc Gemini, không cài gì.", prompt, "Một ảnh sản phẩm mờ hoặc độ phân giải thấp.", "Ảnh độ phân giải cao hơn, sản phẩm và chữ trên bao bì được kiểm tra lại.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://github.com/upscayl/upscayl", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='multishot'").fetchone()["id"]
    prompt = """Tôi gửi một ảnh. Hãy tạo cho tôi 9 góc quay khác nhau của ĐÚNG khoảnh khắc này.

Quy tắc bắt buộc:
- Giữ nguyên nhân vật, trang phục, đạo cụ, bối cảnh và ánh sáng như ảnh gốc. Đây phải là cùng một khoảnh khắc nhìn từ chỗ khác, KHÔNG phải chín khoảnh khắc khác nhau.
- Chỉ thay ba thứ: vị trí máy quay, cỡ cảnh (cận / trung / toàn), và kiểu ống kính.
- Chín góc phải khác nhau rõ rệt. Đừng cho tôi chín tấm chỉ xê dịch vài độ.
- Mỗi tấm ghi rõ bên dưới: máy đặt ở đâu, cỡ cảnh gì, ống kính gì.

Trước khi tạo ảnh, liệt kê cho tôi xem 9 góc bạn định làm. Tôi duyệt xong bạn mới tạo."""
    steps = """Bước 1 — Chọn ảnh tham chiếu
Máy có đủ thông tin để dựng lại từ góc khác.

Chọn ảnh thấy rõ nhân vật hoặc vật thể chính, đủ sáng, không bị che khuất. Ảnh càng rõ thì các góc mới càng nhất quán.

Lưu ý: Ảnh chỉ thấy nửa mặt hoặc bị che nhiều thì máy phải tự bịa phần khuất — các góc sẽ lệch nhau. Chọn ảnh nhìn thấy được nhiều nhất có thể.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
AI đề xuất danh sách góc quay.

Bấm kẹp giấy tải ảnh lên, bấm nút Chép ở đầu trang rồi dán câu lệnh vào, gửi. Muốn số góc khác 9 thì sửa thẳng con số trong câu lệnh.

Lưu ý: Muốn STORYBOARD phim thay vì các góc rời: thêm chữ 'Video' vào câu nhờ. Đúng một chữ đó quyết định bạn nhận về thứ gì — có 'Video' thì ra một bảng ô vuông đánh số kèm câu lệnh dựng video, không có thì ra các ảnh rời.

Bước 3 — Duyệt danh sách góc rồi cho chạy
Các góc khác nhau thật.

Đọc danh sách, thấy góc nào trùng ý thì đổi: 'Góc 3 và góc 6 gần giống nhau, đổi góc 6 thành nhìn từ trên xuống.' Ưng rồi thì bảo tạo ảnh.

Bước 4 — Kiểm tính nhất quán
Chín tấm đúng là một khoảnh khắc.

Đặt các tấm cạnh nhau, soi ba thứ: trang phục có đổi không, ánh sáng chiếu cùng hướng không, đạo cụ có còn nguyên chỗ không.

Lưu ý: Định dùng làm keyframe video thì tính nhất quán quan trọng hơn ảnh đẹp. Tấm nào lệch thì bỏ, đừng tiếc."""
    notes = "Ảnh chỉ thấy nửa mặt hoặc bị che nhiều thì máy phải tự bịa phần khuất — các góc sẽ lệch nhau. Chọn ảnh nhìn thấy được nhiều nhất có thể. Muốn STORYBOARD phim thay vì các góc rời: thêm chữ 'Video' vào câu nhờ. Đúng một chữ đó quyết định bạn nhận về thứ gì. Định dùng làm keyframe video thì tính nhất quán quan trọng hơn ảnh đẹp. Tấm nào lệch thì bỏ, đừng tiếc."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh tham chiếu rõ nhân vật hoặc vật thể chính, đủ sáng và không bị che khuất."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Tạo 9 góc quay từ một ảnh chân dung của bạn\n\n1. Chọn một ảnh chân dung rõ mặt, đủ sáng\n2. Làm theo 4 bước trên\n3. Đặt 9 tấm cạnh nhau, kiểm trang phục và hướng sáng\n4. Làm lại một lần nữa, lần này thêm chữ 'Video' để xem storyboard khác thế nào\n\nXong sẽ có: Chín tấm nhìn ra ngay là cùng một người, cùng bộ đồ, cùng khoảnh khắc — chỉ khác chỗ đặt máy quay."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=NULL, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Một ảnh ra nhiều góc quay nhất quán, dùng làm keyframe video hoặc storyboard", "Đưa MỘT ảnh, nhận về NHIỀU góc quay của cùng một khoảnh khắc — nhất quán đủ để làm keyframe video. Thêm chữ 'Video' vào câu nhờ thì đổi sang dựng storyboard điện ảnh. Không cài gì.", prompt, "Một ảnh tham chiếu rõ nhân vật hoặc vật thể chính.", "Chín góc quay khác nhau rõ rệt của cùng một khoảnh khắc.", steps, notes, json.dumps(sections, ensure_ascii=False), skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='hoan-doi-nhan-vat'").fetchone()["id"]
    prompt = """Tôi gửi ảnh nhân vật thương hiệu của tôi. Đây là ảnh neo — nhân vật này phải giữ nguyên nhận diện qua mọi ảnh về sau.

KHOÁ DANH TÍNH, không bao giờ được đổi:
- Khuôn mặt: đúng người trong ảnh neo, không làm trẻ ra, không đổi dáng mắt/mũi/miệng.
- Kiểu tóc và màu tóc: đúng như ảnh neo.
- Trang phục đặc trưng: đúng kiểu, đúng màu như ảnh neo.

ĐƯỢC PHÉP ĐỔI THOẢI MÁI:
- Bối cảnh, ánh sáng, thời gian trong ngày
- Tư thế, hướng nhìn, biểu cảm
- Góc máy, cỡ cảnh, đạo cụ trong tay

Việc tôi cần: đặt nhân vật này vào bối cảnh sau — <ghi bối cảnh bạn muốn>.

Tạo xong, đặt ảnh mới cạnh ảnh neo và tự đánh giá: có nhận ra là cùng một người không? Không giống thì làm lại, đừng đưa tôi tấm sai."""
    steps = """Bước 1 — Chọn một ảnh neo và giữ mãi
Chọn tấm ảnh rõ mặt nhất, đủ sáng, nhìn thẳng hoặc hơi nghiêng, thấy được cả kiểu tóc và trang phục đặc trưng. Lưu riêng ra một chỗ.

Bước 2 — Tải ảnh neo lên rồi dán câu lệnh
Bấm kẹp giấy tải ảnh neo lên. Bấm nút Chép ở đầu trang, dán câu lệnh vào, thay chỗ ngoặc nhọn bằng bối cảnh bạn muốn, rồi gửi.

Bước 3 — So với ảnh neo trước khi dùng
Đặt ảnh mới cạnh ảnh neo. Soi ba chỗ máy hay đổi nhất: dáng mũi, khoảng cách hai mắt, màu tóc."""
    notes = "Đây là quyết định dùng mãi. Mỗi lần đổi ảnh neo là nhân vật của bạn đổi mặt, khách hàng sẽ thấy ngay là không nhất quán. Tả bối cảnh càng cụ thể càng tốt. Thấy lệch thì làm lại ngay, đừng dùng tạm."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh neo rõ mặt, tóc và trang phục đặc trưng của nhân vật thương hiệu."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Đưa nhân vật thương hiệu của bạn qua ba bối cảnh khác nhau\n\n1. Chọn ảnh neo cho nhân vật thương hiệu\n2. Làm ba ảnh với ba bối cảnh khác hẳn nhau: trong nhà, ngoài trời, ban đêm\n3. Đặt cả ba cạnh ảnh neo mà so mặt\n4. Cả ba đều nhận ra là một người thì bạn đã có bộ ảnh dùng được\n\nXong sẽ có: Ba ảnh ở ba bối cảnh khác hẳn nhau, nhưng nhìn phát nhận ra ngay là cùng một nhân vật."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=NULL, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Một nhân vật thương hiệu cố định, đặt vào bối cảnh nào cũng vẫn là một người", "Một nhân vật thương hiệu cố định — cùng khuôn mặt, cùng trang phục — xuất hiện ở bối cảnh nào cũng vẫn nhận ra là một người. Không cài gì, chạy thẳng trên AI bạn đang có.", prompt, "Một ảnh neo rõ mặt, tóc và trang phục đặc trưng.", "Ảnh nhân vật nhất quán ở bối cảnh mới.", steps, notes, json.dumps(sections, ensure_ascii=False), skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='dang-1-thoai-thumbnail'").fetchone()["id"]
    prompt = """Video của tôi đang ở input/ (hoặc tôi sẽ đưa đường dẫn cụ thể). Edit Dạng 1 cho video này:
- Cắt gọn khoảng lặng và từ đệm tự nhiên, giữ mạch nói liền lạc.
- Tự đọc nội dung rồi viết 1 thumbnail mở đầu đúng chủ đề (đừng copy nguyên câu chào đầu video).
- Thêm phụ đề động chạy khớp lời nói, chữ trắng dày, không che mặt.
- Xuất video dọc 9:16.

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước, đừng hỏi tôi từng bước trừ khi bị chặn quyền hệ thống. Xong việc thì cho tôi biết file kết quả nằm ở đâu và chỗ nào bạn không chắc thì nói rõ."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
AI của bạn đọc và nạp được Skill này, dùng lại được cho lần sau. Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video vào, nhờ việc
Dán câu nhờ việc mẫu trong cùng cuộc trò chuyện. Kèm theo video của bạn — nói rõ đường dẫn file hoặc kéo thả nếu AI hỗ trợ.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu dùng trên 1 máy mới, AI cần thêm vài phút để cài ffmpeg/Whisper/Node. Các lần edit sau trên máy này sẽ nhanh ngay từ đầu.

Bước 4 — Nhận file, kiểm tra và chỉnh nếu cần
Mở file trong thư mục output/, kiểm thumbnail, phụ đề và điểm cắt. Chưa ưng thì nhắn tiếp trong cùng cuộc trò chuyện."""
    notes = "KHÔNG dán vào ChatGPT/Claude bản web thường — bản web không chạy lệnh thật trên máy được. AI báo thiếu quyền cài đặt hệ thống thì mới cần bạn can thiệp."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Cắt gọn tự nhiên, thumbnail AI và phụ đề động cho video nói chuyện."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video nói chuyện trước camera, dài 1–5 phút; đường dẫn file hoặc file upload."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Edit 1 video nói chuyện thật thành short đăng được ngay\n\n1. Chọn 1 video quay cảnh bạn nói chuyện, dài 1-5 phút\n2. Làm theo 4 bước trên\n3. Xem lại kết quả trong output/, kiểm thumbnail, phụ đề, điểm cắt\n4. Đăng thử lên kênh của bạn\n\nXong sẽ có: 1 video dọc 9:16, mở đầu bằng thumbnail đúng nội dung, phụ đề chạy khớp lời, không còn khoảng lặng/từ đệm thừa."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Cắt gọn tự nhiên, mở đầu bằng thumbnail AI tự viết, phụ đề động chạy theo lời nói", "Đưa 1 video nói chuyện trước camera vào — AI tự cắt gọn khoảng lặng/từ đệm, tự viết thumbnail mở đầu, thêm phụ đề động và xuất video dọc 9:16.", prompt, "Một video nói chuyện trước camera, dài 1–5 phút.", "Một video dọc 9:16 có thumbnail mở đầu, phụ đề động và điểm cắt gọn.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='dang-2-hieu-ung-cao-cap'").fetchone()["id"]
    prompt = """Video của tôi đang ở input/. Edit Dạng 2 cho video này — bản cao cấp nhiều hiệu ứng:
- Vẫn cắt gọn khoảng lặng + thumbnail mở đầu + phụ đề động như bản cơ bản.
- Thêm zoom theo nhịp cảm xúc, overlay hoạt hoạ minh hoạ đúng nội dung đang nói, âm thanh phụ trợ (SFX) khớp lúc hiệu ứng xuất hiện, từ khoá đắt nhấn 2 màu, 1 lần crop bám mặt ở giữa video, và 1 hiệu ứng so sánh trước/sau nếu nội dung có kiểu \"thay vì A hãy B\".
- Màu thương hiệu của tôi (nếu có): [điền màu, không có thì bỏ qua để AI tự chọn].

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước. Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video vào, nói rõ màu thương hiệu nếu có
Bấm Chép câu nhờ việc mẫu, điền màu thương hiệu nếu có, dán cùng video vào cuộc trò chuyện.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper/Node/thư viện nhận diện khuôn mặt.

Bước 4 — Nhận file, kiểm tra 3 chỗ hay lệch
Mở file trong output/, kiểm overlay có che mặt không, hiệu ứng có dồn dập không và từ khoá nhấn có đúng ý chính không."""
    notes = "Không có màu riêng cũng không sao — AI tự chọn tông neon+trắng mặc định. Chưa ưng chỗ nào thì nhắn tiếp trong CÙNG cuộc trò chuyện, ví dụ 'overlay ở giây 12 đang che một phần mặt, đẩy xuống thấp hơn'."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Zoom theo cảm xúc, overlay hoạt hoạ, âm thanh, crop bám mặt, so sánh trước/sau."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video nói chuyện dài 1–3 phút; nếu có, chuẩn bị màu thương hiệu."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Edit 1 video nói chuyện thành bản cao cấp có hiệu ứng\n\n1. Chọn 1 video nói chuyện dài 1-3 phút, có ít nhất 1 đoạn kiểu liệt kê hoặc số liệu\n2. Làm theo 3 bước trên\n3. So sánh với bản Dạng 1 (nếu có) — thấy rõ 7 lớp hiệu ứng thêm vào\n4. Đăng thử, theo dõi thời gian xem trung bình có tăng\n\nXong sẽ có: 1 video sinh động: zoom đúng lúc, overlay minh hoạ không che mặt, âm thanh phụ trợ tinh tế, tối đa 1 lần crop-mặt và 1 hiệu ứng so sánh — không bị nhồi nhét."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Zoom theo cảm xúc, overlay hoạt hoạ, âm thanh, crop bám mặt, so sánh trước/sau", "Đưa 1 video nói chuyện vào — AI dựng bản edit cao cấp: zoom theo cảm xúc, overlay hoạt hoạ, âm thanh phụ trợ, từ khoá nhấn 2 màu, crop bám mặt và so sánh trước/sau.", prompt, "Một video nói chuyện dài 1–3 phút; màu thương hiệu nếu có.", "Video dọc sinh động với các hiệu ứng đúng ngữ cảnh, không che mặt.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='dang-3-huong-dan-toi-gian'").fetchone()["id"]
    prompt = """Video của tôi đang ở input/. Edit Dạng 3 cho video này — bản tối giản cho coach/chuyên gia:
- Đọc nội dung, viết 1 tiêu đề trắng lớn bám trên khung suốt video (câu hook đắt nhất).
- Chia nội dung thành các bước/ý theo đúng những gì tôi nói (không ép đánh số cứng nếu nội dung không phải quy trình), text trắng hiện lần lượt.
- Chèn CTA khéo léo, tự nhiên — câu CTA của tôi (nếu có): [điền câu CTA, không có thì để AI tự viết].
- Thêm nhạc nền dẫn dắt cảm xúc, tự điều chỉnh to/nhỏ theo có lời hay không.
- Zoom cực nhẹ, chỉ ở điểm chuyển ý.
- KHÔNG thêm overlay hoạt hoạ, không crop mặt, không SFX — giữ khung thật sạch.

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước. Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video vào, đưa câu CTA nếu có
Bấm Chép câu nhờ việc mẫu, điền câu CTA hay dùng nếu có, dán cùng video vào cuộc trò chuyện.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper/Node.

Bước 4 — Nhận file, kiểm nhạc và CTA
Mở file trong output/, kiểm nhạc có đủ nhỏ khi bạn đang nói không, CTA có tự nhiên không và tiêu đề có đúng trọng tâm không."""
    notes = "KHÔNG dán vào ChatGPT/Claude bản web thường — bản web không chạy lệnh thật trên máy được. Chưa ưng thì nhắn tiếp trong CÙNG cuộc trò chuyện, ví dụ 'nhạc đoạn đầu to quá, hạ thêm xuống'."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Tiêu đề trắng lớn, các bước hiện dần theo nội dung, CTA tự nhiên và nhạc dẫn cảm xúc."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video chia sẻ kiến thức/hướng dẫn dài 1–3 phút và câu CTA nếu có."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Edit 1 video hướng dẫn/chia sẻ thành bản tối giản chuyên nghiệp\n\n1. Chọn 1 video bạn chia sẻ kiến thức/hướng dẫn, dài 1-3 phút\n2. Nghĩ trước 1 câu CTA muốn dùng (không có cũng được)\n3. Làm theo 3 bước trên\n4. Đăng thử, so cảm giác sạch, sang với video có nhiều hiệu ứng\n\nXong sẽ có: 1 video khung sạch: tiêu đề trắng lớn rõ ràng, các bước hiện đúng nhịp nội dung, CTA nghe tự nhiên, nhạc dẫn cảm xúc mà không đè lời nói."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Tiêu đề trắng lớn, các bước hiện dần theo nội dung, nhạc dẫn dắt cảm xúc — sạch, sang", "Đưa 1 video hướng dẫn/chia sẻ vào — AI dựng bản tối giản kiểu content coach cao cấp: tiêu đề trắng lớn, các bước hiện dần, CTA khéo léo, nhạc dẫn cảm xúc và zoom cực nhẹ.", prompt, "Một video hướng dẫn/chia sẻ dài 1–3 phút; CTA nếu có.", "Video tối giản, sạch, sang, có tiêu đề, các bước, CTA và nhạc đúng nhịp.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='dang-4-infographic-trang'").fetchone()["id"]
    prompt = """Video của tôi đang ở input/. Edit Dạng 4 cho video này:
- Vẫn cắt gọn khoảng lặng + phụ đề động như bản cơ bản.
- Xen kẽ talking-head với lớp phủ infographic trắng/sáng toàn màn hình — AI tự đọc nội dung, tự chọn khối phù hợp (tiêu đề hero, thẻ so sánh VS, sơ đồ bước, danh sách, số liệu) và tự biến tấu thiết kế mỗi lần khác nhau.
- Áp bộ lọc màu pro mặc định (sáng nhẹ, tương phản, nịnh da, làm nét).
- Tông màu thương hiệu của tôi (nếu có): [điền 2 màu, không có thì để AI dùng đỏ+navy mặc định].

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước. Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video vào, nói rõ tông màu nếu có
Bấm Chép câu nhờ việc mẫu, điền 2 tông màu thương hiệu nếu có, dán cùng video vào cuộc trò chuyện.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper/Node/thư viện nhận diện khuôn mặt.

Bước 4 — Nhận file, kiểm độ đa dạng của infographic
Mở file trong output/, kiểm lớp phủ infographic có khác kiểu nhau không, nội dung có đúng đoạn đang nói không và màu có đúng thương hiệu không."""
    notes = "Chưa ưng chỗ nào thì nhắn tiếp trong CÙNG cuộc trò chuyện, ví dụ 'lớp phủ ở giây 20 đang lặp kiểu với lớp ở giây 5, đổi sang dạng khác'."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Lớp phủ infographic trắng do AI tự thiết kế: tiêu đề hero, thẻ so sánh VS, sơ đồ bước, danh sách và số liệu."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video nói chuyện có phần so sánh hoặc quy trình nhiều bước; 2 màu thương hiệu nếu có."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Edit 1 video nói chuyện thành bản infographic kiểu HeyGen\n\n1. Chọn video có đoạn so sánh hoặc quy trình nhiều bước\n2. Làm theo 3 bước trên\n3. Kiểm các lớp phủ có đa dạng bố cục không\n4. Đăng thử, so cảm giác chuyên nghiệp với video gốc\n\nXong sẽ có: 1 video xen kẽ talking-head và lớp phủ infographic trắng đa dạng kiểu, màu sắc sáng/sạch, chất lượng hình ảnh nét và nịnh da hơn bản gốc."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Xen kẽ lớp phủ infographic trắng do AI tự thiết kế, phong cách chuyên nghiệp kiểu HeyGen", "Đưa 1 video nói chuyện vào — AI tự thiết kế và xen kẽ các lớp phủ infographic trắng toàn màn hình kèm bộ lọc màu pro, phong cách chuyên nghiệp kiểu HeyGen.", prompt, "Một video nói chuyện có đoạn so sánh hoặc quy trình; 2 màu thương hiệu nếu có.", "Video xen kẽ talking-head và lớp phủ infographic trắng đa dạng, đúng nội dung.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='cap-do-1-khung-don'").fetchone()["id"]
    prompt = """Video dài của tôi đang ở input/. Cắt video này thành short, Cấp độ 1:
- Quét toàn bộ, tự tìm và cắt ra các đoạn hay nhất (mở-thân-kết trọn vẹn, không cắt giữa ý).
- Mỗi đoạn crop khung đơn 9:16 bám sát mặt người nói, không cắt đầu.
- Áp cắt gọn khoảng lặng + thumbnail mở đầu + phụ đề động cho từng đoạn.
- Số lượng/độ dài mong muốn (nếu có): [điền, không có thì để AI tự ước theo độ dài video gốc, thường 5-8 đoạn].
- Ưu tiên tìm đoạn nói về (nếu có): [điền mô tả cụ thể, không có thì bỏ qua].

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước. Xong việc thì cho tôi biết các file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video dài vào, mô tả đoạn muốn ưu tiên nếu có
Bấm Chép câu nhờ việc mẫu, điền mô tả đoạn muốn tìm nếu có, dán cùng video vào cuộc trò chuyện.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper/Node/thư viện nhận diện khuôn mặt.

Bước 4 — Nhận nhiều file, chọn short ưng nhất
Các file nằm trong output/, đặt tên theo thứ tự điểm số giảm dần. Xem lần lượt, kiểm khung có bám đúng mặt không."""
    notes = "Video càng dài, bước quét càng lâu — video 1 giờ có thể mất 10-20 phút để ra hết short. Đoạn nào crop lệch mặt thì nhắn rõ short cần canh lại, không cần làm lại cả lô."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"AI quét video dài, tìm đoạn hay nhất, tạo short dọc 9:16 bám mặt, có thumbnail và phụ đề."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video dài 20–60 phút; mô tả chủ đề cần ưu tiên nếu có."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cắt 1 video dài thành bộ short đăng dần trong tuần\n\n1. Chọn 1 video dài 20-60 phút\n2. Làm theo 3 bước trên\n3. Xem hết các short ra được, xếp theo mức độ ưng ý\n4. Lên lịch đăng dần mỗi ngày 1 short\n\nXong sẽ có: 5-8 file short 9:16 riêng biệt, mỗi file là 1 đoạn trọn vẹn ý, khung luôn bám đúng mặt người nói, có thumbnail và phụ đề."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("AI tự tìm đoạn hay nhất trong video dài, cắt thành nhiều short 9:16 bám sát mặt người nói", "Đưa 1 video dài vào — AI tự quét toàn bộ, tìm và cắt ra nhiều đoạn hay nhất thành các short 9:16 riêng biệt, khung luôn bám sát mặt người nói.", prompt, "Một video dài 20–60 phút; chủ đề ưu tiên nếu có.", "5–8 short dọc riêng biệt có thumbnail, phụ đề và khung bám mặt.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='cap-do-2-postcard-2-nguoi'").fetchone()["id"]
    prompt = """Video podcast 2 người của tôi đang ở input/. Cắt video này thành short, Cấp độ 2:
- Quét toàn bộ, tự tìm và cắt ra các đoạn hay nhất.
- Xác định ai nói khi nào, dựng khung postcard: 1 khung lớn khi 1 người nói dài, 2 ô trên-dưới khi cả hai qua lại nhanh — chuyển đổi mượt, đúng nhịp câu.
- Mỗi ô crop bám mặt, không cắt đầu.
- Áp cắt gọn khoảng lặng + thumbnail mở đầu + phụ đề động cho từng đoạn.
- Số lượng/độ dài mong muốn (nếu có): [điền, không có thì để AI tự ước].

Nếu máy chưa có ffmpeg/Whisper/Node/hyperframes thì tự cài trước. Xong việc thì cho tôi biết các file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video vào
Bấm Chép câu nhờ việc mẫu, dán cùng video vào cuộc trò chuyện. Video càng quay rõ mặt cả 2 người thì kết quả càng chuẩn.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper/Node/thư viện nhận diện khuôn mặt.

Bước 4 — Nhận nhiều file, kiểm điểm chuyển khung
Mở file trong output/, kiểm khung có chuyển 1↔2 đúng lúc không, có bị cắt giữa câu ai đó đang nói không."""
    notes = "Kết quả nhận diện người nói chưa đủ tốt khi 2 người che khuất nhau hoặc dùng mic chung thì có thể nhờ AI dùng cách chính xác hơn. Sai người nói ở đoạn nào thì nhắn rõ short và thời gian để sửa, không cần làm lại cả lô."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"AI tự nhận diện hai người nói, cắt short podcast và chuyển khung postcard 1↔2 ô theo nhịp trò chuyện."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video podcast/phỏng vấn 2 người dài 20–60 phút, thấy rõ mặt cả hai người."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cắt 1 tập podcast/phỏng vấn 2 người thành bộ short\n\n1. Chọn video podcast/phỏng vấn 2 người, dài 20-60 phút\n2. Làm theo 3 bước trên\n3. Xem hết các short, kiểm khung postcard chuyển đúng nhịp không\n4. Đăng thử 1 short, xem phản ứng người xem\n\nXong sẽ có: 5-8 file short 9:16, khung postcard chuyển 1↔2 ô mượt đúng nhịp cuộc nói chuyện, cả 2 người đều rõ mặt khi cần, có thumbnail và phụ đề."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Video phỏng vấn/podcast 2 người tự cắt short, khung postcard tự chuyển 1↔2 theo ai đang nói", "Đưa 1 video podcast/phỏng vấn 2 người vào — AI tự cắt ra nhiều short 9:16, khung postcard 2 ô tự chuyển linh hoạt giữa 1 khung và 2 khung theo đúng nhịp cuộc trò chuyện.", prompt, "Một video podcast/phỏng vấn 2 người rõ mặt, dài 20–60 phút.", "5–8 short dọc với khung postcard chuyển đúng theo người nói.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='multiclip-ghep-nhac-trend'").fetchone()["id"]
    prompt = """Các clip của tôi đang ở input/, nhạc ở assets/music/. Ghép các clip này theo nhạc:
- Phân tích beat và cường độ nhạc, xếp thứ tự clip sao cho đoạn cao trào nhạc trùng clip ấn tượng nhất.
- Mỗi lần chuyển clip đặt đúng vào 1 mốc beat, không cắt tự do.
- Thêm zoom giật nhẹ ở các beat mạnh, áp 1 bộ lọc màu điện ảnh nhất quán cho cả video.
- Nếu clip quay ngang mà tôi cần xuất 9:16 thì crop dọc bám chủ thể.

Nếu máy chưa có ffmpeg/librosa/Node thì tự cài trước. Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa clip và nhạc vào, dặn rõ nếu là nhạc trend
Đưa các clip vào input/, đưa file nhạc vào assets/music/ hoặc nhờ AI gợi ý nhạc free-license nếu chưa có. Dán câu nhờ việc mẫu.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/thư viện phân tích nhạc (librosa)/Node.

Bước 4 — Nhận file, kiểm điểm chuyển clip có khớp nhạc không
Mở file trong output/, bật nhạc to lên nghe kỹ: mỗi lần đổi cảnh có đúng vào tiếng đập của nhạc không, clip đẹp nhất có nằm ở đoạn cao trào không."""
    notes = "Nhạc đang trend trên TikTok/Reels thường có bản quyền hãng đĩa — bạn phải tự tải file từ nguồn bạn có quyền dùng, AI không tự tải nhạc trend hộ bạn. Chưa khớp thì nhắn thời điểm cần canh beat, không cần ghép lại từ đầu."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Ghép nhiều clip rời rạc theo beat nhạc, zoom theo nhịp và bộ lọc màu điện ảnh nhất quán."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"5–10 clip ngắn và một bài nhạc free-license hoặc bạn có quyền dùng."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Ghép 5-10 clip thành 1 video theo nhạc\n\n1. Chọn 5-10 clip ngắn và 1 bài nhạc free-license hoặc bạn có quyền dùng\n2. Làm theo 3 bước trên\n3. Nghe lại với âm lượng to, kiểm nhịp chuyển clip có khớp beat không\n4. Đăng thử lên kênh trend\n\nXong sẽ có: 1 video liền mạch, mỗi lần đổi clip rơi đúng nhịp nhạc, clip ấn tượng nhất nằm ở đoạn cao trào, màu sắc nhất quán cả video."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Nhiều clip rời rạc tự ghép liền mạch, mỗi lần chuyển cảnh rơi đúng nhịp beat của nhạc", "Đưa nhiều clip rời rạc + 1 bài nhạc vào — AI ghép lại thành 1 video liền mạch, mỗi lần chuyển clip rơi đúng nhịp beat của nhạc, kèm zoom theo nhịp và bộ lọc màu điện ảnh.", prompt, "5–10 clip và một bài nhạc bạn có quyền dùng.", "Video dọc liền mạch với chuyển cảnh đúng beat và màu sắc nhất quán.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='multiclip-1-video-highlight'").fetchone()["id"]
    prompt = """Video dài của tôi đang ở input/, nhạc ở assets/music/ (hoặc gợi ý giúp tôi nếu chưa có). Cắt highlight từ video này ghép theo nhạc:
- Tự chia video thành các đoạn ứng viên theo điểm chuyển cảnh, chấm điểm chọn ra đoạn đẹp/ấn tượng/đa dạng nhất.
- Ghép các đoạn đã chọn khớp đúng nhịp (beat) nhạc, đoạn đẹp nhất đặt vào đoạn cao trào.
- Thêm zoom giật theo nhịp, bộ lọc màu điện ảnh, crop dọc nếu tôi cần xuất 9:16.
- Độ dài thành phẩm mong muốn (nếu có): [điền 15s/20s/30s/trọn bài, không có thì để AI tự ước theo độ dài nhạc].

Nếu máy chưa có ffmpeg/librosa/Node thì tự cài trước. Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa video dài và nhạc vào
Đưa 1 video dài vào input/, đưa nhạc vào assets/music/ hoặc nhờ AI gợi ý nhạc free-license. Dán câu nhờ việc mẫu.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/thư viện phân tích nhạc (librosa)/Node.

Bước 4 — Nhận file, kiểm độ đa dạng của các đoạn được chọn
Mở file trong output/, kiểm các đoạn được chọn có đủ đa dạng góc quay không và đoạn đẹp nhất có nằm ở cao trào nhạc không."""
    notes = "Nhạc đang trend trên TikTok/Reels thường có bản quyền — tự tải file từ nguồn bạn có quyền dùng. Muốn đổi đoạn nào thì nhắn cụ thể thời điểm cần thay, không cần làm lại từ đầu."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Tự chọn các đoạn đẹp/ấn tượng từ một video dài, ghép theo nhạc thành video quảng cáo ngắn."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video quay liên tục ít nhất 2–3 phút và nhạc bạn có quyền dùng."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Biến 1 video quay dài thành video quảng cáo ngắn\n\n1. Chọn video quay liên tục dài ít nhất 2-3 phút\n2. Chọn nhạc free-license hoặc bạn có quyền dùng\n3. Làm theo 3 bước trên\n4. So sánh với việc tự cắt tay\n\nXong sẽ có: 1 video ngắn 15-30s, các đoạn được chọn đa dạng góc quay, khớp đúng nhịp nhạc, đoạn ấn tượng nhất rơi vào cao trào."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Chỉ 1 video dài duy nhất, AI tự chọn đoạn ấn tượng nhất rồi ghép theo nhạc như video quảng cáo", "Chỉ 1 video dài duy nhất — AI tự quét, chọn ra các đoạn đẹp/ấn tượng nhất, cắt rời rồi ghép đúng nhịp nhạc thành video ngắn kiểu quảng cáo.", prompt, "Một video dài và nhạc bạn có quyền dùng.", "Video highlight 15–30 giây với các đoạn đa dạng, khớp beat và cao trào nhạc.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='edit-video-zoom'").fetchone()["id"]
    prompt = """File ghi buổi Zoom của tôi đang ở input/. Cắt buổi này thành 1 chuỗi khoá học nhiều phần:
- Đọc toàn bộ transcript, lập outline theo 4 loại (rác kỹ thuật / nội dung chính / khoảnh khắc cảm xúc thật / lạc trọng tâm) trước khi cắt gì.
- Cắt bỏ rác kỹ thuật, khoảng lặng >2s, đoạn lạc trọng tâm — GIỮ nguyên mọi khoảnh khắc cảm xúc thật (tiếng cười, câu chuyện tạo kết nối).
- Chia thành 5 phần theo đúng ranh giới chủ đề tự nhiên (ít hơn/nhiều hơn nếu nội dung không chia đẹp thành 5 — hỏi tôi trước khi đổi số phần).
- Mỗi phần: làm sạch âm thanh, chỉnh màu nhẹ, chống đơ hình nếu khung tĩnh lâu, nối mạch với phần trước bằng flashback từ chính footage gốc, có tiêu đề + mô tả + chương mục.
- Giữ 16:9 1920×1080, không crop dọc.
- Tên chuỗi (nếu có): [điền tên, không có thì tự rút từ nội dung].

Nếu máy chưa có ffmpeg/Whisper thì tự cài trước. Xong việc thì cho tôi biết các file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex đang mở tại một thư mục dự án.

Bước 2 — Đưa file Zoom vào, nói tên chuỗi nếu có
Bấm Chép câu nhờ việc mẫu, điền tên chuỗi/khoá học nếu có, dán cùng file ghi Zoom vào cuộc trò chuyện.

Bước 3 — Để AI tự cài môi trường (chỉ lần đầu)
Lần đầu trên máy mới sẽ mất thêm vài phút cài ffmpeg/Whisper.

Bước 4 — Nhận N file, kiểm continuity giữa các phần
Các file trong output/ kèm titles-descriptions.md và series-overview.md. Xem lần lượt, kiểm các phần có nối mạch tự nhiên không."""
    notes = "Buổi Zoom càng dài, bước đọc transcript + lập outline càng lâu — buổi 2 tiếng có thể mất 20-40 phút để ra hết 5 phần. Chỗ nào cắt hụt hoặc nối gượng thì nhắn rõ phần và thời điểm cần chỉnh, không cần làm lại cả chuỗi."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Đọc transcript Zoom, lập outline, loại rác kỹ thuật và chia thành chuỗi video 16:9 có tiêu đề, mô tả và chương mục."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một buổi ghi Zoom/đào tạo/coaching từ 45 phút trở lên và tên chuỗi nếu có."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cắt 1 buổi Zoom thành chuỗi khoá học đăng dần\n\n1. Chọn buổi ghi Zoom dài từ 45 phút trở lên\n2. Làm theo 3 bước trên\n3. Xem hết các phần, kiểm outline có đúng những gì đã nói không\n4. Đăng thử phần 1, hẹn phần 2 theo đúng câu nối đã dựng\n\nXong sẽ có: 1 chuỗi 5 video 16:9, mỗi video có tiêu đề/mô tả/chương mục riêng, nối mạch như một khoá học thật."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Video họp, hội thảo quay bằng Zoom tự cắt gọn, bỏ đoạn chết, dựng thành video hoàn chỉnh", "Đưa 1 buổi ghi Zoom dài vào — AI tự đọc transcript, lập outline, cắt bỏ khoảng lặng/rác kỹ thuật, chia thành chuỗi video 16:9 nối mạch kèm tiêu đề/mô tả/chương mục.", prompt, "Một buổi ghi Zoom dài từ 45 phút và tên chuỗi nếu có.", "Một chuỗi video 16:9 có outline, tiêu đề, mô tả và chương mục riêng.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='video-tu-dong-google-flow'").fetchone()["id"]
    prompt = """Mở Google Flow cho tôi và tạo 1 TVC: [mô tả ý tưởng của bạn, ví dụ \"tôi và nhân vật chính đi giữa thảo nguyên Mông Cổ lúc hoàng hôn\"].

Dùng đúng avatar/nhân vật và bối cảnh tôi đã lưu (hỏi tôi nếu chưa rõ dùng cái nào).

Giữ đúng cấu hình đã khoá: Thành phần, Omni 1.1 Flash, 9:16, chất lượng cao nhất hiện có, 10 giây, x1, không thoại/không voice-over.

Kiểm tra kỹ 3 mốc đầu/giữa/cuối trước khi cho tôi xem, sửa lại tối đa 1 lần nếu có lỗi rõ."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex có bật công cụ trình duyệt.

Bước 2 — Onboarding lần đầu: chọn project + xác nhận avatar/nhân vật
Tự đăng nhập/chọn hoặc tạo project trong Flow, rồi xác nhận tên avatar/nhân vật. Nếu chưa có avatar/nhân vật trong Flow, tự tải ảnh lên Flow trước.

Bước 3 — Nói ý tưởng, để AI tự mở Flow và tạo
Điền ý tưởng cụ thể: chủ thể + hành động + bối cảnh. AI soạn prompt, gắn đúng component, kiểm cấu hình rồi tạo x1 để thử nhận diện trước.

Bước 4 — Xem toàn bộ 10 giây, duyệt hoặc yêu cầu sửa
AI kiểm 3 mốc đầu/giữa/cuối. Xem toàn bộ, để ý mặt/tay/bối cảnh; nếu lỗi rõ thì nêu cụ thể để sửa tối đa một lần."""
    notes = "Bản web có thể đọc nội dung nhưng không điều khiển Google Flow thật. Mỗi lượt tạo tốn credit Flow thật — chỉ tạo x1 để thử nhận diện trước. Có lỗi rõ thì mô tả chính xác lỗi ở đâu."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Workflow tự mở Google Flow, dùng avatar/bối cảnh đã lưu và tạo TVC điện ảnh 10 giây không thoại."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Ảnh avatar/nhân vật rõ mặt, ảnh bối cảnh nếu cần và quyền truy cập Google Flow của bạn."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Tạo 1 TVC 10 giây đầu tiên với avatar của bạn\n\n1. Chuẩn bị ảnh avatar/nhân vật rõ mặt và ảnh bối cảnh, tải lên Flow\n2. Nghĩ 1 ý tưởng ngắn: chủ thể làm gì, ở đâu, không khí thế nào\n3. Làm theo 3 bước trên\n4. Xem lại video, so đối chiếu mặt/bối cảnh với ảnh gốc\n\nXong sẽ có: 1 video dọc 9:16, 10 giây, không thoại, đúng avatar và bối cảnh đã chọn, chuyển động mượt, kết thúc tự nhiên."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Nhập kịch bản, Google Flow tự dựng video AI hoàn chỉnh, không cần quay dựng thủ công", "Nói 1 câu ý tưởng — AI tự mở Google Flow, gắn avatar/nhân vật và bối cảnh đã lưu, soạn prompt điện ảnh 10 giây không thoại, tạo và kiểm tra video.", prompt, "Avatar/nhân vật, bối cảnh và ý tưởng TVC ngắn.", "Video TVC dọc 9:16, 10 giây, không thoại, kiểm tra 3 mốc.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://flow.google.com/", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='subagent-cham-soc'").fetchone()["id"]
    prompt = """Trang của tôi: [link Facebook Page]. Vào Meta Business Suite, mở bài viết [link bài viết hoặc \"bài mới nhất\"], trả lời hết bình luận trong [khoảng thời gian, ví dụ \"2 ngày qua\"] chưa có phản hồi từ trang.

Nguyên tắc bắt buộc:
- Mỗi câu trả lời một kiểu khác nhau thật sự — không copy khuôn câu, độ dài dao động tự nhiên (có câu chỉ vài từ, có câu dài hơn).
- Câu hỏi thật thì trả lời đúng trọng tâm (tra caption bài viết nếu cần); lời khen/xin tài liệu thì trả ngắn gọn, thân tình.
- Không bịa link, giá, chính sách cụ thể nếu không chắc — trả lời né nhẹ, mời nhắn riêng.
- Không tự nhắn tin riêng (Messenger/DM) trừ khi tôi yêu cầu.
- Không đăng 2 câu giống nhau dưới cùng 1 bình luận.
- Bỏ qua, để tôi tự xử lý: bình luận mâu thuẫn/cà khịa giữa 2 người, hoặc câu hỏi cần thông tin thật mà không xác minh được.

Xử lý xong báo tôi: đã trả lời bao nhiêu bình luận, bỏ qua bao nhiêu và vì sao."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex có bật công cụ trình duyệt.

Bước 2 — Đưa link trang + phạm vi cần xử lý
Điền link trang và khoảng thời gian hoặc đúng bài viết cụ thể. Nói rõ thông tin AI không được tự bịa nếu không chắc.

Bước 3 — Để AI tự trả lời từng bình luận
AI mở từng bình luận, gõ và gửi câu trả lời trên giao diện trong phạm vi bạn đã chỉ định.

Bước 4 — Kiểm lại và xử lý phần AI bỏ qua
AI báo danh sách đã trả lời và danh sách bỏ qua kèm lý do. Bạn tự xử lý phần cần quyết định."""
    notes = "Thấy câu trả lời nào chưa ưng thì nhắn ngay trong CÙNG cuộc trò chuyện để AI sửa lại. Không để AI tự trả lời phần mâu thuẫn/cà khịa hoặc câu hỏi cần thông tin thật mà không xác minh được."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Quy trình trả lời bình luận Facebook/YouTube tự nhiên, đa dạng, không bịa thông tin và biết bỏ qua đúng lúc."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Link Facebook Page, link bài viết hoặc phạm vi thời gian, cùng các thông tin AI không được tự bịa."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Trả lời thử một loạt bình luận thật trên trang của bạn\n\n1. Chọn 1 bài viết đang có nhiều bình luận chưa trả lời\n2. Làm theo 3 bước trên\n3. Đọc lại 5-10 câu trả lời đã gửi, kiểm xem có câu nào giống nhau không\n4. Xử lý tay phần AI báo bỏ qua\n\nXong sẽ có: Các bình luận trong phạm vi đã có phản hồi từ trang, mỗi câu một kiểu khác nhau thật sự, không có thông tin bịa, không có 2 câu giống hệt nhau dưới cùng 1 bình luận."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Trả lời bình luận Facebook/YouTube tự nhiên, đa dạng, không rập khuôn, không bịa thông tin", "AI tự vào Facebook/YouTube trả lời một loạt bình luận thay bạn — mỗi câu một kiểu, tự nhiên, không bịa thông tin khi không chắc và biết bỏ qua đúng lúc.", prompt, "Link trang, link bài viết hoặc phạm vi bình luận, cùng giới hạn thông tin được phép trả lời.", "Báo cáo số bình luận đã trả lời và các bình luận được bỏ qua kèm lý do.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://business.facebook.com/", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='subagent-nghien-cuu'").fetchone()["id"]
    prompt = """Ngách của tôi: [ví dụ \"AI tools cho dân kinh doanh nhỏ\"].
Nền tảng: [Facebook/YouTube/TikTok].
Đối tượng xem: [mô tả ngắn].

Tìm giúp tôi trend/chủ đề đang lên liên quan ngách này (ưu tiên tin tức vài tuần gần nhất), rồi soạn 10 ý tưởng content cụ thể cho [tuần này/tháng này].

Mỗi ý tưởng gồm: tên chủ đề, góc tiếp cận, lý do nên làm, mức độ tiềm năng (Cao/Trung bình/Thấp). Xếp theo tiềm năng giảm dần.

Nếu tôi đưa link kênh của tôi hoặc kênh đối thủ, xem qua vài bài/video gần đây trước khi đề xuất, để ý tưởng hợp giọng điệu và không trùng nội dung đã làm."""
    steps = """Bước 1 — Nói rõ ngách, nền tảng, mục tiêu
Điền ngách, nền tảng, đối tượng. Có link kênh của bạn hoặc kênh đối thủ thì đưa luôn để AI đối chiếu phong cách.

Bước 2 — Để AI tìm trend và soạn danh sách
AI tìm kiếm trend thật, xem qua kênh bạn đưa nếu có, rồi trả về danh sách 10 ý tưởng kèm góc tiếp cận và lý do.

Bước 3 — Chọn ý tưởng, nhờ AI đào sâu thêm
Chọn 1-2 ý tưởng ưng nhất, nhắn AI khai triển thêm góc quay/dàn ý trong cùng cuộc trò chuyện để giữ ngữ cảnh ngách."""
    notes = "AI nói rõ mức độ tin cậy khi một thông tin/xu hướng chưa chắc chắn — đừng bỏ qua chi tiết này; nó giúp bạn biết ý tưởng nào nên kiểm lại trước khi làm."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Tìm trend đang lên, phân tích kênh cùng ngách và trả về danh sách ý tưởng content cụ thể, xếp theo tiềm năng."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Ngách, nền tảng, đối tượng xem; link kênh của bạn hoặc đối thủ nếu có."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Lấy 10 ý tưởng content thật cho tuần này\n\n1. Chuẩn bị ngách, nền tảng, đối tượng xem, link kênh nếu có\n2. Làm theo 2 bước trên\n3. Đọc lại danh sách, đánh dấu 2-3 ý tưởng phù hợp nhất\n4. Nhờ AI khai triển sâu 1 ý tưởng đã chọn\n\nXong sẽ có: Danh sách 10 ý tưởng content cụ thể, mỗi ý tưởng có góc tiếp cận, lý do, mức tiềm năng, xếp theo tiềm năng giảm dần, đúng ngách và giọng điệu kênh."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=NULL, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Tìm chủ đề/trend đang lên, phân tích đối thủ, lên danh sách ý tưởng nội dung theo mức tiềm năng", "Nói ngách và nền tảng của bạn — AI tự tìm trend đang lên, soi kênh cùng ngách, rồi trả về danh sách ý tưởng content cụ thể, xếp theo mức tiềm năng.", prompt, "Ngách, nền tảng, đối tượng xem và link kênh nếu có.", "Danh sách 10 ý tưởng content có góc tiếp cận, lý do và mức tiềm năng.", steps, notes, json.dumps(sections, ensure_ascii=False), skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='seo-video-youtube'").fetchone()["id"]
    prompt = """Video của tôi đang ở [link video/đang mở sẵn trong YouTube Studio]. SEO đầy đủ cho video này:
- Dùng \"Hỏi Studio\" lấy timeline/chương thật từ transcript, đặt gần cuối mô tả.
- Thêm 2 thẻ (Cards) video liên quan, dựng màn hình kết thúc mẫu \"2 video\".
- Thêm từ khoá: kết hợp từ ngắn + cụm tìm kiếm dài 4-6 từ, gần đầy 500 ký tự.
- Đối chiếu tiêu đề với các video win nhất kênh, chỉnh nếu lệch pattern.
- Dựng mô tả đúng thứ tự: intro/hook → khối mặc định của tôi (nếu có, xem dưới) → timeline → hashtag.
- Bấm Lưu, xác nhận đã lưu thành công.

Khối mặc định của tôi (nếu có, dùng lại cho mọi video): [dán khối mặc định của bạn ở đây, hoặc bỏ trống nếu chưa có]."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Dán câu cài Skill vào Claude Code hoặc Codex có bật công cụ trình duyệt.

Bước 2 — Đưa link video + khối mặc định (lần đầu)
Điền link video và khối mặc định cuối mô tả nếu kênh có; chỉ cần đưa khối mặc định một lần để AI dùng lại.

Bước 3 — Để AI tự làm đủ 7 phần trong YouTube Studio
AI mở trang Chi tiết video, làm timeline → thẻ → màn hình kết thúc → từ khoá → tiêu đề → mô tả → hashtag → Lưu.

Bước 4 — Kiểm lại và công khai video khi sẵn sàng
Mở lại trang Chi tiết video kiểm tiêu đề/mô tả/từ khoá và timeline có khớp nội dung thật không."""
    notes = "Chưa có khối mặc định cũng không sao — AI vẫn làm các phần còn lại. Chưa ưng tiêu đề hoặc phần nào thì nhắn sửa trong cùng cuộc trò chuyện, AI sửa và lưu lại."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Quy trình SEO 7 phần trong YouTube Studio: timeline, thẻ, màn hình kết thúc, từ khoá, tiêu đề, mô tả, hashtag."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một video vừa upload ở trạng thái không công khai, link video và khối mặc định cuối mô tả nếu có."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"SEO đầy đủ 1 video vừa upload lên kênh\n\n1. Upload 1 video lên kênh, để Không công khai trong lúc SEO\n2. Chuẩn bị khối mặc định cuối mô tả nếu có\n3. Làm theo 3 bước trên\n4. Kiểm lại trang Chi tiết video, rồi công khai khi ưng ý\n\nXong sẽ có: Video có đủ chương mục, 2 thẻ liên quan, màn hình kết thúc, từ khoá, tiêu đề, mô tả và hashtag; đã lưu thành công trên YouTube Studio."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Tối ưu tiêu đề, mô tả, thẻ tag, timeline và thumbnail để video lên đề xuất nhanh hơn", "Đưa 1 video mới đăng vào — AI tự vào YouTube Studio làm timeline/chương, thẻ, màn hình kết thúc, từ khoá, tiêu đề, mô tả và hashtag rồi lưu thật.", prompt, "Video YouTube không công khai, link video và khối mặc định nếu có.", "Video YouTube đã lưu đủ 7 phần SEO trong Studio.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://studio.youtube.com/", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='dang-bai-tu-dong-da-kenh'").fetchone()["id"]
    prompt = """Kênh Facebook của tôi: [dán link]. Viết cho tôi 1 bài về [chủ đề/ý tưởng], đúng giọng văn kênh tôi:
- Đọc qua các bài gần đây trên kênh để bắt đúng nhịp câu, cách xưng hô, kiểu mở bài, CTA.
- Tự chọn định dạng phù hợp (bài chữ/ảnh đơn/carousel/Reel) và giải thích ngắn gọn vì sao — đừng hỏi tôi chọn.
- Viết luôn nội dung trên từng ảnh hoặc kịch bản video đi kèm.
- Không bịa trải nghiệm, số liệu hay kết quả tôi chưa cung cấp.
- Cho tôi xem bản cuối để duyệt. Chưa đăng gì khi tôi chưa nói rõ."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
AI của bạn đọc và nạp được Skill này, dùng lại được cho lần sau.

Bước 2 — Đưa link kênh và ý tưởng
Dán câu nhờ việc mẫu kèm link kênh Facebook. Lần đầu AI hỏi thêm mục tiêu, ảnh được phép dùng, đăng ngay hay hẹn giờ — trả lời một lần để AI ghi nhớ.

Bước 3 — Nhận bài, duyệt và chỉnh
AI trình bày bài viết, định dạng đi kèm, nội dung từng ảnh/kịch bản video và lý do chọn. So với bài cũ của chính kênh: nhịp câu, cách xưng hô có giống không.

Bước 4 — Xác nhận đăng hoặc lên lịch
Nói rõ đăng ngay hay hẹn giờ, kèm múi giờ. AI điền sẵn mọi thứ trong Meta Business Suite và dừng trước nút Đăng/Lên lịch để chờ bạn xác nhận cuối."""
    notes = "Chưa ưng thì nhắn chỉnh cụ thể trong cùng cuộc trò chuyện. AI không tự đăng khi bạn chưa xác nhận; bạn tự đăng nhập Facebook, AI không đọc hay lưu mật khẩu hoặc OTP."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Học giọng kênh, chọn định dạng bài chữ/ảnh/carousel/Reel, viết nội dung đi kèm, xin duyệt rồi chuẩn bị đăng hoặc lên lịch Facebook."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Link kênh Facebook chính chủ, một ý tưởng/chủ đề và ảnh thật được phép dùng nếu cần."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Viết và đăng 1 bài đầu tiên đúng giọng kênh bạn\\n\\n1. Đưa link kênh Facebook chính chủ\\n2. Chọn một ý tưởng và, nếu cần, một ảnh thật được phép dùng\\n3. Làm theo các bước trên\\n4. So bài AI viết với một bài cũ của kênh, rồi duyệt đăng hoặc hẹn giờ\\n\\nXong sẽ có: Một bài Facebook kèm nội dung ảnh/kịch bản nếu có, đúng giọng quen thuộc của kênh, đã qua bạn duyệt và sẵn sàng đăng hoặc lên lịch."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Viết bài Facebook đúng giọng kênh, kèm nội dung ảnh/carousel/video và chuẩn bị đăng hoặc lên lịch", "Đưa link kênh Facebook và ý tưởng — AI học giọng kênh, tự chọn định dạng, viết bài cùng nội dung ảnh/kịch bản, chờ bạn duyệt trước khi đăng.", prompt, "Link kênh Facebook, chủ đề/ý tưởng, ảnh thật được phép dùng và thời điểm đăng nếu đã có.", "Bài Facebook đúng giọng kênh, nội dung đi kèm và bản chuẩn bị đăng/lên lịch sau khi bạn duyệt.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://business.facebook.com/", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='tao-video-viral'").fetchone()["id"]
    prompt = """Làm video viral cho tôi từ: [ý tưởng/văn bản/URL/ảnh tham chiếu].
- Chọn đúng cấu trúc (tin tức/review/giới thiệu) theo nội dung.
- Ưu tiên tuyệt đối ảnh/video thật liên quan trực tiếp — nếu không đủ tư liệu thật, dừng lại và báo tôi thiếu gì, đừng tự tạo hình AI giả làm bằng chứng.
- Phụ đề karaoke theo đúng lời đọc, chữ tiếng Việt phải đúng dấu, không tràn/che mặt.
- Thời lượng: [45 giây / điền số khác nếu có].
- Cho tôi xem contact sheet/preview trước, tôi duyệt rồi mới xuất MP4. Nếu máy chưa có công cụ dựng thì tự cài trước.
Xong việc thì cho tôi biết file kết quả nằm ở đâu."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Skill này cần AI có thể chạy công cụ dựng video thực tế trên máy.

Bước 2 — Đưa ý tưởng/nguồn và media thật nếu có
Dán câu nhờ việc mẫu, điền ý tưởng/văn bản/URL, đính kèm ảnh hoặc video thật nếu có sẵn. Nếu không đủ tư liệu thật, AI phải dừng và báo rõ phần thiếu.

Bước 3 — Để AI cài môi trường lần đầu rồi dựng bản nháp
Trên máy mới, AI cài công cụ dựng cần thiết; sau đó nghiên cứu, tìm/tải media, viết kịch bản và dựng preview.

Bước 4 — Duyệt contact sheet, xuất MP4
Kiểm hook 2 giây đầu, chữ tiếng Việt và tính phù hợp của media trên preview. Chỉ nói xuất sau khi đã ưng bản nháp."""
    notes = "Ưu tiên media thật liên quan trực tiếp. Nếu media không đủ, yêu cầu AI báo thiếu thay vì dùng hình AI giả làm bằng chứng. Sửa ở bản nháp trước khi render lại để tránh tốn thời gian."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Dựng video dọc 9:16 theo công thức tin tức/review/giới thiệu, hook 2 giây đầu, media thật và phụ đề karaoke tiếng Việt chuẩn."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ý tưởng, văn bản, URL hoặc ảnh tham chiếu; ảnh/video thật liên quan nếu bạn có sẵn."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Dựng một video viral 45 giây từ một chủ đề bạn đang quan tâm\\n\\n1. Chọn chủ đề tin tức/review/giới thiệu có ảnh hoặc video thật liên quan\\n2. Làm theo các bước trên\\n3. Xem contact sheet trước khi xuất: hook, chữ tiếng Việt, media\\n4. Xuất MP4 và xem lại trên điện thoại trước khi đăng\\n\\nXong sẽ có: Một video dọc 9:16 có hook rõ trong 2 giây đầu, phần lớn hình ảnh là media thật, phụ đề karaoke khớp lời và chữ tiếng Việt không lỗi dấu."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Tạo video dọc viral từ ý tưởng hoặc tư liệu thật, có hook, phụ đề karaoke và bản MP4 hoàn chỉnh", "Đưa ý tưởng, văn bản, URL hoặc ảnh tham chiếu — AI chọn cấu trúc phù hợp, dùng media thật, dựng preview 9:16 để bạn duyệt rồi mới xuất MP4.", prompt, "Ý tưởng/văn bản/URL/ảnh tham chiếu và media thật liên quan nếu có.", "Video 9:16 MP4 có hook, media thật, phụ đề karaoke khớp lời và chữ tiếng Việt đúng dấu.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org/", skill_id))

    skill_id = database.execute("SELECT id FROM skills WHERE slug='reel-facebook-viral'").fetchone()["id"]
    prompt = """Làm Reel Facebook cho tôi.
Kênh mẫu để học cấu trúc: [link kênh mẫu].
Fanpage sẽ đăng: [link fanpage].
Thư mục làm việc đặt ở: [đường dẫn thư mục].
- Học cấu trúc của kênh mẫu (chủ đề, hook, mật độ chữ, độ dài caption) nhưng KHÔNG sao chép câu chữ, danh tính hay tư liệu của họ.
- Dựng kho làm việc, mở các thư mục để tôi bỏ video/nhạc/logo vào, rồi làm tiếp.
- Nội dung chữ trên Reel: [dán nội dung đã duyệt, giữ nguyên từng chữ — hoặc ghi "hãy soạn bản nháp cho tôi xem trước"].
- Dựng Reel 9:16, kiểm tra xem trước ở nhiều mốc thời gian, tự sửa nếu chữ tràn hay logo che chủ thể.
- Cho tôi xem video + caption. KHÔNG đăng khi tôi chưa nói rõ "Duyệt".
Nếu máy chưa có ffmpeg/Python thì tự cài trước. Không đọc hay lưu mật khẩu/OTP của tôi."""
    steps = """Bước 1 — Cài Skill vào AI của bạn
Skill này cần AI có thể chạy công cụ dựng video thực tế trên máy.

Bước 2 — Đưa kênh mẫu, fanpage và bỏ tư liệu vào kho
Điền link kênh mẫu và fanpage. AI dựng kho làm việc với ba thư mục video gốc, nhạc nền, logo để bạn bỏ tư liệu của mình vào.

Bước 3 — Duyệt nội dung và xem Reel AI dựng
Đưa nội dung chữ đã duyệt hoặc yêu cầu bản nháp. AI dựng Reel, xem preview ở 25%/50%/75% thời lượng, sửa lỗi chữ tràn hoặc logo che chủ thể trước khi đưa bạn xem.

Bước 4 — Xác nhận để AI đăng hoặc lên lịch
AI chuẩn bị tải Reel, caption và giờ trống; dừng lại với bản tóm tắt trang, tên file, đầu caption, ngày giờ. Chỉ bấm khi bạn nói rõ Duyệt hoặc Lên lịch."""
    notes = "Chỉ dùng nhạc và video bạn có quyền sử dụng. Lời duyệt cho video cũ không có giá trị cho video mới; AI phải xin xác nhận lại cho từng Reel và không tự đăng trùng khi không chắc giao dịch trước đã thành công."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Học cấu trúc kênh mẫu, dựng Reel dọc 9:16 từ kho video của bạn, thêm chữ cố định/nhạc nền, kiểm preview và chuẩn bị đăng hoặc hẹn lịch sau duyệt."},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Link kênh mẫu, link fanpage, thư mục làm việc, video/nhạc/logo bạn có quyền dùng và nội dung chữ đã duyệt."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Dựng và hẹn giờ đăng một Reel đầu tiên\\n\\n1. Chuẩn bị 2-3 video ngắn, một bài nhạc có quyền dùng và một đoạn chữ ngắn đã duyệt\\n2. Làm theo các bước trên\\n3. Xem Reel trên điện thoại: chữ có đọc được, logo có che gì không\\n4. Hẹn giờ đăng và kiểm Reel xuất hiện trong danh sách bài đã hẹn\\n\\nXong sẽ có: Một Reel 9:16 khoảng 20 giây có chữ cố định rõ, nhạc nền, đã qua bạn duyệt và nằm trong lịch đăng fanpage; kho ghi lại tư liệu đã dùng."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Xây quy trình Reel Facebook từ kho tư liệu, có preview và hẹn lịch đăng sau khi bạn duyệt", "Đưa kênh mẫu, fanpage và tư liệu của bạn — AI học cấu trúc, dựng Reel 9:16, kiểm preview rồi chỉ chuẩn bị đăng/lên lịch khi bạn xác nhận.", prompt, "Link kênh mẫu, fanpage, thư mục làm việc, video/nhạc/logo được phép dùng và nội dung chữ.", "Reel 9:16 với caption, preview đã kiểm, sẵn sàng đăng hoặc đã hẹn lịch sau xác nhận.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://ffmpeg.org/", skill_id))


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


@app.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, bool]:
    if authorization and authorization.startswith("Bearer "):
        with connection() as database:
            database.execute("DELETE FROM sessions WHERE token=?", (authorization.removeprefix("Bearer "),))
    return {"ok": True}


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


@app.get("/skills/{slug}")
def skill_detail(slug: str, authorization: str | None = Header(default=None)) -> dict[str, object]:
    with connection() as database:
        skill = database.execute(
            "SELECT skills.slug,skills.title,skills.description,skills.tag,skills.price,skills.status,"
            "skills.legacy_tool,skill_categories.name AS hall,skill_content.content_state,skill_content.preview_text,"
            "skill_content.workflow_text,skill_content.prompt_text,skill_content.input_notes,"
            "skill_content.output_notes,skill_content.steps_text,skill_content.notes_text,"
            "skill_content.owned_sections_json,skill_content.resource_url,skill_content.tutorial_url "
            "FROM skills JOIN skill_categories ON skills.category_id=skill_categories.id "
            "JOIN skill_content ON skill_content.skill_id=skills.id WHERE skills.slug=?",
            (slug,),
        ).fetchone()
        if skill is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Skill.")
        user_id = None
        if authorization and authorization.startswith("Bearer "):
            session = database.execute(
                "SELECT user_id FROM sessions WHERE token=?", (authorization.removeprefix("Bearer "),)
            ).fetchone()
            user_id = session["user_id"] if session else None
        owned = False
        if user_id:
            owned = bool(database.execute(
                "SELECT 1 FROM skill_purchases JOIN skills ON skills.id=skill_purchases.skill_id "
                "WHERE skill_purchases.user_id=? AND skills.slug=?", (user_id, slug)
            ).fetchone())
    payload = dict(skill)
    if not owned:
        # The sales page can describe a Skill, but its real workflow and prompt
        # are available only after purchase.
        for field in ("workflow_text", "prompt_text", "steps_text", "notes_text", "resource_url", "tutorial_url"):
            payload[field] = None
    return {"skill": payload, "owned": owned}


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
        # A provider transaction is normally handled exactly once.  Skill
        # ownership is deliberately reconciled on a replay as well: this is a
        # safe repair for an interrupted delivery, while a credit top-up is
        # never credited a second time.
        existing_transaction = database.execute(
            "SELECT order_code FROM payment_transactions WHERE provider_id=?",
            (provider_id,),
        ).fetchone()
        if existing_transaction:
            order = database.execute(
                "SELECT * FROM payment_orders WHERE code=?",
                (existing_transaction["order_code"],),
            ).fetchone()
            if order and order["order_type"] == "SKILL_PURCHASE" and order["skill_slug"]:
                skill = database.execute(
                    "SELECT id FROM skills WHERE slug=?",
                    (order["skill_slug"],),
                ).fetchone()
                if skill:
                    database.execute(
                        "INSERT INTO skill_purchases(user_id,skill_id,order_code) VALUES (?,?,?) "
                        "ON CONFLICT(user_id,skill_id) DO NOTHING",
                        (order["user_id"], skill["id"], order["code"]),
                    )
            return {"ok": True}
        # Do not use SQL LIKE with literal percent signs here. psycopg reserves
        # percent syntax for bound values, which previously caused a 500 only
        # when SePay delivered a payment. Use the native string-search function
        # for each supported database instead.
        if is_postgres():
            order = database.execute(
                "SELECT * FROM payment_orders WHERE status='pending' AND POSITION(code IN ?) > 0",
                (content,),
            ).fetchone()
        else:
            order = database.execute(
                "SELECT * FROM payment_orders WHERE status='pending' AND instr(?, code) > 0",
                (content,),
            ).fetchone()
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
