import { createServer } from "node:http";

const port = Number(process.env.PORT ?? 5173);
const page = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Backroom</title></head>
<body><p>Backroom web is not built yet. The API is at <a href="http://localhost:8000/docs">localhost:8000/docs</a>.</p></body>
</html>`;

createServer((_req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(page);
}).listen(port, "0.0.0.0");
