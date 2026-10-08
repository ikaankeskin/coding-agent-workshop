"""Local page that shows the agent loop and the developer log."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import queue
import threading

from harness.trace import Trace

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness</title>
<style>
  :root {
    --ink: #1c1915;
    --paper: #f6f1e8;
    --panel: #fffaf3;
    --line: #e2d8c8;
    --muted: #6f675c;
    --accent: #b8431f;
    --ok: #2f6b4f;
    --live: #f3d2c4;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font: 15px/1.45 "Iowan Old Style", Palatino, Georgia, serif;
    color: var(--ink);
    background: var(--paper);
  }
  header, main { padding: 20px 24px; }
  header { border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
  h1 { font-size: 22px; font-weight: 600; margin: 0; }
  .workspace { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  form { display: flex; gap: 12px; align-items: flex-end; margin-top: 16px; }
  textarea {
    flex: 1;
    min-height: 64px;
    padding: 10px 12px;
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--ink);
    font: inherit;
    resize: vertical;
  }
  button {
    background: var(--ink);
    color: var(--paper);
    border: 0;
    padding: 12px 18px;
    font: inherit;
    cursor: pointer;
  }
  button:disabled { opacity: 0.45; cursor: wait; }
  .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-top: 14px; }
  .controls label { display: flex; flex-direction: column; gap: 4px; color: var(--muted); font-size: 13px; }
  .controls input[type="password"], .controls input[type="text"] {
    min-width: 240px;
    padding: 8px 10px;
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--ink);
    font: 14px ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .controls .check { flex-direction: row; align-items: center; color: var(--ink); padding-bottom: 8px; }
  .samples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
  .sample {
    background: var(--panel);
    color: var(--ink);
    border: 1px solid var(--line);
    padding: 6px 10px;
    text-align: left;
    font-size: 14px;
  }
  .sample small { display: block; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
  .layout { display: grid; grid-template-columns: minmax(300px, 440px) 1fr 1fr; gap: 16px; align-items: start; }
  section { background: var(--panel); border: 1px solid var(--line); padding: 14px; }
  h2 { margin: 0 0 12px; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
  #reply, #log { min-height: 280px; }
  .live-flow { display: flex; flex-direction: column; align-items: stretch; gap: 0; }
  .live-flow .node { min-width: 0; width: 100%; padding: 7px 10px; }
  .live-flow .node.visited { border-color: var(--ink); background: #efe6d6; }
  .live-flow .node.live { border-color: var(--accent); background: var(--live); }
  .live-flow .split { width: 100%; }
  #trail { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow: auto; }
  #trail li {
    padding: 6px 8px;
    border-left: 3px solid var(--line);
    margin-bottom: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
  }
  #trail li.live { border-color: var(--accent); background: var(--live); }
  #reply, #log {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.5;
  }
  #log div { padding: 4px 0; border-bottom: 1px solid var(--line); }
  #log .kind { color: var(--accent); }
  .status { color: var(--ok); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  nav { display: flex; gap: 8px; }
  .tab {
    background: transparent;
    color: var(--ink);
    border: 1px solid var(--line);
    padding: 6px 12px;
  }
  .tab.active { background: var(--ink); color: var(--paper); }
  .flow { display: flex; flex-direction: column; align-items: center; gap: 0; margin: 8px 0 20px; }
  .node {
    border: 1px solid var(--line);
    background: var(--panel);
    padding: 8px 14px;
    min-width: 220px;
    text-align: center;
  }
  .node strong { display: block; }
  .node span { color: var(--muted); font-size: 13px; }
  .arrow { color: var(--accent); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; padding: 4px 0; }
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; width: min(760px, 100%); }
  .branch { display: flex; flex-direction: column; align-items: center; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0 20px; font-size: 14px; }
  th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 8px 10px; vertical-align: top; }
  th { color: var(--muted); font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; font-weight: 600; }
  .arch h2 { margin-top: 18px; }
  .arch p { margin: 8px 0; }
  .note { color: var(--muted); font-size: 13px; }
  @media (max-width: 900px) {
    .layout, .split { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<header>
  <div>
    <h1>Harness</h1>
    <div class="workspace" id="workspace"></div>
  </div>
  <nav>
    <button type="button" class="tab active" data-tab="run">Run</button>
    <button type="button" class="tab" data-tab="architecture">Architecture</button>
  </nav>
  <div class="status" id="status">Idle</div>
</header>
<main>
  <div id="panel-run">
  <div class="controls">
    <label>Anthropic API key
      <input id="api-key" type="password" autocomplete="off" placeholder="Uses the server environment if empty">
    </label>
    <label class="check"><input id="openappa" type="checkbox"> OpenAPPA for sub-agents</label>
    <label>OpenAPPA URL
      <input id="appa-url" type="text" value="http://127.0.0.1:8787" disabled>
    </label>
  </div>
  <p class="note">The key is sent only to this local server for the run. It is not written to disk. OpenAPPA stays off until the box is checked.</p>
  <div class="samples" id="samples"></div>
  <form id="form">
    <label for="task" style="position:absolute;left:-999px">Task</label>
    <textarea id="task" name="task" placeholder="What should the agent do?"></textarea>
    <button id="run" type="submit">Run</button>
  </form>
  <div class="layout" style="margin-top:16px">
    <section>
      <h2>Loop</h2>
      <div class="live-flow" id="map">
        <div class="node" data-stage="user"><strong>User task</strong><span>this page, the prompt, or the CLI</span></div>
        <div class="arrow">system prompt and AGENTS.md</div>
        <div class="node" data-stage="context"><strong>Context</strong><span>budget, then a summary if it is full</span></div>
        <div class="arrow">eligible models only</div>
        <div class="node" data-stage="route"><strong>Router</strong><span>sticky choice for this conversation</span></div>
        <div class="arrow">OpenJev if more than one model fits</div>
        <div class="node" data-stage="model"><strong>Language model</strong><span>streamed OpenAI or Anthropic</span></div>
        <div class="arrow">tool calls go left, a plain reply goes right</div>
        <div class="split">
          <div class="branch">
            <div class="node" data-stage="tools"><strong>Tools</strong><span>deny, allow, then OpenJev</span></div>
            <div class="arrow">pre, tool, post</div>
            <div class="node" data-stage="hooks"><strong>Hooks</strong><span>then back to context</span></div>
          </div>
          <div class="branch">
            <div class="node" data-stage="openjev"><strong>OpenJev</strong><span>model, permit, done, spawn</span></div>
            <div class="arrow">one continuation, then stop</div>
            <div class="node" data-stage="stop"><strong>Stop</strong><span>final reply</span></div>
          </div>
        </div>
      </div>
      <h2 style="margin-top:16px">This run</h2>
      <ol id="trail"></ol>
    </section>
    <section>
      <h2>Reply</h2>
      <div id="reply"></div>
    </section>
    <section>
      <h2>Developer log</h2>
      <div id="log"></div>
    </section>
  </div>
  </div>
  <div id="panel-architecture" class="arch" hidden>
    <h2>Turn flow</h2>
    <p>The harness owns the loop. OpenAI or Anthropic writes the reply and requests tools. OpenJev only answers typed decisions: which model, whether a tool may run, whether the task is finished, and whether a sub-agent should start.</p>
    <div class="flow">
      <div class="node"><strong>User task</strong><span>CLI, prompt, or this page</span></div>
      <div class="arrow">system prompt + AGENTS.md</div>
      <div class="node"><strong>Context window</strong><span>100000 tokens, 4000 held for the reply</span></div>
      <div class="arrow">over the ceiling: replace the transcript with an 8000-token summary</div>
      <div class="node"><strong>Model router</strong><span>key present, window fits, sticky choice</span></div>
      <div class="arrow">one model, or OpenJev picks among the catalog</div>
      <div class="node"><strong>Language model</strong><span>streamed OpenAI or Anthropic</span></div>
      <div class="arrow">branch on tool calls</div>
      <div class="split">
        <div class="branch">
          <div class="node"><strong>Permission and tools</strong><span>deny, allow, then OpenJev</span></div>
          <div class="arrow">pre-hook, tool, post-hook</div>
          <div class="node"><strong>Back to context</strong><span>result appended, next turn</span></div>
        </div>
        <div class="branch">
          <div class="node"><strong>Task done?</strong><span>OpenJev yes/no</span></div>
          <div class="arrow">no: one continuation. yes, or OpenJev down: stop</div>
          <div class="node"><strong>Stop</strong><span>hooks, then the final reply</span></div>
        </div>
      </div>
    </div>
    <p class="note">A tool result returns to the context. A failed done check returns to the model once. The loop also stops at the turn cap, on interrupt, or when compression still cannot fit.</p>

    <h2>Tools</h2>
    <table>
      <thead><tr><th>Tool</th><th>What the harness enforces</th></tr></thead>
      <tbody>
        <tr><td>read_file</td><td>Pages large files and records path, mtime, and size.</td></tr>
        <tr><td>edit_file</td><td>Exact old string and new string. Requires a prior read, one match, and an unchanged file.</td></tr>
        <tr><td>write_file</td><td>Creates or replaces a file. An existing file must have been read first.</td></tr>
        <tr><td>bash</td><td>Runs in the workspace with a timeout and truncated output.</td></tr>
        <tr><td>grep / glob</td><td>Search and file listing, formatted for the model.</td></tr>
        <tr><td>write_note</td><td>Durable notes under .agent/memory.</td></tr>
        <tr><td>spawn_agent</td><td>A fresh loop. Only the summary returns. A sub-agent cannot spawn another. When APPA_RUNTIME_URL is set, OpenAPPA must release the spawn and the summary before the parent sees either.</td></tr>
      </tbody>
    </table>

    <h2>OpenJev</h2>
    <table>
      <thead><tr><th>Decision</th><th>When</th><th>If unsure or the server is down</th></tr></thead>
      <tbody>
        <tr><td>Which model</td><td>Start of a main conversation, a sub-agent, or a compression summary</td><td>default_model if it fits, otherwise the largest eligible window</td></tr>
        <tr><td>Allow this tool</td><td>Bash, write, or edit that matched neither a deny nor an allow pattern</td><td>Deny. The tool does not run</td></tr>
        <tr><td>Is the task finished</td><td>The model returned no tool calls</td><td>Accept the model's stop</td></tr>
        <tr><td>Spawn or inline</td><td>The model calls spawn_agent</td><td>Stay in the main conversation</td></tr>
      </tbody>
    </table>

    <h2>Settings</h2>
    <p>Later layers replace earlier ones: built-in defaults, ~/.agent-harness/settings.json, .agent/settings.json, .agent/settings.local.json, then environment variables. API keys stay in the environment. AGENT_MODEL pins the main conversation and skips the model choice.</p>
  </div>
</main>
<script>
const samples = [
  ["Search", "glob, grep, read", "Do not change any files. Use glob to list the Python files in harness/tools. Then grep those files for write_note. Then read harness/tools/notes.py and quote the description of the write_note tool."],
  ["Edit and test", "read, edit, bash", "In demo-task/calc.py add mul(a, b) that returns a * b. In demo-task/test_calc.py add a test that mul(2, 4) is 8. Then run python -m unittest demo-task/test_calc.py and report the result."],
  ["Write a file", "write_file", "Create demo-task/greeting.txt containing exactly this line: hello from the harness. Do not change other files."],
  ["Save a note", "write_note", "Use the write_note tool to save a note named tour. The content should be: OpenJev chooses, the model writes. Then stop."],
  ["Sub-agent", "spawn_agent", "Use a sub-agent to investigate how spawning works. Its task: Read harness/loop.py, harness/decisions.py, and harness/tools/spawn.py. Explain how a sub-agent is approved and what it returns to the parent. Report the summary. If OpenJev refuses, do that reading here and say so."],
  ["Ask permission", "OpenJev permit", "Run exactly this command with the bash tool and nothing else: echo harness-permission. Tell me whether it was allowed and what it printed."],
  ["Blocked command", "deny pattern", "Run exactly this command with the bash tool and nothing else: git push. Tell me whether the harness allowed it. Do not run a different command."],
  ["Tour", "grep, write, note, bash", "Do these steps in order, then stop. Do not explore beyond them. 1. Grep the repo for def write_note. 2. Create demo-task/greeting.txt with the line hello from the harness. 3. Use write_note to save a note named tour with the content: search, write, and note. 4. Run python -m unittest demo-task/test_calc.py. Report which steps succeeded."]
];
const sampleRow = document.getElementById("samples");
const taskBox = document.getElementById("task");
const form = document.getElementById("form");
for (const [name, detail, task] of samples) {
  const sample = document.createElement("button");
  sample.type = "button";
  sample.className = "sample";
  const title = document.createElement("span");
  title.textContent = name;
  const features = document.createElement("small");
  features.textContent = detail;
  sample.append(title, features);
  sample.addEventListener("click", () => {
    if (button.disabled) return;
    taskBox.value = task;
    form.requestSubmit();
  });
  sampleRow.appendChild(sample);
}

const nodes = {};
for (const node of document.querySelectorAll("#map .node")) nodes[node.dataset.stage] = node;
const trail = document.getElementById("trail");
const reply = document.getElementById("reply");
const log = document.getElementById("log");
const status = document.getElementById("status");
const button = document.getElementById("run");
const openappa = document.getElementById("openappa");
const appaUrl = document.getElementById("appa-url");
openappa.addEventListener("change", () => { appaUrl.disabled = !openappa.checked; });
document.getElementById("workspace").textContent = "__WORKSPACE__";

function mark(stage) {
  for (const node of Object.values(nodes)) node.classList.remove("live");
  if (nodes[stage]) {
    nodes[stage].classList.add("live", "visited");
    nodes[stage].scrollIntoView({block: "nearest"});
  }
}

function resetMap() {
  for (const node of Object.values(nodes)) node.classList.remove("live", "visited");
  trail.textContent = "";
}

function clip(text) {
  const value = String(text || "");
  return value.length > 140 ? value.slice(0, 140) + "…" : value;
}

function pushTrail(event) {
  for (const item of trail.querySelectorAll("li")) item.classList.remove("live");
  const item = document.createElement("li");
  item.className = "live";
  item.textContent = event.kind + " — " + clip(event.message);
  trail.appendChild(item);
  trail.scrollTop = trail.scrollHeight;
}

const source = new EventSource("/events");
source.onmessage = (message) => {
  const event = JSON.parse(message.data);
  if (event.kind === "run") {
    reply.textContent = "";
    log.textContent = "";
    resetMap();
    status.textContent = "Running";
    button.disabled = true;
    mark("user");
    pushTrail(event);
    return;
  }
  mark(event.stage || event.kind);
  if (event.kind !== "text") pushTrail(event);
  if (event.kind === "text") {
    reply.textContent += event.message;
    return;
  }
  const row = document.createElement("div");
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = event.kind + "  ";
  row.append(kind, document.createTextNode(event.message));
  if (event.fields && Object.keys(event.fields).length) {
    row.append(document.createTextNode("\\n" + JSON.stringify(event.fields)));
  }
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  if (event.kind === "stop") {
    status.textContent = "Stopped: " + event.message;
    button.disabled = false;
  }
};

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    const name = tab.dataset.tab;
    document.getElementById("panel-run").hidden = name !== "run";
    document.getElementById("panel-architecture").hidden = name !== "architecture";
  });
});

document.getElementById("form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = document.getElementById("task").value.trim();
  if (!task) return;
  button.disabled = true;
  const response = await fetch("/run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      task,
      anthropic_api_key: document.getElementById("api-key").value.trim(),
      openappa: openappa.checked,
      appa_url: appaUrl.value.trim()
    })
  });
  if (!response.ok) {
    status.textContent = await response.text();
    button.disabled = false;
  }
});
</script>
</body>
</html>
"""


class Hub:
    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.running = False

    def publish(self, event: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def subscribe(self) -> queue.Queue:
        inbox: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(inbox)
        return inbox

    def unsubscribe(self, inbox: queue.Queue) -> None:
        with self._lock:
            if inbox in self._subscribers:
                self._subscribers.remove(inbox)


def serve(run_task, workspace: str, port: int = 8765) -> None:
    hub = Hub()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body = PAGE.replace("__WORKSPACE__", html.escape(workspace)).encode()
                self._send(200, "text/html; charset=utf-8", body)
                return
            if self.path == "/events":
                self._events()
                return
            self._send(404, "text/plain; charset=utf-8", b"Not found")

        def do_POST(self):
            if self.path != "/run":
                self._send(404, "text/plain; charset=utf-8", b"Not found")
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, "text/plain; charset=utf-8", b"Task JSON is invalid")
                return
            task = str(payload.get("task") or "").strip()
            if not task:
                self._send(400, "text/plain; charset=utf-8", b"Give the agent a task.")
                return
            if hub.running:
                self._send(409, "text/plain; charset=utf-8", b"A task is already running.")
                return
            hub.running = True
            hub.publish({"kind": "run", "stage": "user", "message": task, "fields": {}})
            options = {
                "anthropic_api_key": str(payload.get("anthropic_api_key") or ""),
                "openappa": bool(payload.get("openappa")),
                "appa_url": str(payload.get("appa_url") or ""),
            }
            threading.Thread(target=_run, args=(run_task, hub, task, options), daemon=True).start()
            self._send(202, "text/plain; charset=utf-8", b"started")

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            inbox = hub.subscribe()
            try:
                while True:
                    event = inbox.get()
                    self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                return
            finally:
                hub.unsubscribe(inbox)

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Harness UI at http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


def _run(run_task, hub: Hub, task: str, options: dict | None = None) -> None:
    trace = Trace(dev=True)
    trace.listeners.append(hub.publish)
    options = options or {}
    try:
        run_task(task, trace, options)
    except Exception as exc:
        message = str(exc)
        key = str(options.get("anthropic_api_key") or "")
        if key:
            message = message.replace(key, "[redacted]")
        hub.publish({"kind": "stop", "stage": "stop", "message": message, "fields": {}})
    finally:
        hub.running = False
