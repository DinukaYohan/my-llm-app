// frontend/server.js
import { createServer } from "http";
import { readFile } from "fs/promises";
import { extname, join } from "path";

const PORT = 3000;
const publicDir = new URL(".", import.meta.url).pathname;

const mime = {
  ".html": "text/html",
  ".js":   "application/javascript",
  ".css":  "text/css",
  ".json": "application/json"
};

createServer(async (req, res) => {
  let url = req.url === "/" ? "/index.html" : req.url;
  let filePath = join(publicDir, url);
  try {
    const data = await readFile(filePath);
    const type = mime[extname(filePath)] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": type });
    res.end(data);
  } catch {
    // API proxy
    if (req.method === "POST" && req.url === "/generate") {
      let body = "";
      for await (const chunk of req) body += chunk;
      const response = await fetch("http://127.0.0.1:5000/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body
      });
      const json = await response.json();
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify(json));
    }

    if (req.method === "GET" && req.url.startsWith("/history")) {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const backendUrl = `http://127.0.0.1:5000/history?${url.searchParams.toString()}`;
    const r = await fetch(backendUrl);
    const text = await r.text();
    res.writeHead(r.status, { "Content-Type": r.headers.get("content-type") || "application/json" });
    return res.end(text);
}

    res.writeHead(404);
    res.end();
  }
}).listen(PORT, () => console.log(`Frontend running at http://localhost:${PORT}`));
