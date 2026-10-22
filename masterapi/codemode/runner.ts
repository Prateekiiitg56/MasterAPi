// MasterAPI Code Mode sandbox.
//
// Runs under Deno with no permissions (no network, files, env or subprocesses).
// The only way out is the `masterapi` binding: each call is a JSON line on
// stdout, answered by the Python host on stdin. Keys never enter this process.
//
// Messages (one JSON object per line):
//   host -> sandbox  {type: "run", code}              start
//                    {type: "result", id, ok, value | error}
//   sandbox -> host  {type: "call", id, method, args}
//                    {type: "log", level, text}
//                    {type: "done", ok, value | error}

const out = Deno.stdout;
const input = Deno.stdin.readable;
const exit = Deno.exit;
const encoder = new TextEncoder();

function send(message: unknown): void {
  const data = encoder.encode(JSON.stringify(message) + "\n");
  let written = 0;
  while (written < data.length) written += out.writeSync(data.subarray(written));
}

async function* lines(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  let buffer = "";
  for await (const chunk of stream.pipeThrough(new TextDecoderStream())) {
    buffer += chunk;
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      yield buffer.slice(0, nl);
      buffer = buffer.slice(nl + 1);
    }
  }
}

function format(value: unknown): string {
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.stack ?? `${value.name}: ${value.message}`;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

// The binding: every method is a call to the host.
let nextId = 0;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
function call(method: string, args: Record<string, unknown>): Promise<unknown> {
  const id = ++nextId;
  send({ type: "call", id, method, args });
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
const masterapi = Object.freeze({
  models: () => call("models", {}),
  chat: (model: string, prompt: unknown, options: Record<string, unknown> = {}) => call("chat", { model, prompt, options }),
  chatCompletion: (model: string, body: Record<string, unknown>) => call("chatCompletion", { model, body }),
  embed: (model: string, input: unknown, options: Record<string, unknown> = {}) => call("embed", { model, input, options }),
  image: (model: string, prompt: string, options: Record<string, unknown> = {}) => call("image", { model, prompt, options }),
  request: (alias: string, method: string, path: string, options: Record<string, unknown> = {}) =>
    call("request", { alias, method, path, options }),
});

const logger = Object.fromEntries(
  ["log", "info", "warn", "error", "debug"].map((level) => [
    level,
    (...args: unknown[]) => send({ type: "log", level, text: args.map(format).join(" ") }),
  ]),
);

const disabled = (what: string) => () => {
  throw new Error(`${what} is disabled in the sandbox. Use masterapi.request() to reach an API.`);
};

// Remove capabilities the agent's code must not touch. Deno permissions already
// deny them; this makes the failure clear and closes module-loading paths.
for (const name of ["Deno", "Worker", "WebSocket", "EventSource", "BroadcastChannel", "WebSocketStream"]) {
  try { delete (globalThis as Record<string, unknown>)[name]; } catch { /* not configurable */ }
}
(globalThis as Record<string, unknown>).fetch = disabled("Network access");
(globalThis as Record<string, unknown>).console = logger;  // keep stdout for the protocol
globalThis.addEventListener("unhandledrejection", (e) => {
  e.preventDefault();
  send({ type: "log", level: "error", text: `Unhandled rejection: ${format(e.reason)}` });
});

async function run(code: string): Promise<void> {
  const source = `export default async function (masterapi, console) {\n${code}\n}`;
  const url = "data:application/typescript;base64," + btoa(String.fromCharCode(...encoder.encode(source)));
  try {
    // Loading the agent's code is the one import allowed, and it happens here.
    const mod = await import(url);
    const value = await mod.default(masterapi, logger);
    send({ type: "done", ok: true, value: value === undefined ? null : JSON.parse(JSON.stringify(value)) });
  } catch (e) {
    send({ type: "done", ok: false, error: format(e) });
  }
  exit(0);
}

for await (const line of lines(input)) {
  if (!line.trim()) continue;
  const msg = JSON.parse(line);
  if (msg.type === "run") {
    run(msg.code);
  } else if (msg.type === "result") {
    const p = pending.get(msg.id);
    if (!p) continue;
    pending.delete(msg.id);
    if (msg.ok) p.resolve(msg.value);
    else p.reject(new Error(msg.error));
  }
}
