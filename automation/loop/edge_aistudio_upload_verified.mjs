import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const [localPath, remotePath] = process.argv.slice(2);
// AIStudio canvas 终端处理大段 base64 输入较慢，超时通过环境变量放宽
// （默认 120s；慢速终端可设 CDP_TIMEOUT_MS=240000）。
const timeoutMs = parseInt(process.env.CDP_TIMEOUT_MS || "120000", 10);
if (!localPath || !remotePath) {
  throw new Error("usage: edge_aistudio_upload_verified.mjs LOCAL REMOTE");
}
const remoteRoot = "/home/aiuser/work/automation_submissions/";
if (!remotePath.startsWith(remoteRoot)) {
  throw new Error(`Remote path must stay under ${remoteRoot}`);
}

const bytes = readFileSync(localPath);
const payload = bytes.toString("base64");
const localSha = createHash("sha256").update(bytes).digest("hex");
const marker = `CODEX_UPLOAD_OK_${localSha}`;
const command =
  `python -c 'import base64,hashlib,pathlib; ` +
  `p=pathlib.Path(${JSON.stringify(remotePath)}); ` +
  `p.parent.mkdir(parents=True,exist_ok=True); ` +
  `p.write_bytes(base64.b64decode(${JSON.stringify(payload)})); ` +
  `h=hashlib.sha256(p.read_bytes()).hexdigest(); ` +
  `assert h==${JSON.stringify(localSha)},(h,${JSON.stringify(localSha)}); ` +
  `print(${JSON.stringify(marker)})'`;

const targets = await fetch("http://127.0.0.1:9222/json/list").then((r) => r.json());
const target = targets.find(
  (item) => item.type === "page" && item.url.includes("bigquant.com/aistudio/studios/"),
);
if (!target) throw new Error("No AIStudio page in external Edge");

const socket = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(JSON.stringify(message.error)));
  else resolve(message.result);
});
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
function cdp(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await cdp("Page.bringToFront");
const focused = await cdp("Runtime.evaluate", {
  expression: `(() => {
    const nodes = Array.from(document.querySelectorAll(".xterm-helper-textarea"));
    const node = nodes[nodes.length - 1];
    if (!node) return false;
    node.focus();
    return document.activeElement === node;
  })()`,
  returnByValue: true,
});
if (!focused.result.value) throw new Error("No open AIStudio terminal");

await cdp("Input.insertText", { text: command });
for (const type of ["rawKeyDown", "keyUp"]) {
  await cdp("Input.dispatchKeyEvent", {
    type,
    key: "Enter",
    code: "Enter",
    windowsVirtualKeyCode: 13,
    nativeVirtualKeyCode: 13,
  });
}

let terminalText = "";
const started = Date.now();
while (Date.now() - started < timeoutMs) {
  await pause(500);
  const result = await cdp("Runtime.evaluate", {
    expression: `Array.from(document.querySelectorAll(".xterm-rows > div"))
      .map((row) => row.innerText || row.textContent || "").slice(-120).join("\\n")`,
    returnByValue: true,
  });
  terminalText = result.result?.value || "";
  if (terminalText.includes(marker)) break;
}
socket.close();
if (!terminalText.includes(marker)) {
  throw new Error(`Remote hash marker not observed for ${remotePath}`);
}

console.log(JSON.stringify({
  ok: true,
  localPath,
  remotePath,
  bytes: bytes.length,
  localSha,
  remoteSha: localSha,
}, null, 2));
