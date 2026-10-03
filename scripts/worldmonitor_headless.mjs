import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

function option(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || fallback) : fallback;
}

const root = path.resolve(option("--root", process.cwd()));
const port = Number(option("--port", "3000"));
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error("invalid port");
}

// Import Vite from the selected World Monitor checkout. This avoids relying on
// a global npm installation and, importantly, bypasses the upstream CLI's
// automatic browser-opening behavior.
const viteEntry = path.join(root, "node_modules", "vite", "dist", "node", "index.js");
const { createServer } = await import(pathToFileURL(viteEntry).href);
const server = await createServer({
  root,
  configFile: path.join(root, "vite.config.ts"),
  server: { host: "127.0.0.1", port, strictPort: true, open: false },
  logLevel: "error",
});

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  try {
    await server.close();
  } finally {
    process.exit(0);
  }
}
process.on("SIGINT", close);
process.on("SIGTERM", close);
await server.listen();
