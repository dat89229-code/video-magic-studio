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
    response.writeHead(200, { "content-type": contentTypes[extension] || "application/octet-stream" });
    createReadStream(asset).pipe(response);
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
