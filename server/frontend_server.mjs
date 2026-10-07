import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { join, normalize } from "node:path";
import { Readable } from "node:stream";

import app from "../dist/server/server.js";

const clientRoot = join(import.meta.dirname, "..", "dist", "client");
const port = Number(process.env.PORT || 10000);

const contentTypes = {
  ".css": "text/css", ".ico": "image/x-icon", ".js": "text/javascript",
  ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4",
  ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp",
};

function localAsset(pathname) {
  const file = normalize(join(clientRoot, decodeURIComponent(pathname)));
  return file.startsWith(clientRoot) && existsSync(file) && statSync(file).isFile() ? file : null;
}

createServer(async (request, response) => {
  const origin = `http://${request.headers.host || "localhost"}`;
  const url = new URL(request.url || "/", origin);
  const asset = localAsset(url.pathname);
  if (asset) {
    const extension = asset.slice(asset.lastIndexOf("."));
    const size = statSync(asset).size;
    const isVersioned = /(?:-v\d+|[.-][a-f0-9]{8,})\.[a-z0-9]+$/i.test(url.pathname);
    const cacheControl = isVersioned
      ? "public, max-age=31536000, immutable"
      : "public, max-age=86400";
    const headers = {
      "content-type": contentTypes[extension] || "application/octet-stream",
      "cache-control": cacheControl,
      "accept-ranges": "bytes",
    };
    const range = request.headers.range;
    if (range) {
      const match = /^bytes=(\d*)-(\d*)$/.exec(range);
      if (!match) {
        response.writeHead(416, { ...headers, "content-range": `bytes */${size}` });
        response.end();
        return;
      }
      const start = match[1] ? Number(match[1]) : 0;
      const end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || start > end || start >= size) {
        response.writeHead(416, { ...headers, "content-range": `bytes */${size}` });
        response.end();
        return;
      }
      response.writeHead(206, {
        ...headers,
        "content-range": `bytes ${start}-${end}/${size}`,
        "content-length": end - start + 1,
      });
      if (request.method === "HEAD") response.end();
      else createReadStream(asset, { start, end }).pipe(response);
      return;
    }
    response.writeHead(200, { ...headers, "content-length": size });
    if (request.method === "HEAD") response.end();
    else createReadStream(asset).pipe(response);
    return;
  }

  try {
    const body = ["GET", "HEAD"].includes(request.method || "GET") ? undefined : request;
    const webRequest = new Request(url, { method: request.method, headers: request.headers, body, duplex: "half" });
    const result = await app.fetch(webRequest, {}, { waitUntil() {} });
    response.writeHead(result.status, Object.fromEntries(result.headers));
    if (result.body) Readable.fromWeb(result.body).pipe(response);
    else response.end();
  } catch (error) {
    console.error(error);
    response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
    response.end("Unable to load the application.");
  }
}).listen(port, "0.0.0.0", () => console.log(`Frontend listening on ${port}`));
