import { createFileRoute } from "@tanstack/react-router";
import {
  AudioLines,
  Brush,
  Captions,
  Check,
  ChevronDown,
  CircleDollarSign,
  Clapperboard,
  Clock3,
  CloudUpload,
  Download,
  FileAudio,
  Film,
  FolderOpen,
  Gauge,
  Headphones,
  Home,
  ImageIcon,
  ImagePlus,
  Link2,
  Menu,
  MessageSquareText,
  Music2,
  Pause,
  Play,
  Plus,
  Scissors,
  Sparkles,
  Star,
  Upload,
  User,
  Video,
  WandSparkles,
  X,
  type LucideIcon,
} from "lucide-react";
import { useRef, useState } from "react";

import sampleGolfMan from "@/assets/sample-golf-man.mp4.asset.json";
import sampleGolfSwing from "@/assets/sample-golf-swing.mp4.asset.json";
import sampleLake from "@/assets/sample-lake.mp4.asset.json";
import sampleTravel from "@/assets/sample-travel.mp4.asset.json";
import presenter from "@/assets/sample-presenter.jpg";
import runner from "@/assets/sample-runner.jpg";
import stretch from "@/assets/sample-stretch.jpg";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Render supplies VITE_API_URL during production builds. The cloud fallback keeps
// the staging app functional if a Docker build environment omits build-time vars.
const DEFAULT_API_BASE_URL =
  typeof window !== "undefined" && window.location.hostname.endsWith(".onrender.com")
    ? "https://video-magic-api-fp7a.onrender.com"
    : "http://127.0.0.1:8787";
const API_BASE_URL = (import.meta.env.VITE_API_URL || DEFAULT_API_BASE_URL).replace(/\/$/, "");

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Master Clip — Video dài thành nhiều Short" },
      { name: "description", content: "Biến video thô thành nội dung viral tự động bằng AI." },
      { property: "og:title", content: "Master Clip — Video dài thành nhiều Short" },
      { property: "og:description", content: "Biến video thô thành nội dung viral tự động bằng AI." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Index,
});

type AiTool = { icon: LucideIcon; label: string; sublabel?: string };

const tools: AiTool[] = [
  { icon: Film, label: "Sửa Đổi Video AI" },
  { icon: Music2, label: "Đồng Bộ Nhạc", sublabel: "Thông minh" },
  { icon: AudioLines, label: "Lọc Mức Điểm", sublabel: "Âm" },
  { icon: Sparkles, label: "AI Chấm Điểm", sublabel: "Cảnh Quay" },
  { icon: Clapperboard, label: "Video Dài →", sublabel: "Short" },
  { icon: Download, label: "Nhập Từ", sublabel: "YouTube/Drive" },
  { icon: WandSparkles, label: "Hook Mở Đầu" },
  { icon: Captions, label: "Caption Đồng", sublabel: "Bộ" },
  { icon: Scissors, label: "Cắt Khoảng", sublabel: "Lặng Tự Động" },
  { icon: ImageIcon, label: "Slide Đồ Họa AI" },
  { icon: FileAudio, label: "Đồng Bộ Nhịp", sublabel: "Nhạc" },
  { icon: Gauge, label: "Lọc Mức Ồn", sublabel: "Âm" },
];

const studioProducts = [
  { icon: Video, title: "Edit video AI", description: "Cắt short, talking-head, ghép clip theo nhạc và xuất video dọc.", mode: "Nhiều clip + Nhạc", badge: "Đang hoạt động" },
  { icon: Brush, title: "Chỉnh ảnh", description: "Làm sáng, chỉnh màu, làm nét và chuẩn bị ảnh sản phẩm để đăng bán.", mode: "Chỉnh ảnh", badge: "Sắp kết nối AI" },
  { icon: ImagePlus, title: "Tạo ảnh AI", description: "Tạo ảnh quảng cáo, thumbnail và hình sản phẩm theo prompt thương hiệu.", mode: "Tạo ảnh AI", badge: "Cần API AI" },
];

const samples = [
  { video: "/samples/handbag-sample-1.mp4", name: "Video mẫu 1" },
  { video: "/samples/handbag-sample-2.mp4", name: "Video mẫu 2" },
  { video: sampleGolfSwing.url, name: "Video mẫu 3" },
  { video: sampleGolfMan.url, name: "Video mẫu 4" },
  { video: sampleTravel.url, name: "Video mẫu 5" },
  { video: sampleLake.url, name: "Video mẫu 6" },
];

const projects = [
  { title: "cải phân tích xương — bản đề xuất 8 cảnh", meta: "Bản dự án · 2:44", image: null, active: true },
  { title: "cải phân tích xương — bản đề xuất 8 cảnh", meta: "Bản dự án · 2:15", image: null, active: true },
  { title: "video-nhiều-clip-nhạc", meta: "30.09.2026 · 1:39", image: runner },
  { title: "2026-09-30_ai_sub-agent-edit-video", meta: "30.09.2026 · 0:48", image: presenter },
  { title: "video-nhiều-clip-nhạc", meta: "28.09.2026 · 1:49", image: stretch },
];

function Index() {
  const inputRef = useRef<HTMLInputElement>(null);
  const multiclipInputRef = useRef<HTMLInputElement>(null);
  const musicInputRef = useRef<HTMLInputElement>(null);
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([]);
  const [mode, setMode] = useState("Video dài → Short");
  const [tab, setTab] = useState("Tất cả các dự án");
  const [url, setUrl] = useState("");
  const [fileName, setFileName] = useState("");
  const [selectedSample, setSelectedSample] = useState<number | null>(null);
  const [playingSample, setPlayingSample] = useState<number | null>(null);
  const [favorite, setFavorite] = useState<number[]>([3]);
  const [notice, setNotice] = useState("");
  const [multiclips, setMulticlips] = useState<File[]>([]);
  const [music, setMusic] = useState<File | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const [renderUrl, setRenderUrl] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [token, setToken] = useState("");
  const [account, setAccount] = useState<{ email: string; credits: number } | null>(null);
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [order, setOrder] = useState<{ code: string; qr_url: string; plan: { name: string; amount: number; credits: number }; bank: { bank: string; account: string; name: string } } | null>(null);

  function handleUrl() {
    setNotice(url.trim() ? "Đã nhận liên kết — sẵn sàng tạo dự án." : "Hãy dán liên kết video trước.");
  }

  function toggleSample(index: number) {
    const video = videoRefs.current[index];
    if (!video) return;
    if (playingSample === index) {
      video.pause();
      setPlayingSample(null);
      return;
    }
    videoRefs.current.forEach((other, i) => { if (i !== index && other) other.pause(); });
    video.play().catch(() => undefined);
    setSelectedSample(index);
    setPlayingSample(index);
  }

  function chooseFile(file?: File) {
    if (!file) return;
    setFileName(file.name);
    setNotice(`Đã thêm ${file.name}`);
  }

  async function renderMulticlip() {
    if (!token) {
      setAuthOpen(true);
      setNotice("Đăng nhập để dùng credit dựng video.");
      return;
    }
    if (!multiclips.length || !music) {
      setNotice("Hãy chọn các clip và một file nhạc trước.");
      return;
    }
    setIsRendering(true);
    setRenderUrl("");
    setNotice("Đang phân tích nhịp nhạc và dựng video…");
    const payload = new FormData();
    multiclips.forEach((clip) => payload.append("clips", clip));
    payload.append("music", music);
    try {
      const response = await fetch(`${API_BASE_URL}/render`, { method: "POST", body: payload, headers: { Authorization: `Bearer ${token}` } });
      const result = await response.json() as { url?: string; credits?: number; detail?: string };
      if (!response.ok || !result.url) throw new Error(result.detail || "Không thể dựng video.");
      setRenderUrl(result.url);
      setAccount((old) => old ? { ...old, credits: result.credits ?? old.credits } : old);
      setNotice("Đã dựng xong video ghép theo nhạc.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Không thể kết nối bộ dựng video cục bộ.");
    } finally {
      setIsRendering(false);
    }
  }

  async function authenticate(action: "login" | "register") {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: authEmail, password: authPassword }) });
      const result = await response.json() as { token?: string; user?: { email: string; credits: number }; detail?: string };
      if (!response.ok || !result.token || !result.user) throw new Error(result.detail || "Không thể đăng nhập.");
      setToken(result.token);
      setAccount(result.user);
      setAuthOpen(false);
      setNotice(`Chào ${result.user.email}. Bạn có ${result.user.credits} credit dùng thử.`);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Không thể kết nối tài khoản."); }
  }

  async function checkout(plan: "starter" | "pro" | "studio") {
    if (!token) { setPaymentOpen(false); setAuthOpen(true); setNotice("Đăng nhập trước khi mua gói."); return; }
    setPaymentLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/orders/${plan}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
      const result = await response.json() as typeof order & { detail?: string };
      if (!response.ok || !result) throw new Error(result.detail || "Không tạo được đơn hàng.");
      setOrder(result);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Không thể tạo đơn hàng."); }
    finally { setPaymentLoading(false); }
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <Header onNotice={setNotice} account={account} onAuth={() => setAuthOpen(true)} onPricing={() => { setOrder(null); setPaymentOpen(true); }} />

      <aside className="fixed left-0 top-14 z-30 hidden h-[calc(100vh-3.5rem)] w-44 border-r border-border/60 bg-background/95 p-3 xl:block">
        <Button variant="outline" className="h-10 w-full justify-start border-brand/65 bg-brand/5 text-brand">
          <Home className="size-4" /> Trang chủ
        </Button>
        <div className="mt-auto flex h-[calc(100%-3rem)] items-end">
          <Button variant="ghost" className="w-full justify-start"><MessageSquareText className="size-4" /> Phản hồi</Button>
        </div>
      </aside>

      <main className="relative mx-auto max-w-[1040px] px-4 pb-14 pt-9 sm:px-6 xl:ml-[calc((100vw-1040px)/2+42px)]">
        <div className="pointer-events-none absolute left-1/2 top-6 -z-0 h-80 w-[620px] -translate-x-1/2 app-grid opacity-20 [mask-image:linear-gradient(to_bottom,black,transparent)]" />
        <section className="relative z-10 mx-auto max-w-xl text-center">
          <p className="text-sm font-semibold text-foreground">Một studio AI để tạo nội dung, xử lý ảnh và dựng video.</p>
          <p className="mt-3 text-xs text-muted-foreground">Dùng nội bộ hoặc đóng gói thành dịch vụ bán cho khách hàng của bạn.</p>

          <div className="mt-4 rounded-lg border border-border bg-card p-2 shadow-2xl">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Link2 className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  aria-label="Liên kết video"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && handleUrl()}
                  placeholder="Dán link YouTube, Google Drive, hoặc link file video"
                  className="h-10 w-full rounded-md border border-input bg-background pl-9 pr-3 text-xs outline-none placeholder:text-muted-foreground focus:border-brand"
                />
              </div>
              <Button variant="gold" size="sm" className="h-10" onClick={handleUrl}>Lấy video</Button>
            </div>

            <div className="my-2 flex items-center gap-3 text-xs uppercase text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">hoặc</div>

            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => { event.preventDefault(); chooseFile(event.dataTransfer.files[0]); }}
              className="flex h-16 w-full items-center justify-center gap-3 rounded-md border border-dashed border-border bg-panel-raised text-left transition-colors hover:border-brand/60"
            >
              <span className="grid size-8 place-items-center rounded-md bg-brand/10 text-brand"><CloudUpload className="size-4" /></span>
              <span>
                <strong className="block text-xs">{fileName || "Kéo thả file video dài vào đây"}</strong>
                <span className="mt-1 block text-xs text-muted-foreground">hoặc bấm để chọn file từ máy</span>
              </span>
            </button>
            <input ref={inputRef} type="file" accept="video/*" className="hidden" onChange={(event) => chooseFile(event.target.files?.[0])} />
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-center gap-1 text-xs">
            <span className="mr-2 text-muted-foreground">Chế độ tạo:</span>
            {["Talking-head", "Nhiều clip + Nhạc", "Video dài → Short"].map((item) => (
              <Button key={item} variant="ghost" size="sm" onClick={() => setMode(item)} className={cn("h-7 px-2", mode === item && "border-b border-brand text-brand")}>{item}</Button>
            ))}
          </div>

          {mode === "Nhiều clip + Nhạc" && (
            <div className="mt-4 rounded-lg border border-brand/35 bg-panel-raised p-4 text-left shadow-lg">
              <div className="flex items-center gap-2 text-xs font-bold text-foreground"><Music2 className="size-4 text-brand" /> Ghép clip theo nhịp nhạc</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">Chọn các clip rời và một bài nhạc bạn có quyền sử dụng. App sẽ cắt và ghép thành video dọc 9:16.</p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <Button type="button" variant="outline" className="h-auto min-h-16 justify-start px-3 py-3 text-left" onClick={() => multiclipInputRef.current?.click()}>
                  <Upload className="size-4 text-brand" />
                  <span><strong className="block text-sm">Chọn clip</strong><small className="block text-xs text-muted-foreground">{multiclips.length ? `${multiclips.length} clip đã chọn` : "Chọn nhiều file video"}</small></span>
                </Button>
                <Button type="button" variant="outline" className="h-auto min-h-16 justify-start px-3 py-3 text-left" onClick={() => musicInputRef.current?.click()}>
                  <Headphones className="size-4 text-brand" />
                  <span><strong className="block text-sm">Chọn nhạc</strong><small className="block max-w-40 truncate text-xs text-muted-foreground">{music?.name || "MP3, WAV, M4A…"}</small></span>
                </Button>
              </div>
              <input ref={multiclipInputRef} type="file" accept="video/*" multiple className="hidden" onChange={(event) => setMulticlips(Array.from(event.target.files || []))} />
              <input ref={musicInputRef} type="file" accept="audio/*" className="hidden" onChange={(event) => setMusic(event.target.files?.[0] || null)} />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Button type="button" variant="gold" size="sm" disabled={isRendering} onClick={renderMulticlip}>{isRendering ? "Đang dựng…" : "Ghép theo nhạc"}</Button>
                {renderUrl && <a href={renderUrl} target="_blank" rel="noreferrer" className="text-xs font-semibold text-brand underline">Mở video đã dựng</a>}
              </div>
            </div>
          )}
        </section>

        <section className="relative z-10 mt-8" aria-label="Các công năng của studio">
          <div className="mb-4 flex items-end justify-between gap-3">
            <div><p className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Studio công năng</p><h2 className="mt-1 text-lg font-bold">Chọn dịch vụ để bắt đầu</h2></div>
            <span className="rounded-full border border-brand/35 bg-brand/10 px-2.5 py-1 text-[10px] font-bold text-brand">Sẵn sàng bán theo gói</span>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {studioProducts.map(({ icon: Icon, title, description, mode: productMode, badge }) => (
              <button key={title} type="button" onClick={() => { setMode(productMode); setNotice(productMode === "Nhiều clip + Nhạc" ? "Đã mở bộ dựng video theo nhạc." : `${title} cần kết nối nhà cung cấp AI trước khi xuất thành phẩm.`); }} className={cn("rounded-xl border p-4 text-left transition hover:-translate-y-0.5 hover:border-brand/70 hover:shadow-brand", mode === productMode ? "border-brand bg-brand/5" : "border-border bg-card")}>
                <span className="grid size-10 place-items-center rounded-lg bg-brand/10 text-brand"><Icon className="size-5" /></span>
                <h3 className="mt-4 text-sm font-bold">{title}</h3>
                <p className="mt-1 min-h-10 text-xs leading-5 text-muted-foreground">{description}</p>
                <span className="mt-4 inline-block text-[11px] font-bold text-brand">{badge} →</span>
              </button>
            ))}
          </div>
        </section>

        <section className="relative z-10 mt-8" aria-labelledby="ai-tools-title">
          <h2 id="ai-tools-title" className="text-center text-[10px] font-bold uppercase tracking-[0.22em] text-muted-foreground">Được hỗ trợ bởi AI</h2>
          <div className="marquee relative mt-4 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_7%,black_93%,transparent)]">
            <div className="marquee-track flex w-max items-start">
              {[0, 1].map((copy) => (
                <div key={copy} aria-hidden={copy === 1} className="flex items-start gap-5 pr-5 sm:gap-8 sm:pr-8">
                  {tools.map(({ icon: Icon, label, sublabel }) => (
                    <button
                      key={`${copy}-${label}`}
                      type="button"
                      tabIndex={copy === 1 ? -1 : 0}
                      onClick={() => setNotice(`${label}${sublabel ? ` ${sublabel}` : ""} đã được chọn.`)}
                      className="group flex w-[72px] shrink-0 flex-col items-center gap-2 text-center sm:w-[86px]"
                    >
                      <span className="grid size-10 place-items-center rounded-full border border-border bg-panel-raised text-brand transition-all group-hover:border-brand group-hover:bg-brand/10"><Icon className="size-[18px]" strokeWidth={1.8} /></span>
                      <span className="text-[9px] font-semibold leading-3 text-muted-foreground group-hover:text-foreground">{label}<br />{sublabel}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="relative z-10 mt-9" aria-labelledby="sample-title">
          <h2 id="sample-title" className="mb-4 text-center text-[10px] font-bold uppercase tracking-[0.22em] text-muted-foreground">Video mẫu</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {samples.map((sample, index) => (
              <article key={sample.name} className={cn("group relative overflow-hidden rounded-lg border bg-card transition-colors", selectedSample === index ? "border-brand" : "border-border")}>
                <button type="button" onClick={() => toggleSample(index)} className="relative block aspect-[9/14] w-full overflow-hidden bg-panel">
                  <video ref={(el) => { videoRefs.current[index] = el; }} src={sample.video} muted loop autoPlay playsInline preload="auto" className="h-full w-full object-cover" />
                  <span className="absolute inset-0 bg-gradient-to-t from-background/60 via-transparent to-background/10" />
                  <span className="absolute right-2 top-2 grid size-6 place-items-center rounded-full border border-foreground/20 bg-background/65 text-foreground">
                    {playingSample === index ? <Pause className="size-3" fill="currentColor" /> : <Play className="ml-0.5 size-3" fill="currentColor" />}
                  </span>
                  {index === 4 && <span className="absolute inset-x-2 top-1/2 text-sm font-extrabold">Follow us for</span>}
                  {selectedSample === index && <span className="absolute left-2 top-2 grid size-5 place-items-center rounded-full bg-brand text-brand-foreground"><Check className="size-3" /></span>}
                </button>
                <div className="px-2 py-2 text-[10px] font-semibold">{sample.name}</div>
              </article>
            ))}
          </div>
        </section>

        <section className="relative z-10 mt-9" aria-label="Danh sách dự án">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
            <div className="flex items-center gap-4">
              {["Tất cả các dự án", "Dự án đã lưu", "Nháp"].map((item, index) => (
                <Button key={item} variant="ghost" size="sm" onClick={() => setTab(item)} className={cn("h-9 rounded-none px-0 text-[11px]", tab === item && "border-b-2 border-brand text-foreground")}>
                  {item} <span className="text-muted-foreground">({index === 0 ? 6 : 0})</span>
                </Button>
              ))}
            </div>
            <div className="flex gap-3 text-[10px]">
              <Button variant="ghost" size="sm" className="px-1">Chọn nhiều</Button>
              <Button variant="ghost" size="sm" className="px-1">Xem tất cả</Button>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {projects.map((project, index) => (
              <article key={`${project.title}-${index}`} className={cn("overflow-hidden rounded-lg border bg-card", project.active ? "border-brand/65" : "border-border")}>
                <div className="relative aspect-[16/9] overflow-hidden bg-panel-raised">
                  {project.image ? (
                    <img src={project.image} alt="" loading="lazy" width={768} height={1376} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full flex-col items-center justify-center gap-2 px-3 text-center">
                      <span className="grid size-8 place-items-center rounded-full bg-brand text-brand-foreground"><Play className="ml-0.5 size-4" fill="currentColor" /></span>
                      <span className="text-[9px] font-semibold">cải phân tích xương — bản đề xuất 8 cảnh</span>
                    </div>
                  )}
                  {project.image && <span className="absolute bottom-2 left-2 rounded bg-background/80 px-1.5 py-1 text-[8px] font-bold">Còn 15 ngày</span>}
                  <Button variant="ghost" size="icon" aria-label="Yêu thích dự án" onClick={() => setFavorite((old) => old.includes(index) ? old.filter((item) => item !== index) : [...old, index])} className="absolute right-1 top-1 size-7 bg-background/65">
                    <Star className={cn("size-3", favorite.includes(index) && "fill-brand text-brand")} />
                  </Button>
                </div>
                <div className="p-2">
                  <h3 className="truncate text-[10px] font-bold">{project.title}</h3>
                  <p className="mt-1 text-[8px] text-muted-foreground">{project.meta}</p>
                </div>
              </article>
            ))}
          </div>
        </section>
      </main>

      {authOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-2xl">
            <div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-widest text-brand">Video Magic Studio</p><h2 className="mt-1 text-lg font-bold">Tài khoản khách hàng</h2></div><Button variant="ghost" size="icon" onClick={() => setAuthOpen(false)}><X className="size-4" /></Button></div>
            <p className="mt-2 text-xs text-muted-foreground">Đăng ký nhận 3 credit dùng thử để dựng video.</p>
            <input value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} placeholder="Email" className="mt-4 h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-brand" />
            <input value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} type="password" placeholder="Mật khẩu (tối thiểu 8 ký tự)" className="mt-2 h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-brand" />
            <div className="mt-4 grid grid-cols-2 gap-2"><Button variant="outline" onClick={() => authenticate("login")}>Đăng nhập</Button><Button variant="gold" onClick={() => authenticate("register")}>Tạo tài khoản</Button></div>
          </div>
        </div>
      )}

      {paymentOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-background/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-2xl rounded-xl border border-border bg-card p-5 shadow-2xl">
            <div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-widest text-brand">Thanh toán VietQR</p><h2 className="mt-1 text-lg font-bold">Mua credit cho Studio</h2></div><Button variant="ghost" size="icon" onClick={() => setPaymentOpen(false)}><X className="size-4" /></Button></div>
            {!order ? <div className="mt-5 grid gap-3 sm:grid-cols-3">{[{ key: "starter", name: "Starter", price: "49.000đ", credits: 10 }, { key: "pro", name: "Pro", price: "129.000đ", credits: 35 }, { key: "studio", name: "Studio", price: "349.000đ", credits: 120 }].map((plan) => <button key={plan.key} disabled={paymentLoading} onClick={() => checkout(plan.key as "starter" | "pro" | "studio")} className="rounded-lg border border-border p-4 text-left transition hover:border-brand hover:bg-brand/5"><p className="font-bold">{plan.name}</p><p className="mt-2 text-xl font-bold text-brand">{plan.price}</p><p className="mt-1 text-xs text-muted-foreground">{plan.credits} credit</p></button>)}</div> : <div className="mt-5 grid gap-5 sm:grid-cols-[1fr_210px]"><div className="text-sm"><p className="font-bold">Chuyển khoản đúng số tiền để mở gói {order.plan.name}</p><dl className="mt-4 space-y-2 text-xs"><div><dt className="text-muted-foreground">Ngân hàng</dt><dd className="font-semibold">{order.bank.bank}</dd></div><div><dt className="text-muted-foreground">Số tài khoản</dt><dd className="font-semibold">{order.bank.account}</dd></div><div><dt className="text-muted-foreground">Chủ tài khoản</dt><dd className="font-semibold">{order.bank.name}</dd></div><div><dt className="text-muted-foreground">Nội dung bắt buộc</dt><dd className="font-bold text-brand">{order.code}</dd></div><div><dt className="text-muted-foreground">Số tiền</dt><dd className="font-bold">{order.plan.amount.toLocaleString("vi-VN")}đ</dd></div></dl><p className="mt-4 text-[11px] text-muted-foreground">Sau khi SePay xác nhận giao dịch, credit sẽ tự cộng vào tài khoản.</p></div><img src={order.qr_url} alt="QR thanh toán VietQR" className="w-full rounded-lg bg-white p-2" /></div>}
          </div>
        </div>
      )}

      {notice && (
        <div className="fixed bottom-5 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-2 rounded-md border border-brand/40 bg-popover px-4 py-3 text-xs shadow-2xl">
          <Check className="size-4 text-brand" /><span>{notice}</span>
          <Button variant="ghost" size="icon" aria-label="Đóng thông báo" onClick={() => setNotice("")} className="ml-2 size-6"><X className="size-3" /></Button>
        </div>
      )}
    </div>
  );
}

function Header({ onNotice, account, onAuth, onPricing }: { onNotice: (message: string) => void; account: { email: string; credits: number } | null; onAuth: () => void; onPricing: () => void }) {
  return (
    <header className="sticky top-0 z-40 h-14 border-b border-brand/25 bg-background/95 shadow-[0_4px_22px_color-mix(in_oklab,var(--brand)_10%,transparent)] backdrop-blur">
      <div className="flex h-full items-center justify-between px-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" size="icon" className="xl:hidden"><Menu className="size-4" /></Button>
          <div className="font-display text-2xl font-extrabold italic gold-text sm:text-3xl">Master Clip</div>
          <span className="hidden text-xs font-semibold text-muted-foreground sm:inline">Video dài → Nhiều Short</span>
        </div>
        <div className="hidden text-[10px] font-semibold text-muted-foreground lg:block">Thời Gian · Thu Nhập · Tự Do</div>
        <nav className="flex items-center gap-1.5">
          <Button variant="nav" size="sm" onClick={onPricing}><CircleDollarSign className="size-3.5" /><span className="hidden sm:inline">Nạp credit</span></Button>
          <Button variant="nav" size="sm" onClick={() => onNotice("Đã mở thư viện dự án.")}><FolderOpen className="size-3.5" /><span className="hidden md:inline">Dự án</span></Button>
          <Button variant="nav" size="sm" onClick={() => onNotice("Đã mở thư viện âm thanh.")}><Headphones className="size-3.5" /><span className="hidden md:inline">Âm thanh</span></Button>
          <Button variant="nav" size="sm" onClick={onAuth}><User className="size-3.5 sm:hidden" /><span className="hidden sm:inline">{account ? `${account.credits} credit` : "Đăng nhập"}</span></Button>
        </nav>
      </div>
    </header>
  );
}
