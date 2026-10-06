import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  Bell,
  Check,
  ChevronLeft,
  Clapperboard,
  Film,
  Gem,
  Headphones,
  ImageIcon,
  Menu,
  MessageCircle,
  Music2,
  Play,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  SlidersHorizontal,
  Sparkles,
  User,
  Upload,
  Wand2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

const API = (
  (import.meta.env.VITE_API_URL ||
    (typeof window !== "undefined"
      ? window.location.hostname.endsWith(".workers.dev")
        ? "/api"
        : window.location.hostname.endsWith(".onrender.com")
          ? "https://video-magic-api-fp7a.onrender.com"
          : "http://127.0.0.1:8787"
      : "http://127.0.0.1:8787")) as string
).replace(/\/$/, "");
// The dedicated Skill deployment sets this at build time. The existing Video
// deployment keeps its code path intact, allowing both apps to share a repo.
const SKILL_APP = import.meta.env.VITE_APP_SURFACE === "skill";
// Support is intentionally independent of the existing Skill/payment API so
// the AI assistant can be deployed and configured in staging on its own.
const SUPPORT_API = (import.meta.env.VITE_SUPPORT_API_URL || API).replace(/\/$/, "");
const SESSION_KEY = "master-clip-session-token";
const PROVIDER_PHONE = "0976440998";
const ZALO_CONTACT_URL = `https://zalo.me/${PROVIDER_PHONE}`;
export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Master Clip — AI Skill World" }] }),
  component: Index,
});
type Hall =
  | "Tất cả"
  | "Sửa ảnh AI"
  | "Tạo ảnh AI"
  | "Edit Video"
  | "Video AI/Viral"
  | "Marketing & Social Media";
type Skill = {
  slug: string;
  title: string;
  hall: Exclude<Hall, "Tất cả">;
  description: string;
  tag: string;
  status?: string;
  legacy?: boolean;
  price?: number;
};
const TRAFFIC_SKILL_SLUG = "poster-san-pham";
const TRAFFIC_SKILL_PRICE = 10_000;
const STANDARD_SKILL_PRICE = 50_000;
const skillPrice = (skill: Skill) => skill.price ?? (skill.slug === TRAFFIC_SKILL_SLUG ? TRAFFIC_SKILL_PRICE : STANDARD_SKILL_PRICE);
const formatVnd = (amount: number) => `${amount.toLocaleString("vi-VN")}đ`;
type SkillContent = {
  content_state: "READY" | "CONTENT_MISSING";
  preview_text?: string | null;
  workflow_text?: string | null;
  prompt_text?: string | null;
  input_notes?: string | null;
  output_notes?: string | null;
  steps_text?: string | null;
  notes_text?: string | null;
  owned_sections_json?: string | null;
  resource_url?: string | null;
  tutorial_url?: string | null;
};
const halls: {
  name: Exclude<Hall, "Tất cả">;
  description: string;
  icon: LucideIcon;
  accent: string;
}[] = [
  {
    name: "Sửa ảnh AI",
    description: "Biến ảnh sản phẩm và chân dung chỉ trong vài bước.",
    icon: ImageIcon,
    accent: "#e487a3",
  },
  {
    name: "Tạo ảnh AI",
    description: "Tạo visual đẹp, đồng nhất với thương hiệu.",
    icon: Sparkles,
    accent: "#d886a5",
  },
  {
    name: "Edit Video",
    description: "Cắt, dựng và đóng gói video bán hàng.",
    icon: Clapperboard,
    accent: "#ad6f9c",
  },
  {
    name: "Video AI/Viral",
    description: "Thiết kế nội dung ngắn có khả năng lan tỏa.",
    icon: Film,
    accent: "#ba7590",
  },
  {
    name: "Marketing & Social Media",
    description: "Xây kênh và vận hành nội dung thông minh.",
    icon: Wand2,
    accent: "#c78ca5",
  },
];
const skills: Skill[] = [
  [
    "thuong-hieu-ca-nhan",
    "Thương hiệu cá nhân & Text Overlay",
    "Sửa ảnh AI",
    "Tạo lớp chữ và hình ảnh nhất quán cho thương hiệu.",
    "Ảnh",
  ],
  [
    "poster-san-pham",
    "Poster sản phẩm",
    "Sửa ảnh AI",
    "Thiết kế poster sản phẩm thu hút cho chiến dịch.",
    "Ảnh",
  ],
  [
    "xoa-nen-anh",
    "Xóa nền ảnh",
    "Sửa ảnh AI",
    "Tách chủ thể sạch sẽ, sẵn sàng cho mọi bối cảnh.",
    "Ảnh",
  ],
  [
    "xoa-logo-anh",
    "Xóa logo, vật thể",
    "Sửa ảnh AI",
    "Làm sạch chi tiết thừa trong ảnh sản phẩm.",
    "Ảnh",
  ],
  [
    "chinh-sua-anh",
    "Chỉnh sửa ảnh",
    "Sửa ảnh AI",
    "Làm nét, cân sáng và nâng chất lượng ảnh.",
    "Ảnh",
  ],
  [
    "tang-chat-luong-4k",
    "Tăng chất lượng 4K",
    "Sửa ảnh AI",
    "Nâng độ phân giải ảnh một cách tự nhiên.",
    "Ảnh",
  ],
  [
    "multishot",
    "Multishot",
    "Tạo ảnh AI",
    "Tạo nhiều góc hình đồng bộ cho một ý tưởng.",
    "AI Image",
  ],
  [
    "hoan-doi-nhan-vat",
    "Hoán đổi nhân vật",
    "Tạo ảnh AI",
    "Thay đổi nhân vật trong bố cục hình ảnh.",
    "AI Image",
  ],
  [
    "dang-1-thoai-thumbnail",
    "Talking-head cơ bản",
    "Edit Video",
    "Cắt gọn video nói chuyện và tạo thumbnail mở đầu.",
    "Video",
    undefined,
    true,
  ],
  [
    "dang-2-hieu-ung-cao-cap",
    "Talking-head hiệu ứng cao cấp",
    "Edit Video",
    "Nâng cấp nhịp dựng, zoom, overlay và caption.",
    "Video",
  ],
  [
    "dang-3-huong-dan-toi-gian",
    "Video hướng dẫn tối giản",
    "Edit Video",
    "Định dạng guide tinh gọn, tập trung vào nội dung.",
    "Video",
    "Sắp mở",
  ],
  [
    "dang-4-infographic-trang",
    "Talking-head infographic",
    "Edit Video",
    "Video nói chuyện cùng các lớp infographic sáng.",
    "Video",
  ],
  [
    "cap-do-1-khung-don",
    "Video dài → Short",
    "Edit Video",
    "Tìm và cắt các đoạn hay từ video dài thành short.",
    "Đang phát triển",
    undefined,
    true,
  ],
  [
    "cap-do-2-postcard-2-nguoi",
    "Podcast 2 người → Short",
    "Edit Video",
    "Khung postcard linh hoạt cho podcast hai người.",
    "Video",
  ],
  [
    "multiclip-ghep-nhac-trend",
    "Nhiều clip + Nhạc trend",
    "Edit Video",
    "Ghép nhiều clip thành video dọc theo nhịp nhạc.",
    "Đang hoạt động",
    undefined,
    true,
  ],
  [
    "multiclip-1-video-highlight",
    "AI cắt highlight theo nhạc",
    "Edit Video",
    "Tự chọn highlight đẹp và đồng bộ nhịp nhạc.",
    "Video",
  ],
  [
    "edit-video-zoom",
    "Edit video Zoom tự động",
    "Edit Video",
    "Đóng gói buổi Zoom dài thành series rõ ràng.",
    "Video",
  ],
  [
    "video-tu-dong-google-flow",
    "Tạo video AI với Flow",
    "Video AI/Viral",
    "Biến ý tưởng và tư liệu thành video AI.",
    "AI Video",
  ],
  [
    "tao-video-viral",
    "Tạo video viral",
    "Video AI/Viral",
    "Tạo video dọc viral cho quảng cáo và kênh bán hàng.",
    "AI Video",
  ],
  [
    "reel-facebook-viral",
    "Xây kênh Facebook Reels",
    "Video AI/Viral",
    "Quy trình tạo Reels có chiến lược cho thương hiệu.",
    "Viral",
  ],
  [
    "subagent-cham-soc",
    "Subagent chăm sóc khách hàng",
    "Marketing & Social Media",
    "Trợ lý AI hỗ trợ vận hành và chăm sóc khách.",
    "Agent",
  ],
  [
    "subagent-nghien-cuu",
    "Subagent nghiên cứu",
    "Marketing & Social Media",
    "Thu thập insight để chuẩn bị nội dung nhanh hơn.",
    "Agent",
  ],
  [
    "seo-video-youtube",
    "SEO video YouTube",
    "Marketing & Social Media",
    "Tối ưu tiêu đề, mô tả và cơ hội tìm kiếm.",
    "SEO",
  ],
  [
    "dang-bai-tu-dong-da-kenh",
    "Viết & đăng bài đa kênh",
    "Marketing & Social Media",
    "Viết đúng giọng và chuẩn bị nội dung đa nền tảng.",
    "Social",
  ],
].map(([slug, title, hall, description, tag, status, legacy]) => ({
  slug,
  title,
  hall: hall as Skill["hall"],
  description,
  tag,
  status,
  legacy: Boolean(legacy),
}));
const coverByHall: Record<Exclude<Hall, "Tất cả">, string> = {
  "Sửa ảnh AI": "/cover-photo-edit.png",
  "Tạo ảnh AI": "/cover-image-ai.png",
  "Edit Video": "/cover-video-edit.png",
  "Video AI/Viral": "/cover-video-viral.png",
  "Marketing & Social Media": "/cover-marketing.png",
};
const coverBySkill: Record<string, string> = Object.fromEntries(
  skills.map((skill) => [skill.slug, `/skill-${skill.slug}.webp`]),
);
coverBySkill["thuong-hieu-ca-nhan"] = "/skill-thuong-hieu-ca-nhan-v4.png";
coverBySkill["poster-san-pham"] = "/skill-poster-san-pham-v4.png";
coverBySkill["xoa-nen-anh"] = "/skill-xoa-nen-anh-v4.png";
coverBySkill["xoa-logo-anh"] = "/skill-xoa-logo-anh-v4.png";
coverBySkill["chinh-sua-anh"] = "/skill-chinh-sua-anh-v5.png";
coverBySkill["tang-chat-luong-4k"] = "/skill-tang-chat-luong-4k-v5.png";
coverBySkill["multishot"] = "/skill-multishot-v5.png";
coverBySkill["hoan-doi-nhan-vat"] = "/skill-hoan-doi-nhan-vat-v5.png";
coverBySkill["dang-1-thoai-thumbnail"] = "/skill-dang-1-thoai-thumbnail-v4.png";
coverBySkill["dang-2-hieu-ung-cao-cap"] = "/skill-dang-2-hieu-ung-cao-cap-v4.png";
coverBySkill["dang-3-huong-dan-toi-gian"] = "/skill-dang-3-huong-dan-toi-gian-v4.png";
coverBySkill["dang-4-infographic-trang"] = "/skill-dang-4-infographic-trang-v4.png";
coverBySkill["cap-do-1-khung-don"] = "/skill-cap-do-1-khung-don-v4.png";
coverBySkill["cap-do-2-postcard-2-nguoi"] = "/skill-cap-do-2-postcard-2-nguoi-v4.png";
coverBySkill["multiclip-ghep-nhac-trend"] = "/skill-multiclip-ghep-nhac-trend-v4.png";
coverBySkill["multiclip-1-video-highlight"] = "/skill-multiclip-1-video-highlight-v4.png";
coverBySkill["edit-video-zoom"] = "/skill-edit-video-zoom-v4.png";
coverBySkill["video-tu-dong-google-flow"] = "/skill-video-tu-dong-google-flow-v4.png";
coverBySkill["subagent-cham-soc"] = "/skill-subagent-cham-soc-v4.png";
coverBySkill["subagent-nghien-cuu"] = "/skill-subagent-nghien-cuu-v4.png";
coverBySkill["seo-video-youtube"] = "/skill-seo-video-youtube-v4.png";
coverBySkill["dang-bai-tu-dong-da-kenh"] = "/skill-dang-bai-tu-dong-da-kenh-v4.png";
coverBySkill["tao-video-viral"] = "/skill-tao-video-viral-v4.png";
coverBySkill["reel-facebook-viral"] = "/skill-reel-facebook-viral-v4.png";
const coverTextBySkill: Record<string, string> = {
  "thuong-hieu-ca-nhan": "ẢNH\nTHƯƠNG HIỆU",
  "poster-san-pham": "POSTER\nSẢN PHẨM",
  "xoa-nen-anh": "TÁCH NỀN\nTRONG SUỐT",
  "xoa-logo-anh": "XÓA VẬT THỂ\nKHỎI ẢNH",
  "chinh-sua-anh": "CHỈNH SỬA\nẢNH",
  "tang-chat-luong-4k": "NÂNG ẢNH\n4K",
  "multishot": "MULTISHOT",
  "hoan-doi-nhan-vat": "HOÁN ĐỔI\nNHÂN VẬT",
  "dang-1-thoai-thumbnail": "TALKING-HEAD\nCƠ BẢN",
  "dang-2-hieu-ung-cao-cap": "HIỆU ỨNG\nCAO CẤP",
  "dang-3-huong-dan-toi-gian": "HƯỚNG DẪN\nTỐI GIẢN",
  "dang-4-infographic-trang": "VIDEO\nINFOGRAPHIC",
  "cap-do-1-khung-don": "VIDEO DÀI\n→ SHORT",
  "cap-do-2-postcard-2-nguoi": "PODCAST\n→ SHORT",
  "multiclip-ghep-nhac-trend": "CLIP + NHẠC\nTREND",
  "multiclip-1-video-highlight": "CẮT HIGHLIGHT\nTHEO NHẠC",
  "edit-video-zoom": "EDIT ZOOM\nTỰ ĐỘNG",
  "video-tu-dong-google-flow": "VIDEO AI\nVỚI FLOW",
  "tao-video-viral": "VIDEO VIRAL\n9:16",
  "reel-facebook-viral": "FACEBOOK REELS\nVIRAL",
  "subagent-cham-soc": "AGENT\nCHĂM SÓC",
  "subagent-nghien-cuu": "AGENT\nNGHIÊN CỨU",
  "seo-video-youtube": "SEO VIDEO\nYOUTUBE",
  "dang-bai-tu-dong-da-kenh": "ĐĂNG BÀI\nĐA KÊNH",
};
const lockedReferenceCovers = new Set([
  "thuong-hieu-ca-nhan",
  "poster-san-pham",
  "xoa-nen-anh",
  "xoa-logo-anh",
]);

function Index() {
  const [page, setPage] = useState<"home" | "skills" | "detail" | "mine" | "combo" | "studio">(
      "home",
    ),
    [hall, setHall] = useState<Hall>("Tất cả"),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState<Skill>(skills[14]),
    [menu, setMenu] = useState(false),
    [sidebarCompact, setSidebarCompact] = useState(false),
    [auth, setAuth] = useState(false),
    [zaloHelp, setZaloHelp] = useState(false),
    [pay, setPay] = useState(false),
    [notice, setNotice] = useState(""),
    [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [token, setToken] = useState(""),
    [account, setAccount] = useState<{ email: string; credits: number } | null>(null),
    [ownedSkills, setOwnedSkills] = useState<Skill[]>([]),
    [detailContent, setDetailContent] = useState<SkillContent | null>(null),
    [detailContentLoading, setDetailContentLoading] = useState(false),
    [order, setOrder] = useState<any>(null);
  async function loadOwned(activeToken = token) {
    if (!activeToken) return setOwnedSkills([]);
    const response = await fetch(`${API}/skills/mine`, { headers: { Authorization: `Bearer ${activeToken}` } });
    if (response.ok) {
      const data = await response.json();
      setOwnedSkills((data.skills || []).map((skill: Skill & { legacy_tool?: string }) => ({ ...skill, legacy: Boolean(skill.legacy_tool) })));
    }
  }
  useEffect(() => { void loadOwned(); }, [token]);
  useEffect(() => {
    void (async () => {
      setDetailContentLoading(true);
      try {
        const response = await fetch(`${API}/skills/${selected.slug}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (!response.ok) throw new Error("Không thể tải nội dung Skill.");
        const data = await response.json();
        setDetailContent(data.skill || null);
      } catch {
        setDetailContent(null);
      } finally {
        setDetailContentLoading(false);
      }
    })();
  }, [selected.slug, token]);
  useEffect(() => {
    const savedToken = window.localStorage.getItem(SESSION_KEY);
    if (!savedToken) return;
    void (async () => {
      try {
        const response = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${savedToken}` } });
        if (!response.ok) throw new Error("Session expired");
        setToken(savedToken);
        setAccount(await response.json());
        await loadOwned(savedToken);
      } catch {
        window.localStorage.removeItem(SESSION_KEY);
      }
    })();
  }, []);
  const listed = useMemo(
    () =>
      skills.filter(
        (s) =>
          (hall === "Tất cả" || s.hall === hall) &&
          `${s.title} ${s.description}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [hall, query],
  );
  const jump = (next: Hall = "Tất cả") => {
    setHall(next);
    setPage("skills");
    scrollTo({ top: 0, behavior: "smooth" });
  };
  const select = (s: Skill) => {
    setSelected(s);
    setPage("detail");
    scrollTo({ top: 0, behavior: "smooth" });
  };
  async function login(action: "login" | "register") {
    try {
      const r = await fetch(`${API}/auth/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        }),
        x = await r.json();
      if (!r.ok || !x.token) throw Error(x.detail || "Không thể đăng nhập.");
      setToken(x.token);
      window.localStorage.setItem(SESSION_KEY, x.token);
      setAccount(x.user);
      void loadOwned(x.token);
      setAuth(false);
      setNotice(`Chào ${x.user.email}. Tài khoản đã sẵn sàng.`);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Không thể kết nối tài khoản.");
    }
  }
  function logout() {
    if (token) void fetch(`${API}/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
    window.localStorage.removeItem(SESSION_KEY);
    setToken("");
    setAccount(null);
    setOwnedSkills([]);
    setAuth(false);
    setNotice("Bạn đã đăng xuất.");
  }
  async function checkout(plan: "starter" | "pro" | "studio") {
    if (!token) {
      setPay(false);
      setAuth(true);
      setNotice("Đăng nhập trước khi nạp credit.");
      return;
    }
    try {
      const r = await fetch(`${API}/orders/${plan}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }),
        x = await r.json();
      if (!r.ok) throw Error(x.detail || "Không tạo được đơn hàng.");
      setOrder(x);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Không thể tạo đơn hàng.");
    }
  }
  async function checkoutSkill(skill: Skill) {
    if (!token) {
      setAuth(true);
      setNotice("Đăng nhập trước khi mua Skill.");
      return;
    }
    try {
      const response = await fetch(`${API}/skills/${skill.slug}/orders`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Không tạo được đơn Skill.");
      setOrder({ ...data, kind: "skill" });
      setPay(true);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể tạo đơn Skill.");
    }
  }
  async function paymentCompleted() {
    await loadOwned();
    if (!token) return;
    const response = await fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
    if (response.ok) setAccount(await response.json());
  }
  return (
    <div className={`skill-world${sidebarCompact ? " sidebar-compact" : ""}`}>
      <Header
        page={page}
        setPage={setPage}
        openSkills={() => jump()}
        searchSkills={(search: string) => {
          setQuery(search);
          jump();
        }}
        skillOnly={SKILL_APP}
        openTools={() => {
          setSelected(skills.find((skill) => skill.slug === "multiclip-ghep-nhac-trend") || skills[0]);
          setPage("studio");
          scrollTo({ top: 0, behavior: "smooth" });
        }}
        account={account}
        auth={() => setAuth(true)}
        logout={logout}
        credit={() => {
          setOrder(null);
          setPay(true);
        }}
        menu={menu}
        setMenu={setMenu}
        sidebarCompact={sidebarCompact}
        setSidebarCompact={setSidebarCompact}
        notify={(message: string) => setNotice(message)}
      />
      {page === "home" && <Home skillOnly={SKILL_APP} jump={jump} select={select} openStudio={() => {
        setSelected(skills.find((skill) => skill.slug === "multiclip-ghep-nhac-trend") || skills[0]);
        setPage("studio");
        scrollTo({ top: 0, behavior: "smooth" });
      }} />}{" "}
      {page === "skills" && (
        <Skills
          hall={hall}
          setHall={setHall}
          query={query}
          setQuery={setQuery}
          skills={listed}
          select={select}
        />
      )}{" "}
      {page === "detail" && (
        <Detail
          skill={selected}
          skillOnly={SKILL_APP}
          owned={ownedSkills.some((skill) => skill.slug === selected.slug)}
          content={detailContent}
          loading={detailContentLoading}
          back={() => jump(selected.hall)}
          use={() =>
            !SKILL_APP && selected.legacy
              ? setPage("studio")
              : ownedSkills.some((skill) => skill.slug === selected.slug)
                ? document.getElementById("owned-skill-content")?.scrollIntoView({ behavior: "smooth", block: "start" })
                : void checkoutSkill(selected)
          }
        />
      )}{" "}
      {!SKILL_APP && page === "studio" && (
        <VideoStudio
          skill={selected}
          token={token}
          account={account}
          back={() => setPage("detail")}
          askAuth={() => setAuth(true)}
          setNotice={setNotice}
          setAccount={setAccount}
        />
      )}
      {page === "mine" && <MySkills skills={ownedSkills} browse={() => jump()} select={select} />}{" "}
      {page === "combo" && (
        <Combo
          skillOnly={SKILL_APP}
          credit={() => {
            setOrder(null);
            setPay(true);
          }}
        />
      )}
      <Footer />
      <button
        className="zalo-chat-button"
        aria-label={`Trò chuyện qua Zalo với Master Clip, số ${PROVIDER_PHONE}`}
        onClick={() => setZaloHelp(true)}
      >
        <MessageCircle size={19} />
        <span>Chat Zalo</span>
      </button>
      {zaloHelp && <ZaloAssistant close={() => setZaloHelp(false)} />}
      {auth && (
        <Auth
          close={() => setAuth(false)}
          email={email}
          password={password}
          setEmail={setEmail}
          setPassword={setPassword}
          login={login}
          account={account}
          logout={logout}
        />
      )}{" "}
      {pay && (
        <Payment
          close={() => setPay(false)}
          order={order}
          checkout={checkout}
          token={token}
          account={account}
          onPaid={paymentCompleted}
          skillOnly={SKILL_APP}
          openMine={() => {
            setPay(false);
            setPage("mine");
          }}
          useNow={() => {
            setPay(false);
            setPage(!SKILL_APP && selected.legacy ? "studio" : "detail");
          }}
        />
      )}{" "}
      {notice && (
        <div className="notice">
          <Check size={17} />
          {notice}
          <button onClick={() => setNotice("")}>
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
function ZaloAssistant({ close }: { close: () => void }) {
  const [messages, setMessages] = useState<{ from: "bot" | "user"; text: string }[]>([{ from: "bot", text: `Chào bạn! Cảm ơn bạn đã quan tâm Master Clip. Mình là trợ lý tư vấn trực tuyến, sẵn sàng hỗ trợ bạn chọn Skill hoặc Combo. Bạn cũng có thể liên hệ nhà cung cấp qua Zalo/số điện thoại ${PROVIDER_PHONE}.` }]);
  const [draft, setDraft] = useState("");
  const [isReplying, setIsReplying] = useState(false);
  const fallbackReply = (question: string) => {
    const text = question.toLowerCase();
    if (text.includes("combo") || text.includes("gói")) return "Bạn có thể vào mục Combo để xem các gói Skill. Hãy cho mình biết bạn muốn tạo ảnh, video hay làm nội dung bán hàng để mình hướng dẫn chọn gói phù hợp.";
    if (text.includes("đăng ký") || text.includes("tài khoản") || text.includes("mua") || text.includes("thanh toán")) return `Bạn có thể chọn Skill hoặc Combo, sau đó đăng nhập/đăng ký và làm theo bước thanh toán trên trang. Nếu cần nhà cung cấp kiểm tra đơn, hãy chat Zalo hoặc gọi ${PROVIDER_PHONE}.`;
    if (text.includes("skill") || text.includes("ảnh") || text.includes("video")) return "Mình có thể hỗ trợ bạn chọn Skill. Bạn cho mình biết mục tiêu: tạo ảnh viral, poster sản phẩm, video viral, hay chỉnh sửa ảnh/video?";
    return `Cảm ơn bạn đã chia sẻ. Mình sẽ hỗ trợ bạn ngay trong khung chat này; bạn cũng có thể trao đổi trực tiếp với nhà cung cấp qua Zalo/số ${PROVIDER_PHONE} khi cần tư vấn chi tiết.`;
  };
  const send = async (question: string) => {
    const clean = question.trim();
    if (!clean || isReplying) return;
    setMessages((items) => [...items, { from: "user", text: clean }]);
    setDraft("");
    setIsReplying(true);
    try {
      const response = await fetch(`${SUPPORT_API}/support/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: clean,
          history: messages.slice(-12).map((item) => ({
            role: item.from === "bot" ? "assistant" : "user",
            text: item.text,
          })),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || typeof data.reply !== "string") throw new Error(data.detail || "Support chat unavailable");
      setMessages((items) => [...items, { from: "bot", text: data.reply }]);
    } catch {
      setMessages((items) => [...items, { from: "bot", text: fallbackReply(clean) }]);
    } finally {
      setIsReplying(false);
    }
  };
  return <div className="modal-wrap zalo-assistant-wrap" role="dialog" aria-modal="true" aria-label="Trợ lý tư vấn Master Clip">
    <section className="modal zalo-assistant">
      <button className="modal-close" onClick={close} aria-label="Đóng trò chuyện"><X size={20} /></button>
      <p className="eyebrow"><MessageCircle size={15} /> TRỢ LÝ MASTER CLIP</p>
      <h2>Xin chào, tôi có thể giúp gì cho bạn?</h2>
      <p>Cảm ơn bạn đã ghé Master Clip. Hỏi về Skill, Combo, đăng ký hoặc cách sử dụng; nhà cung cấp: <strong>{PROVIDER_PHONE}</strong>.</p>
      <div className="zalo-message-list" aria-live="polite">{messages.map((message, index) => <p key={`${message.from}-${index}`} className={`zalo-message ${message.from}`}>{message.text}</p>)}{isReplying && <p className="zalo-message bot">Đang soạn câu trả lời…</p>}</div>
      <div className="zalo-quick-questions">
        {["Tư vấn chọn Skill", "Tư vấn Combo", "Đăng ký và thanh toán", "Tôi cần hướng dẫn sử dụng"].map((question) => <button key={question} disabled={isReplying} onClick={() => void send(question)}>{question}</button>)}
      </div>
      <form className="zalo-composer" onSubmit={(event) => { event.preventDefault(); void send(draft); }}>
        <input value={draft} disabled={isReplying} onChange={(event) => setDraft(event.target.value)} placeholder="Nhập câu hỏi của bạn..." aria-label="Câu hỏi cho trợ lý Master Clip" />
        <button className="btn-primary" disabled={isReplying} type="submit">{isReplying ? "Đang trả lời" : "Gửi"}</button>
      </form>
      <div className="zalo-contact-actions">
        <a className="zalo-open-link" href={ZALO_CONTACT_URL} target="_blank" rel="noreferrer"><MessageCircle size={17} /> Chat Zalo nhà cung cấp</a>
        <a className="zalo-call-link" href={`tel:${PROVIDER_PHONE}`}><Headphones size={17} /> Gọi {PROVIDER_PHONE}</a>
      </div>
    </section>
  </div>;
}
function Header(p: any) {
  const [search, setSearch] = useState("");
  const go = (x: "home" | "mine" | "combo") => {
    p.setPage(x);
    p.setMenu(false);
    scrollTo({ top: 0, behavior: "smooth" });
  };
  return (
    <>
      <aside className="skill-sidebar" aria-label="Điều hướng Master Clip">
        <div className="sidebar-top">
          <button className="sidebar-brand" onClick={() => go("home")} aria-label="Master Clip trang chủ">MC</button>
          <button
            className="sidebar-size-toggle"
            onClick={() => p.setSidebarCompact(!p.sidebarCompact)}
            aria-label={p.sidebarCompact ? "Mở rộng menu" : "Thu gọn menu"}
            title={p.sidebarCompact ? "Mở rộng menu" : "Thu gọn menu"}
          >
            {p.sidebarCompact ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>
        <nav>
          <button className={p.page === "home" ? "active" : ""} onClick={() => go("home")}><Sparkles size={20} /><span>Sảnh Skill</span></button>
          <button className={p.page === "skills" ? "active" : ""} onClick={p.openSkills}><ImageIcon size={20} /><span>Kho Skill</span></button>
          <button className={p.page === "mine" ? "active" : ""} onClick={() => go("mine")}><Clapperboard size={20} /><span>Skill của tôi</span></button>
          <button className={p.page === "combo" ? "active" : ""} onClick={() => go("combo")}><Gem size={20} /><span>Combo</span></button>
        </nav>
        <div className="sidebar-support">
          <button onClick={() => p.notify("Bạn đang có thông báo mới từ Master Clip.")}><Bell size={18} /><span>Thông báo</span></button>
          <button onClick={() => window.open(ZALO_CONTACT_URL, "_blank", "noopener,noreferrer")}><Headphones size={18} /><span>Hỗ trợ</span></button>
        </div>
        <button className="sidebar-account" onClick={p.auth}><User size={20} /><span>Tài khoản</span></button>
      </aside>
      <header className="studio-utilitybar">
        <button className="studio-home-button" onClick={() => go("home")}><span>⌂</span> Trang chủ</button>
        <form className="studio-search" onSubmit={(event) => { event.preventDefault(); p.searchSkills(search); }}>
          <Search size={21} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm kiếm Skill, chủ đề, từ khóa..." aria-label="Tìm kiếm Skill" />
          <button type="submit" aria-label="Tìm kiếm Skill"><SlidersHorizontal size={21} /></button>
        </form>
        <div className="studio-utility-actions">
          <button onClick={() => p.notify("Bạn đang có thông báo mới từ Master Clip.")}><Bell size={23} /><span>Thông báo</span></button>
          <button onClick={() => window.open(ZALO_CONTACT_URL, "_blank", "noopener,noreferrer")}><Headphones size={23} /><span>Hỗ trợ</span></button>
          <button onClick={() => window.open(ZALO_CONTACT_URL, "_blank", "noopener,noreferrer")}><MessageCircle size={23} /><span>Chat với nhà cung cấp</span></button>
          <button className="studio-upgrade" onClick={p.credit}><Gem size={24} /><span>Nâng cấp</span><ArrowRight size={19} /></button>
        </div>
      </header>
      <header className="topbar">
        <div className="shell nav-shell">
          <button className="brand" onClick={() => go("home")}>
            <span>MC</span>
            <b>Master Clip</b>
          </button>
          <nav className={p.menu ? "nav-links open" : "nav-links"}>
            <button className={p.page === "home" ? "active" : ""} onClick={() => go("home")}>Sảnh Skill</button>
            <button className={p.page === "skills" ? "active" : ""} onClick={p.openSkills}>Kho Skill</button>
            <button className={p.page === "mine" ? "active" : ""} onClick={() => go("mine")}>Skill của tôi</button>
            <button className={p.page === "combo" ? "active" : ""} onClick={() => go("combo")}>Combo</button>
          </nav>
          <div className="nav-actions">
            <button className="account-button" onClick={p.auth}><User size={17} /><span>{p.account ? "Tài khoản" : "Đăng nhập"}</span></button>
            <button className="mobile-menu" onClick={() => p.setMenu(!p.menu)}>{p.menu ? <X /> : <Menu />}</button>
          </div>
        </div>
      </header>
    </>
  );
}
function Home({ skillOnly, jump, select, openStudio }: { skillOnly: boolean; jump: (x?: Hall) => void; select: (s: Skill) => void; openStudio: () => void }) {
  const featuredSkills = [
    { skill: skills.find((x) => x.slug === "thuong-hieu-ca-nhan")!, image: "/home-feature-brand-workspace.png", label: "THƯƠNG HIỆU CÁ NHÂN" },
    { skill: skills.find((x) => x.slug === "poster-san-pham")!, image: "/home-feature-emerald-vogue.png", label: "POSTER SẢN PHẨM" },
    { skill: skills.find((x) => x.slug === "tao-video-viral")!, image: "/home-feature-red-dress.png", label: "VIDEO VIRAL" },
    { skill: skills.find((x) => x.slug === "multishot")!, image: "/home-feature-tokyo-full.png", label: "MULTISHOT SẢN PHẨM" },
  ];
  const demos = [
    { src: "/home-demo-1.mp4", title: "Túi xách — TVC ngắn" },
    { src: "/home-demo-2.mp4", title: "Visual bán hàng" },
    { src: "/home-demo-3.mp4", title: "Nội dung lifestyle" },
    { src: "/home-demo-4.mp4", title: "Video quảng cáo sản phẩm" },
  ];
  return (
    <main className="studio-home">
      <section className="studio-home-head">
        <div className="studio-heading-copy"><p className="studio-brand-title">MC MASTER CLIP</p><p className="eyebrow"><Sparkles size={15} /> MASTER CLIP STUDIO</p><h1>SẢNH SKILL</h1><p>Mỗi Skill là một <strong>câu lệnh soạn sẵn</strong> — dán vào ChatGPT hoặc Gemini - CÓ ẢNH VIRAL NGAY.</p></div>
        <aside className="studio-promo" aria-label="Khám phá Master Clip AI Skill World"><div><b>AI giúp bạn<br />sáng tạo dễ dàng hơn</b><small>MASTER CLIP<br />AI SKILL WORLD</small><button className="btn-primary" onClick={() => jump()}>Khám phá ngay <ArrowRight size={18} /></button></div><img src="/home-banner-tieu-nguyet.png" alt="Nhân vật Master Clip AI Skill World" /></aside>
      </section>
      <section className="studio-section"><div className="studio-section-heading"><div><p className="eyebrow">NỔI BẬT</p><h2>Cover Skill nổi bật</h2></div><button className="text-link" onClick={() => jump()}>Xem tất cả <ArrowRight size={17} /></button></div><div className="featured-cover-grid">{featuredSkills.map(({ skill, image, label }) => <button key={skill.slug} className="featured-cover" onClick={() => select(skill)}><i className="featured-cover-backdrop" aria-hidden="true" style={{ backgroundImage: `url(${image})` }} /><img src={image} alt={skill.title} /><span><b>{label}</b><small>{skill.title}</small></span></button>)}</div></section>
      <section className="studio-section"><div className="studio-section-heading"><div><p className="eyebrow">VIDEO DEMO</p><h2>Xem kết quả thực tế</h2></div><button className="text-link" onClick={() => jump("Edit Video")}>Sảnh Edit Video <ArrowRight size={17} /></button></div><div className="demo-video-grid">{demos.map((demo) => <article className="demo-video" key={demo.src}><video controls preload="metadata" playsInline><source src={demo.src} type="video/mp4" /></video><span><Play size={16} fill="currentColor" /><b>{demo.title}</b></span></article>)}</div></section>
    </main>
  );
}
function Skills(p: any) {
  return (
    <main className="page shell">
      <p className="eyebrow">MASTER CLIP / KHO SKILL</p>
      <h1 className="page-title">
        Tìm Skill phù hợp <em>với bạn.</em>
      </h1>
      <p className="page-lead">
        Khám phá bộ công cụ AI được phân loại để bạn bắt đầu đúng việc, nhanh hơn.
      </p>
      <div className="filter-row">
        <div className="searchbox">
          <Search size={18} />
          <input
            value={p.query}
            onChange={(e) => p.setQuery(e.target.value)}
            placeholder="Tìm kiếm Skill..."
          />
        </div>
      </div>
      <div className="hall-tabs">
        {(["Tất cả", ...halls.map((x) => x.name)] as Hall[]).map((x) => (
          <button key={x} className={p.hall === x ? "selected" : ""} onClick={() => p.setHall(x)}>
            {x}
          </button>
        ))}
      </div>
      <p className="results">{p.skills.length} Skill trong kho</p>
      <div className={`skill-grid large ${p.hall === "Sửa ảnh AI" ? "photo-cards" : ""}`}>
        {p.skills.map((s: Skill, i: number) => (
          <Card key={s.slug} skill={s} index={i} select={p.select} />
        ))}
      </div>
    </main>
  );
}
function Card({
  skill,
  index,
  select,
}: {
  skill: Skill;
  index: number;
  select: (s: Skill) => void;
}) {
  const colors = ["#f5dbe3", "#f0cbd7", "#ead8ef", "#f4e2d4", "#ebd4db"];
  const coverLines = (coverTextBySkill[skill.slug] || skill.title).split("\n");
  const isMasterCoverTemplate = lockedReferenceCovers.has(skill.slug);
  const isRefinedCover = !isMasterCoverTemplate;
  const isFullPosterCover = ["thuong-hieu-ca-nhan", "poster-san-pham", "xoa-nen-anh", "xoa-logo-anh", "chinh-sua-anh", "tang-chat-luong-4k", "multishot", "hoan-doi-nhan-vat", "dang-1-thoai-thumbnail", "dang-2-hieu-ung-cao-cap", "dang-3-huong-dan-toi-gian", "dang-4-infographic-trang", "cap-do-1-khung-don", "cap-do-2-postcard-2-nguoi", "multiclip-ghep-nhac-trend", "multiclip-1-video-highlight", "edit-video-zoom", "video-tu-dong-google-flow", "subagent-cham-soc", "subagent-nghien-cuu", "seo-video-youtube", "dang-bai-tu-dong-da-kenh", "tao-video-viral", "reel-facebook-viral"].includes(skill.slug);
  return (
    <article className={`skill-card ${skill.hall === "Sửa ảnh AI" ? "photo-skill-card" : ""}`}>
      <div
        className={`skill-cover ${skill.hall === "Sửa ảnh AI" ? "photo-skill-cover" : ""} ${isRefinedCover ? "cover-system" : ""} ${isFullPosterCover ? "brand-poster-cover" : ""}`}
        style={{ background: `linear-gradient(135deg,${colors[index % 5]},#fffaf6)` }}
      >
        <img src={coverBySkill[skill.slug] || coverByHall[skill.hall]} alt="" loading="lazy" />
        {!isFullPosterCover && <>
          <div className="skill-cover-shade" />
          <span>{skill.hall}</span>
          <strong className={`cover-title ${isMasterCoverTemplate ? "cover-title--master-template" : ""}`}>
            {coverLines.map((line, lineIndex) => <span key={`${skill.slug}-${lineIndex}`}>{line}</span>)}
          </strong>
        </>}
      </div>
      <div className="skill-content">
        <div className="skill-meta">
          <small>{skill.tag}</small>
          {skill.status && <small className="status">{skill.status}</small>}
        </div>
        <h3>{skill.title}</h3>
        <p>{skill.description}</p>
        <div className="card-bottom">
          <b>{formatVnd(skillPrice(skill))}</b>
          <span>Truy cập lâu dài</span>
        </div>
        <button onClick={() => select(skill)}>
          Xem chi tiết <ArrowRight size={16} />
        </button>
      </div>
    </article>
  );
}
function Detail({ skill, skillOnly, owned, content, loading, back, use }: { skill: Skill; skillOnly: boolean; owned: boolean; content: SkillContent | null; loading: boolean; back: () => void; use: () => void }) {
  const displayPrice = formatVnd(skillPrice(skill));
  const isReady = owned && content?.content_state === "READY";
  // A source-aligned layout is enabled only after that Skill's purchased
  // lesson has been checked and imported.  It deliberately shares the same
  // Master Clip visual template; the lesson text remains specific to its slug.
  const isReferenceLayout = ["thuong-hieu-ca-nhan", "poster-san-pham", "xoa-nen-anh", "xoa-logo-anh", "chinh-sua-anh", "tang-chat-luong-4k", "multishot", "hoan-doi-nhan-vat", "dang-1-thoai-thumbnail", "dang-2-hieu-ung-cao-cap", "dang-3-huong-dan-toi-gian", "dang-4-infographic-trang", "cap-do-1-khung-don", "cap-do-2-postcard-2-nguoi", "multiclip-ghep-nhac-trend", "multiclip-1-video-highlight", "edit-video-zoom", "video-tu-dong-google-flow", "subagent-cham-soc", "subagent-nghien-cuu", "seo-video-youtube", "dang-bai-tu-dong-da-kenh", "tao-video-viral", "reel-facebook-viral"].includes(skill.slug);
  const isFullPosterCover = ["thuong-hieu-ca-nhan", "poster-san-pham", "xoa-nen-anh", "xoa-logo-anh", "chinh-sua-anh", "tang-chat-luong-4k", "multishot", "hoan-doi-nhan-vat", "dang-1-thoai-thumbnail", "dang-2-hieu-ung-cao-cap", "dang-3-huong-dan-toi-gian", "dang-4-infographic-trang", "cap-do-1-khung-don", "cap-do-2-postcard-2-nguoi", "multiclip-ghep-nhac-trend", "multiclip-1-video-highlight", "edit-video-zoom", "video-tu-dong-google-flow", "subagent-cham-soc", "subagent-nghien-cuu", "seo-video-youtube", "dang-bai-tu-dong-da-kenh", "tao-video-viral", "reel-facebook-viral"].includes(skill.slug);
  const coverLines = (coverTextBySkill[skill.slug] || skill.title).split("\n");
  const [copied, setCopied] = useState(false);
  const importedSections = useMemo(() => {
    try {
      const value = JSON.parse(content?.owned_sections_json || "[]");
      return Array.isArray(value) ? value.filter((section) => section?.title && section?.body) : [];
    } catch {
      return [];
    }
  }, [content?.owned_sections_json]);
  const steps = useMemo(
    () => (content?.steps_text || "").split(/(?=Bước\s*\d+\s*[—–-])/i).map((step) => step.trim()).filter(Boolean),
    [content?.steps_text],
  );
  const practiceSection = useMemo(
    () => importedSections.find((section: { number?: string }) => section?.number === "05"),
    [importedSections],
  );
  const practice = useMemo(() => {
    const lines = (practiceSection?.body || "").split(/\n+/).map((line: string) => line.trim()).filter(Boolean);
    const resultIndex = lines.findIndex((line: string) => /^Xong sẽ có:/i.test(line));
    return {
      intro: lines[0] || "",
      steps: lines.slice(1, resultIndex === -1 ? undefined : resultIndex).filter((line: string) => /^\d+\.\s/.test(line)),
      result: resultIndex === -1 ? "" : lines[resultIndex].replace(/^Xong sẽ có:\s*/i, ""),
    };
  }, [practiceSection]);
  const lessonMinutes = skill.slug === "poster-san-pham" ? "10 phút" : ["multishot", "hoan-doi-nhan-vat", "subagent-nghien-cuu"].includes(skill.slug) ? "5–10 phút" : skill.slug === "video-tu-dong-google-flow" ? "5–10 phút" : skill.slug === "dang-1-thoai-thumbnail" ? "5–10 phút" : ["dang-2-hieu-ung-cao-cap", "dang-4-infographic-trang", "cap-do-1-khung-don", "subagent-cham-soc"].includes(skill.slug) ? "10–20 phút" : ["seo-video-youtube", "dang-bai-tu-dong-da-kenh"].includes(skill.slug) ? "10–15 phút" : ["tao-video-viral", "reel-facebook-viral"].includes(skill.slug) ? "20–30 phút" : skill.slug === "cap-do-2-postcard-2-nguoi" ? "15–25 phút" : skill.slug === "edit-video-zoom" ? "20–40 phút" : ["multiclip-ghep-nhac-trend", "multiclip-1-video-highlight"].includes(skill.slug) ? "10–15 phút" : skill.slug === "dang-3-huong-dan-toi-gian" ? "8–12 phút" : ["xoa-nen-anh", "xoa-logo-anh", "chinh-sua-anh", "tang-chat-luong-4k"].includes(skill.slug) ? "2 phút" : "3 phút";
  const copyPrompt = async () => {
    if (!content?.prompt_text) return;
    try {
      await navigator.clipboard.writeText(content.prompt_text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard access is browser-controlled; the prompt remains visible for manual copy.
    }
  };
  return (
    <main className={`page shell ${isReferenceLayout ? "reference-skill-page" : ""}`}>
      <button className="back" onClick={back}>
        <ChevronLeft size={18} /> Quay về Kho Skill
      </button>
      {isReferenceLayout ? (
        <section className="reference-skill-top">
          <div className="reference-skill-main">
            <p className="reference-crumb">Sảnh Skill / Sảnh I / {skill.title}</p>
            <h1 className="page-title">{skill.title}</h1>
            <p className="page-lead">{skill.description}</p>
            <div className={`detail-cover reference-cover ${skill.hall === "Sửa ảnh AI" ? "photo-detail-cover" : ""} ${isReferenceLayout ? "master-template-cover" : ""} ${isFullPosterCover ? "brand-poster-detail" : ""}`}>
              <img src={coverBySkill[skill.slug] || coverByHall[skill.hall]} alt={`Ảnh demo ${skill.title}`} />
              {!isFullPosterCover && <>
                <div className="detail-cover-shade" />
                <span>{skill.hall}</span>
                <strong className="cover-headline">
                  {coverLines.map((line, lineIndex) => <span key={`${skill.slug}-detail-${lineIndex}`}>{line}</span>)}
                </strong>
              </>}
            </div>
            <section className="reference-benefits">
              <h2>Skill này gồm những gì?</h2>
              {[
                ["🤖", "Câu lệnh làm việc cho AI", "Dán vào ChatGPT hoặc Gemini kèm ảnh của bạn — ra kết quả ngay."],
                ["📱", "Làm được trên điện thoại", "Không cần máy tính mạnh, không cần cài phần mềm."],
                ["💡", "Cách xử lý lỗi hay gặp", "Có lưu ý thực tế để kiểm kết quả và sửa riêng ảnh bị lệch."],
                ["🖥️", "Tài nguyên đi kèm", content?.resource_url ? "Có đường dẫn công cụ liên quan trong nội dung Skill." : "Chưa có tài nguyên bổ sung được import."],
              ].map(([icon, title, text]) => (
                <article key={title}>
                  <span>{icon}</span><div><b>{title}</b><p>{text}</p></div>
                </article>
              ))}
            </section>
          </div>
          <aside className="reference-quick-start">
            <div className="reference-owned">{owned ? "✓ Bạn đã mở Skill này" : "Skill chưa được mở khóa"}</div>
            <h3>{owned ? "Dùng ngay bằng AI của bạn" : "Mua để mở nội dung đầy đủ"}</h3>
            {owned && isReady ? (
              <>
                <div className="quick-step"><b><i>1</i> Sao chép câu lệnh</b><pre>{content?.prompt_text}</pre><button onClick={copyPrompt}>{copied ? "Đã chép" : "Chép"}</button></div>
                <div className="quick-step"><b><i>2</i> Dán vào AI của bạn rồi Enter</b><p>ChatGPT hoặc Gemini sẽ đọc ảnh và thực hiện theo câu lệnh.</p></div>
                <div className="quick-step"><b><i>3</i> Kiểm từng ảnh</b><p>Dùng các lưu ý trong hướng dẫn để sửa riêng ảnh bị lệch.</p></div>
              </>
            ) : <button className="btn-primary" onClick={use}>Mua Skill · {displayPrice} <ArrowRight size={18} /></button>}
            <div className="quick-foot">Nội dung được lưu trong Skill của tôi và mở lại bất cứ lúc nào.</div>
          </aside>
        </section>
      ) : <>
        <section className="detail-hero sales-hero">
          <div className={`detail-cover ${skill.hall === "Sửa ảnh AI" ? "photo-detail-cover" : ""}`}>
            <img src={coverBySkill[skill.slug] || coverByHall[skill.hall]} alt={`Ảnh demo ${skill.title}`} />
            <div className="detail-cover-shade" />
            <span>{skill.hall}</span>
            <strong>{coverTextBySkill[skill.slug] || skill.title}</strong>
          </div>
          <div>
            <p className="eyebrow">{skill.hall}</p><h1 className="page-title">{skill.title}</h1><p className="page-lead">{skill.description}</p>
            <div className="detail-tags"><span>{skill.tag}</span><span>{skill.status || "Sẵn sàng"}</span></div>
            <div className="detail-price"><b>{displayPrice}</b><span>Quyền sở hữu Skill lâu dài</span></div>
            <button className="btn-primary" onClick={use}>{!skillOnly && skill.legacy ? "Mở AI Video Studio" : owned ? "Mở Skill" : `Mua Skill · ${displayPrice}`}<ArrowRight size={18} /></button>
          </div>
        </section>
        <section className="benefits-section">
          <p className="eyebrow">KẾT QUẢ THAY VÌ LÝ THUYẾT</p><h2>Skill này làm được gì?</h2>
          <div className="benefit-grid">{["Tạo kết quả đồng nhất với thương hiệu", "Rút ngắn thao tác thủ công lặp lại", "Có quy trình rõ ràng để bắt đầu", "Áp dụng theo nội dung gốc sau khi sở hữu Skill"].map((item, index) => <article key={item}><span>0{index + 1}</span><b>{item}</b></article>)}</div>
        </section>
      </>}
      {!isReferenceLayout && <>
      <section className="detail-demo">
        <div className="demo-input">
          <small>INPUT</small>
          <span>{content?.input_notes || (owned && loading ? "Đang tải nội dung Skill đã sở hữu…" : "Ảnh / video / ý tưởng của bạn")}</span>
        </div>
        <ArrowRight size={25} />
        <div className="demo-output">
          <small>OUTPUT</small>
          <span>{content?.output_notes || (owned && loading ? "Đang tải nội dung Skill đã sở hữu…" : "Kết quả sẵn sàng để bán hàng")}</span>
        </div>
      </section>
      <section className="tutorial-section">
        <div className="tutorial-video tutorial-unavailable">
          <Play size={22} />
          <div>
            <b>Video hướng dẫn</b>
            <p>Chưa có video hướng dẫn được import từ Skill nguồn.</p>
          </div>
        </div>
        <div>
          <p className="eyebrow">NỘI DUNG SKILL</p>
          {owned && loading ? (
            <>
              <h2>Đang tải nội dung Skill của bạn</h2>
              <p className="page-lead">Đang kiểm tra quyền sở hữu và tải tài nguyên đã import.</p>
            </>
          ) : isReady ? (
            <>
              <h2>Nội dung Skill của bạn</h2>
              <p className="page-lead">{content?.preview_text}</p>
            </>
          ) : owned ? (
            <>
              <h2>CONTENT_MISSING</h2>
              <p className="page-lead">Tài nguyên gốc của Skill này chưa được import vào Master Clip. Không có workflow, prompt hoặc video nào được tự tạo thay thế.</p>
            </>
          ) : (
            <>
              <h2>Mua để mở nội dung Skill</h2>
              <p className="page-lead">{content?.preview_text || "Sau khi thanh toán, quyền sở hữu được lưu vào Skill của tôi. Nội dung chỉ hiển thị khi có tài nguyên thật đã được import."}</p>
            </>
          )}
        </div>
      </section>
      </>}
      {isReady && isReferenceLayout && (
        <section className="reference-owned-content" id="owned-skill-content" aria-label="Nội dung Skill của bạn">
          <div className="reference-intro">{content?.workflow_text}</div>
          <div className="reference-copy-callout">
            <b>Dán vào ChatGPT hoặc Gemini kèm ảnh của bạn. Không cài gì, làm được cả trên điện thoại.</b>
            <button onClick={copyPrompt}>{copied ? "ĐÃ SAO CHÉP" : "CHÉP CÂU LỆNH"}</button>
            <small>Prompt được giữ nguyên từ nội dung Skill đã import.</small>
          </div>
          <h2>{practiceSection?.title?.replace(/^Làm thử ngay$/i, "Làm theo " + steps.length + " bước") || `Làm theo ${steps.length} bước`}</h2>
          <p className="reference-time">◷ Bộ đầu tiên xong trong {lessonMinutes}</p>
          <div className="reference-steps">
            {steps.map((step, index) => {
              const [heading, ...body] = step.split("\n");
              return <article key={step}><span>{index + 1}</span><div><h3>{heading.replace(/^Bước\s*\d+\s*[—–-]?\s*/i, "")}</h3><p>{body.join("\n")}</p></div></article>;
            })}
          </div>
          {practiceSection && <article className="reference-practice">
            <p><b>{practiceSection.title}</b> {practice.intro}</p>
            {practice.steps.length > 0 && <ol>{practice.steps.map((step: string) => <li key={step}>{step.replace(/^\d+\.\s*/, "")}</li>)}</ol>}
            {practice.result && <div><strong>Xong sẽ có:</strong> {practice.result}</div>}
          </article>}
          <div className="reference-extra">
            <p>{content?.notes_text}</p>
            {content?.resource_url && <a className="resource-link" href={content.resource_url} target="_blank" rel="noreferrer">Mở công cụ liên quan <ArrowRight size={15} /></a>}
          </div>
        </section>
      )}
      {isReady && !isReferenceLayout && (
        <section className="owned-content" id="owned-skill-content" aria-label="Nội dung Skill của bạn">
          <p className="eyebrow">NỘI DUNG SKILL CỦA BẠN</p>
          <h2>Hướng dẫn, Prompt và quy trình thực hiện</h2>
          <div className="owned-grid">
            <article>
              <small>01 — SKILL NÀY GIÚP BẠN LÀM GÌ</small>
              <p>{content?.workflow_text}</p>
            </article>
            <article>
              <small>02 — CHUẨN BỊ TRƯỚC KHI BẮT ĐẦU</small>
              <p>{content?.input_notes}</p>
            </article>
            <article className="prompt-card">
              <small>03 — PROMPT 01 / CÂU LỆNH</small>
              <pre>{content?.prompt_text}</pre>
              <button onClick={copyPrompt}>{copied ? "ĐÃ SAO CHÉP" : "SAO CHÉP PROMPT"}</button>
            </article>
            <article className="steps-card">
              <small>04 — CÁCH SỬ DỤNG TỪNG BƯỚC</small>
              {(content?.steps_text || "").split("\n\n").map((step) => <p key={step}>{step}</p>)}
            </article>
            <article className="input-output-card">
              <small>05 — INPUT → OUTPUT</small>
              <div><b>Input</b><span>{content?.input_notes}</span></div>
              <div><b>Output</b><span>{content?.output_notes}</span></div>
            </article>
            <article>
              <small>06 — VIDEO HƯỚNG DẪN</small>
              <p>Thiếu: Skill nguồn chưa có video hướng dẫn được import. Master Clip không thay thế bằng video khác.</p>
            </article>
            <article>
              <small>07 — TÀI NGUYÊN ĐI KÈM</small>
              {content?.resource_url ? <a className="resource-link" href={content.resource_url} target="_blank" rel="noreferrer">Mở công cụ nền tảng ComfyUI <ArrowRight size={15} /></a> : <p>Thiếu: chưa có tài nguyên/link bổ sung được import.</p>}
            </article>
            <article>
              <small>08 — MẸO ĐỂ RA KẾT QUẢ ĐẸP</small>
              <p>{content?.notes_text}</p>
            </article>
          </div>
          {importedSections.length > 0 && (
            <div className="owned-source-sections" aria-label="Nội dung gốc đã import">
              {importedSections.map((section: { number?: string; title: string; body: string }) => (
                <article key={`${section.number}-${section.title}`}>
                  <small>{section.number ? `${section.number} — ` : ""}{section.title}</small>
                  <p>{section.body}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
      <section className="ownership-section">
        <div>
          <p className="eyebrow">SAU KHI MUA</p>
          <h2>Bạn nhận được gì?</h2>
          <p>Quyền sở hữu Skill được lưu lâu dài. Tài nguyên hướng dẫn chỉ được hiển thị khi có nội dung đã import, không dùng nội dung giả.</p>
        </div>
        <button className="btn-primary" onClick={use}>
          {owned ? "Mở Skill" : `Mua Skill · ${displayPrice}`} <ArrowRight size={18} />
        </button>
      </section>
    </main>
  );
}
function VideoStudio({
  skill,
  token,
  account,
  back,
  askAuth,
  setNotice,
  setAccount,
}: {
  skill: Skill;
  token: string;
  account: { email: string; credits: number } | null;
  back: () => void;
  askAuth: () => void;
  setNotice: (notice: string) => void;
  setAccount: React.Dispatch<React.SetStateAction<{ email: string; credits: number } | null>>;
}) {
  const clipsInput = useRef<HTMLInputElement>(null);
  const musicInput = useRef<HTMLInputElement>(null);
  const [clips, setClips] = useState<File[]>([]);
  const [music, setMusic] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [resultUrl, setResultUrl] = useState("");
  const isMulticlip = skill.slug === "multiclip-ghep-nhac-trend";
  async function render() {
    if (!token) {
      askAuth();
      setNotice("Đăng nhập để dùng credit dựng video.");
      return;
    }
    if (!clips.length || !music) {
      setNotice("Hãy chọn clip và một file nhạc trước.");
      return;
    }
    setRunning(true);
    setResultUrl("");
    try {
      const form = new FormData();
      clips.forEach((clip) => form.append("clips", clip));
      form.append("music", music);
      const response = await fetch(`${API}/render`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = (await response.json()) as { url?: string; credits?: number; detail?: string };
      if (!response.ok || !data.url) throw new Error(data.detail || "Không thể dựng video.");
      setResultUrl(data.url);
      setAccount((old) => (old ? { ...old, credits: data.credits ?? old.credits } : old));
      setNotice("Đã dựng xong video ghép theo nhạc.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể kết nối bộ dựng video.");
    } finally {
      setRunning(false);
    }
  }
  return (
    <main className="page shell">
      <button className="back" onClick={back}>
        <ChevronLeft size={18} /> Quay về Skill
      </button>
      <p className="eyebrow">MASTER CLIP / CÔNG CỤ VIDEO</p>
      <h1 className="page-title">{skill.title}</h1>
      <p className="page-lead">{skill.description}</p>
      {isMulticlip ? (
        <section className="studio-panel">
          <div className="studio-heading">
            <Music2 size={24} />
            <div>
              <h2>Ghép clip theo nhịp nhạc</h2>
              <p>
                Chọn nhiều clip và một bài nhạc bạn có quyền sử dụng. Video được xuất theo tỷ lệ dọc
                9:16.
              </p>
            </div>
            {account && <span>{account.credits} credit</span>}
          </div>
          <div className="studio-inputs">
            <button onClick={() => clipsInput.current?.click()}>
              <Upload size={21} />
              <b>Chọn clip</b>
              <small>
                {clips.length ? `${clips.length} clip đã chọn` : "Chọn nhiều file video"}
              </small>
            </button>
            <button onClick={() => musicInput.current?.click()}>
              <Music2 size={21} />
              <b>Chọn nhạc</b>
              <small>{music?.name || "MP3, WAV, M4A…"}</small>
            </button>
          </div>
          <input
            ref={clipsInput}
            className="hidden-input"
            type="file"
            multiple
            accept="video/*"
            onChange={(event) => setClips(Array.from(event.target.files || []))}
          />
          <input
            ref={musicInput}
            className="hidden-input"
            type="file"
            accept="audio/*"
            onChange={(event) => setMusic(event.target.files?.[0] || null)}
          />
          <button className="btn-primary" disabled={running} onClick={render}>
            {running ? "Đang dựng video…" : "Ghép theo nhạc"}
            <ArrowRight size={18} />
          </button>
          {resultUrl && (
            <a className="result-link" href={resultUrl} target="_blank" rel="noreferrer">
              Mở video đã dựng <ArrowRight size={16} />
            </a>
          )}
        </section>
      ) : (
        <section className="studio-panel">
          <div className="studio-heading">
            <Clapperboard size={24} />
            <div>
              <h2>Không gian dựng Master Clip</h2>
              <p>Đây là điểm truy cập chính thức của workflow này trong Sảnh Edit Video.</p>
            </div>
          </div>
          <div className="workflow-note">
            <b>Workflow đã được giữ lại</b>
            <p>
              Phiên bản UI Skill đã thay thế trang chủ cũ. Tác vụ này sẽ được nối vào engine dựng
              tương ứng ở giai đoạn tích hợp Skill, không ảnh hưởng đến bộ dựng Nhiều clip + Nhạc
              đang hoạt động.
            </p>
          </div>
        </section>
      )}
    </main>
  );
}
function MySkills({ skills, browse, select }: { skills: Skill[]; browse: () => void; select: (skill: Skill) => void }) {
  if (skills.length) {
    return (
      <main className="page shell">
        <p className="eyebrow">THƯ VIỆN CÁ NHÂN</p>
        <h1 className="page-title">Skill của tôi</h1>
        <p className="page-lead">Những Skill đã mở khóa được lưu lâu dài trong tài khoản của bạn.</p>
        <div className="skill-grid large">{skills.map((skill, index) => <Card key={skill.slug} skill={skill} index={index} select={select} />)}</div>
      </main>
    );
  }
  return (
    <main className="page shell empty-page">
      <Gem size={42} />
      <p className="eyebrow">THƯ VIỆN CÁ NHÂN</p>
      <h1 className="page-title">Skill của tôi</h1>
      <p className="page-lead">
        Đăng nhập để xem những Skill bạn đã sở hữu.
      </p>
      <button className="btn-primary" onClick={browse}>
        Khám phá Kho Skill <ArrowRight size={18} />
      </button>
    </main>
  );
}
function Combo({ credit, skillOnly }: { credit: () => void; skillOnly: boolean }) {
  return (
    <main className="page shell">
      <p className="eyebrow">COMBO MASTER CLIP</p>
      <h1 className="page-title">
        Làm nhiều hơn với <em>combo.</em>
      </h1>
      <p className="page-lead">
        Không gian để chuẩn bị các gói Skill theo mục tiêu; giá và quyền sở hữu sẽ kết nối cùng
        PostgreSQL ở giai đoạn tiếp theo.
      </p>
      <div className="combo-card">
        <div>
          <span>COMING SOON</span>
          <h2>Combo Content Starter</h2>
          <p>Kết hợp Skill ảnh, video và marketing cho một quy trình nội dung hoàn chỉnh.</p>
        </div>
        {skillOnly ? <span className="combo-status">Sắp ra mắt</span> : <button className="btn-primary" onClick={credit}>Nạp credit <ArrowRight size={18} /></button>}
      </div>
    </main>
  );
}
function Section({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <div className="section-title">
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      <p>{text}</p>
    </div>
  );
}
function Footer() {
  return (
    <footer>
      <div className="shell footer-row">
        <div className="brand">
          <span>MC</span>
          <b>Master Clip</b>
        </div>
        <p>AI Skill World cho người sáng tạo nội dung.</p>
        <small>© 2026 Master Clip</small>
      </div>
    </footer>
  );
}
function Auth(p: any) {
  return (
    <div className="modal-wrap">
      <div className="modal">
        <button className="modal-close" onClick={p.close}>
          <X />
        </button>
        <p className="eyebrow">MASTER CLIP</p>
        <h2>Chào mừng bạn trở lại</h2>
        <p>Đăng nhập để lưu và mở Skill của bạn.</p>
        <input value={p.email} onChange={(e) => p.setEmail(e.target.value)} placeholder="Email" />
        <input
          type="password"
          value={p.password}
          onChange={(e) => p.setPassword(e.target.value)}
          placeholder="Mật khẩu"
        />
        <div className="modal-actions">
          <button className="btn-quiet" onClick={() => p.login("login")}>
            Đăng nhập
          </button>
          <button className="btn-primary" onClick={() => p.login("register")}>
            Tạo tài khoản
          </button>
          {p.account && <button className="btn-quiet" onClick={p.logout}>Đăng xuất</button>}
        </div>
      </div>
    </div>
  );
}
function Payment(p: any) {
  const plans = [
    { key: "starter", name: "Starter", price: "49.000đ", credits: 10 },
    { key: "pro", name: "Pro", price: "129.000đ", credits: 35 },
    { key: "studio", name: "Studio", price: "349.000đ", credits: 120 },
  ] as const;
  const [paid, setPaid] = useState<any>(null);
  useEffect(() => {
    if (!p.order?.code || !p.token || paid) return;
    let cancelled = false;
    const check = async () => {
      try {
        const response = await fetch(`${API}/orders/${p.order.code}`, {
          headers: { Authorization: `Bearer ${p.token}` },
        });
        if (!response.ok) return;
        const data = await response.json();
        if (data.status === "paid" && !cancelled) {
          setPaid(data);
          void p.onPaid();
        }
      } catch {
        // Payment polling is best-effort. The order remains available after refresh.
      }
    };
    void check();
    const interval = window.setInterval(check, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [p.order?.code, p.token, paid]);
  const isSkill = p.order?.kind === "skill" || paid?.order_type === "SKILL_PURCHASE";
  return (
    <div className="modal-wrap">
      <div className="modal payment">
        <button className="modal-close" onClick={p.close}>
          <X />
        </button>
        <p className="eyebrow">THANH TOÁN VIETQR</p>
        <h2>{isSkill || p.skillOnly ? "Thanh toán Skill" : "Nạp Credit Master Clip"}</h2>
        {!p.order ? (
          p.skillOnly ? <p className="page-lead">Hãy mở trang chi tiết của một Skill để tạo đơn thanh toán.</p> : <div className="plans">
            {plans.map((x) => (
              <button key={x.key} onClick={() => p.checkout(x.key)}>
                <b>{x.name}</b>
                <strong>{x.price}</strong>
                <small>{x.credits} credit</small>
              </button>
            ))}
          </div>
        ) : paid ? (
          <div className="payment-ready">
            <div>
              <p className="eyebrow">✓ XÁC NHẬN TỪ SEPAY</p>
              <h3>{isSkill ? "Thanh toán thành công" : "Nạp credit thành công"}</h3>
              <p>
                {isSkill ? `Skill “${p.order.skill.title}” đã được mở khóa.` : `+${paid.credits} Credit đã được cộng vào số dư của bạn.`}
              </p>
              {!isSkill && <p><b>Số dư hiện tại: {p.account?.credits ?? "…"} Credit</b></p>}
              <div className="modal-actions">
                <button className="btn-quiet" onClick={isSkill ? p.openMine : p.useNow}>
                  {isSkill ? "Skill của tôi" : "Dùng công cụ ngay"}
                </button>
                <button className="btn-primary" onClick={p.useNow}>
                  {isSkill ? "Sử dụng ngay" : "Đóng"}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="payment-ready">
            <div>
              <p>
                {isSkill ? <>Mua Skill – <b>{p.order.skill.price.toLocaleString("vi-VN")}đ</b>. Chuyển khoản đúng số tiền để mở khóa <b>{p.order.skill.title}</b>.</> : <>Nạp Credit. Chuyển khoản đúng số tiền để nhận <b>{p.order.plan.credits} credit</b>.</>}
              </p>
              <dl>
                <dt>Ngân hàng</dt>
                <dd>{p.order.bank.bank}</dd>
                <dt>Số tài khoản</dt>
                <dd>{p.order.bank.account}</dd>
                <dt>Chủ tài khoản</dt>
                <dd>{p.order.bank.name}</dd>
                <dt>Nội dung</dt>
                <dd className="payment-code">{p.order.code}</dd>
                <dt>Số tiền</dt>
                <dd>{(isSkill ? p.order.skill.price : p.order.plan.amount).toLocaleString("vi-VN")}đ</dd>
              </dl>
              <small>{isSkill ? "SePay sẽ tự xác nhận và mở khóa Skill. Giao dịch này không cộng credit." : "SePay sẽ tự xác nhận và cộng credit. Giao dịch này không mở khóa Skill."}</small>
            </div>
            <img src={p.order.qr_url} alt="QR thanh toán VietQR" />
          </div>
        )}
      </div>
    </div>
  );
}
