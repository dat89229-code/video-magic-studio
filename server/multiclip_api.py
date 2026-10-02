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
    """Import only the first purchased Skill whose source content was verified.

    The remaining Skills intentionally stay CONTENT_MISSING until their actual
    customer-authorized materials have been reviewed and imported.
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
        "- Giữ đúng khuôn mặt như ảnh gốc — đây là ảnh thật của tôi, không phải nhân vật hư cấu, sai mặt là không dùng được.\n"
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
Chụp hoặc chọn một ảnh thấy rõ toàn bộ sản phẩm, đọc được chữ trên nhãn, không bị loá sáng. Nền gì cũng được — bối cảnh sẽ thay hết.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
Bấm kẹp giấy tải ảnh sản phẩm lên, bấm nút Chép ở đầu trang rồi dán câu lệnh vào, gửi.

Bước 3 — Duyệt bản đồ concept rồi cho chạy
Đọc 10 concept, thấy cái nào không hợp thì nói thẳng: “Concept 4 và 7 quá giống nhau, đổi concept 7 sang bối cảnh ngoài trời.” Ưng rồi thì bảo tạo ảnh.

Bước 4 — Soi lại sản phẩm trên từng tấm
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
Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
Bấm biểu tượng kẹp giấy hoặc dấu cộng để tải ảnh sản phẩm lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Tải về và kiểm ba chỗ
Bấm vào ảnh kết quả để tải về. Trước khi đăng, phóng to kiểm viền sản phẩm, chữ trên bao bì và màu sản phẩm."""
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
Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên, mô tả CHÍNH XÁC vùng cần xoá
Bấm biểu tượng kẹp giấy để tải ảnh lên. Điền rõ vị trí và mô tả thứ cần xoá vào câu lệnh (ví dụ 'logo hình tròn màu đỏ ở góc trên bên trái') rồi gửi.

Bước 3 — Phóng to kiểm đúng vùng vừa xoá
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
Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được việc này.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
Bấm biểu tượng kẹp giấy để tải ảnh lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Soi kỹ khuôn mặt trước khi dùng
Phóng to phần mặt, đặt cạnh ảnh gốc mà so. Nhìn kỹ dáng mũi, khoảng cách hai mắt, nếp cười — đây là ba chỗ máy hay đổi nhất mà nhìn lướt không thấy."""
    notes = """Ảnh thờ, ảnh gia đình, ảnh hồ sơ xin việc — những ảnh BẮT BUỘC phải đúng mặt — thì đừng dùng cách này. Chat AI vẽ lại khuôn mặt nên rất hay ra người khác.

Thấy khác người thì nhắn lại: 'Ảnh này ra người khác rồi. Làm lại, ưu tiên giữ đúng khuôn mặt gốc, chấp nhận ảnh kém đẹp hơn.'"""
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm\n\nCách xử lý lỗi hay gặp\nPhần mà hướng dẫn miễn phí trên mạng gần như không bao giờ có"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh chân dung cần làm rõ nét, cân sáng hoặc làm mịn da. Với ảnh bắt buộc đúng mặt, dùng dây chuyền cài về máy thay vì Chat AI."},{"number":"04","title":"Làm theo 3 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Cứu một ảnh chân dung mờ trong điện thoại thành ảnh dùng được\n\n1. Chọn một ảnh chân dung bị mờ hoặc thiếu sáng\n2. Làm theo 3 bước trên\n3. Đặt ảnh mới cạnh ảnh gốc, phóng to phần mặt mà so\n4. Vẫn đúng người và nét hơn hẳn thì lưu lại dùng\n\nXong sẽ có: Ảnh nét hơn, sáng hơn, da mịn vừa phải mà vẫn nhận ra đúng người — không thành một gương mặt lạ."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=?, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Nét, đẹp mặt mà vẫn đúng người thật, cân màu, mịn da — sáu bước một lượt", "Làm đẹp ảnh chân dung ngay trên ChatGPT hoặc Gemini, không cần cài gì. Cần GIỮ ĐÚNG khuôn mặt thật thì cài dây chuyền 6 bước về máy, vì chat AI hay vẽ ra người khác.", prompt, "Một ảnh chân dung bị mờ, thiếu sáng hoặc cần cân màu.", "Ảnh nét hơn, sáng hơn và da mịn vừa phải, vẫn nhận ra đúng người.", steps, notes, json.dumps(sections, ensure_ascii=False), "https://github.com/sczhou/CodeFormer", skill_id))

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
Mở app trên điện thoại hoặc vào trang web trên máy tính. Bản miễn phí làm được.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
Bấm biểu tượng kẹp giấy để tải ảnh mờ lên. Rồi bấm nút Chép ở đầu trang, dán câu lệnh vào, gửi.

Bước 3 — Kiểm chữ trước khi dùng
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
Chọn ảnh thấy rõ nhân vật hoặc vật thể chính, đủ sáng, không bị che khuất. Ảnh càng rõ thì các góc mới càng nhất quán.

Bước 2 — Tải ảnh lên rồi dán câu lệnh
Bấm kẹp giấy tải ảnh lên, bấm nút Chép ở đầu trang rồi dán câu lệnh vào, gửi. Muốn số góc khác 9 thì sửa thẳng con số trong câu lệnh.

Bước 3 — Duyệt danh sách góc rồi cho chạy
Đọc danh sách, thấy góc nào trùng ý thì đổi: 'Góc 3 và góc 6 gần giống nhau, đổi góc 6 thành nhìn từ trên xuống.' Ưng rồi thì bảo tạo ảnh.

Bước 4 — Kiểm tính nhất quán
Đặt các tấm cạnh nhau, soi ba thứ: trang phục có đổi không, ánh sáng chiếu cùng hướng không, đạo cụ có còn nguyên chỗ không."""
    notes = "Ảnh chỉ thấy nửa mặt hoặc bị che nhiều thì máy phải tự bịa phần khuất — các góc sẽ lệch nhau. Muốn STORYBOARD phim thay vì các góc rời: thêm chữ 'Video' vào câu nhờ. Định dùng làm keyframe video thì tính nhất quán quan trọng hơn ảnh đẹp. Tấm nào lệch thì bỏ, đừng tiếc."
    sections = [{"number":"01","title":"Skill này gồm những gì","body":"Câu lệnh làm việc cho AI\nDán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay, không cài gì\n\nLàm được trên điện thoại\nKhông cần máy tính mạnh, không cần card đồ hoạ, không phải tải phần mềm"},{"number":"02","title":"Chuẩn bị trước khi bắt đầu","body":"Một ảnh tham chiếu rõ nhân vật hoặc vật thể chính, đủ sáng và không bị che khuất."},{"number":"04","title":"Làm theo 4 bước","body":steps},{"number":"05","title":"Làm thử ngay","body":"Tạo 9 góc quay từ một ảnh chân dung của bạn\n\n1. Chọn một ảnh chân dung rõ mặt, đủ sáng\n2. Làm theo 4 bước trên\n3. Đặt 9 tấm cạnh nhau, kiểm trang phục và hướng sáng\n4. Làm lại một lần nữa, lần này thêm chữ 'Video' để xem storyboard khác thế nào\n\nXong sẽ có: Chín tấm nhìn ra ngay là cùng một người, cùng bộ đồ, cùng khoảnh khắc — chỉ khác chỗ đặt máy quay."}]
    database.execute("UPDATE skill_content SET content_state='READY', preview_text=?, workflow_text=?, prompt_text=?, input_notes=?, output_notes=?, steps_text=?, notes_text=?, owned_sections_json=?, resource_url=NULL, tutorial_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE skill_id=?", ("Một ảnh ra nhiều góc quay nhất quán, dùng làm keyframe video hoặc storyboard", "Đưa MỘT ảnh, nhận về NHIỀU góc quay của cùng một khoảnh khắc — nhất quán đủ để làm keyframe video. Thêm chữ 'Video' vào câu nhờ thì đổi sang dựng storyboard điện ảnh. Không cài gì.", prompt, "Một ảnh tham chiếu rõ nhân vật hoặc vật thể chính.", "Chín góc quay khác nhau rõ rệt của cùng một khoảnh khắc.", steps, notes, json.dumps(sections, ensure_ascii=False), skill_id))


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
