import app from "./dist/server/server.js";

export default {
  async fetch(request, env, ctx) {
    const pathname = new URL(request.url).pathname;
    if (pathname.startsWith("/api/")) {
      const incoming = new URL(request.url);
      const backend = new URL(
        `https://video-magic-api-fp7a.onrender.com${pathname.slice(4)}${incoming.search}`,
      );
      return fetch(new Request(backend, request));
    }
    if (
      pathname.startsWith("/assets/") ||
      pathname.startsWith("/samples/") ||
      pathname === "/master-clip-hero.jpg" ||
      pathname === "/favicon.ico" ||
      pathname === "/robots.txt"
    ) {
      return env.ASSETS.fetch(request);
    }
    return app.fetch(request, env, ctx);
  },
};
