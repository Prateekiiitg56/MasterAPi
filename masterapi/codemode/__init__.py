"""Code Mode: agents write a short TypeScript program against a typed `masterapi`
API instead of making one tool call per step. The program runs in a Deno sandbox
with no permissions; its only way out is the `masterapi` binding, served here by
the Python host. Keys stay in this process and never reach the sandbox.

Same idea as Cloudflare's Code Mode, without Cloudflare: Deno's permission
system plays the role of the Worker isolate, stdio RPC plays the binding.
"""

import base64
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib import resources
from pathlib import Path

from ..client import MasterAPI, MasterAPIError
from ..providers import provider_for

MAX_CODE_CHARS = 100_000
MAX_OUTPUT_CHARS = 40_000
MAX_INLINE_BYTES = 256 * 1024
IMPORT_RE = re.compile(r"\bimport\b")
V8_FLAGS = "--disallow-code-generation-from-strings,--max-old-space-size=256"


class CodeModeError(Exception):
    pass


def find_deno() -> str | None:
    """MASTERAPI_DENO, then PATH, then the usual install locations."""
    candidates = [os.environ.get("MASTERAPI_DENO"), shutil.which("deno"),
                  str(Path.home() / ".deno" / "bin" / ("deno.exe" if os.name == "nt" else "deno"))]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links" / "deno.exe"))
    return next((c for c in candidates if c and Path(c).is_file()), None)


class Bindings:
    """What sandboxed code can do: exactly the methods of `masterapi` in the sandbox."""

    def __init__(self, api: MasterAPI, aliases: list[str] | None = None,
                 output_dir: str | os.PathLike = "masterapi-outputs"):
        self.api = api
        self.aliases = aliases  # None = every alias
        self.output_dir = Path(output_dir)

    def _allow(self, target: str) -> str:
        if not isinstance(target, str) or not target:
            raise MasterAPIError("model must be an alias name or 'alias:model'", 400)
        alias = target.partition(":")[0]
        if self.aliases is not None and alias not in self.aliases:
            raise MasterAPIError(f"alias '{alias}' is not available here", 403)
        return target

    def _save(self, data: bytes, content_type: str, stem: str) -> str:
        """Binary output goes to a file; the agent gets a path, not megabytes of base64."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
        path = self.output_dir / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}{ext}"
        path.write_bytes(data)
        return str(path.resolve())

    def models(self) -> list[dict]:
        out = []
        for name, alias in sorted(self.api.vault.aliases().items()):
            if self.aliases is not None and name not in self.aliases:
                continue
            try:
                caps = list(provider_for(alias).capabilities)
            except ValueError:
                caps = []
            out.append({"name": name, "provider": alias["provider"], "capabilities": caps,
                        "models": alias.get("models", {})})
        return out

    def chat(self, model: str, prompt, options: dict | None = None) -> str:
        return self.api.chat(self._allow(model), prompt, **(options or {}))

    def chatCompletion(self, model: str, body: dict) -> dict:  # noqa: N802 (matches the TS API)
        return self.api.chat_completion(self._allow(model), dict(body or {}))

    def embed(self, model: str, input, options: dict | None = None) -> list[list[float]]:
        return self.api.embed(self._allow(model), input, **(options or {}))

    def image(self, model: str, prompt: str, options: dict | None = None) -> list[dict]:
        items = self.api.image(self._allow(model), prompt, **(options or {}))
        result = []
        for item in items:
            item = dict(item)
            if b64 := item.pop("b64_json", None):
                item["path"] = self._save(base64.b64decode(b64), "image/png", "image")
            result.append(item)
        return result

    def request(self, alias: str, method: str, path: str, options: dict | None = None) -> dict:
        options = options or {}
        r = self.api.request(self._allow(alias), method, path, json=options.get("json"),
                             content=options.get("body"), params=options.get("query"),
                             headers=options.get("headers"))
        content_type = r.headers.get("content-type", "")
        response = {"status": r.status_code, "contentType": content_type}
        if "json" in content_type:
            try:
                response["body"] = r.json()
                return response
            except ValueError:
                pass
        if content_type.startswith("text/") or "xml" in content_type:
            response["body"] = r.text[:MAX_INLINE_BYTES]
        else:
            response["path"] = self._save(r.content, content_type or "application/octet-stream", "response")
            response["bytes"] = len(r.content)
        return response

    METHODS = ("models", "chat", "chatCompletion", "embed", "image", "request")

    def dispatch(self, method: str, args: dict):
        if method not in self.METHODS:
            raise MasterAPIError(f"unknown method '{method}'", 400)
        if method == "models":
            return self.models()
        try:
            return getattr(self, method)(**args)
        except TypeError as e:
            raise MasterAPIError(f"bad arguments to masterapi.{method}: {e}", 400) from None


class CodeRunner:
    def __init__(self, bindings: Bindings, *, timeout: float = 60, max_calls: int = 100,
                 concurrency: int = 4, deno: str | None = None):
        self.bindings = bindings
        self.timeout = timeout
        self.max_calls = max_calls
        self.concurrency = concurrency
        self.deno = deno or find_deno()

    @property
    def available(self) -> bool:
        return self.deno is not None

    def _command(self) -> list[str]:
        runner = resources.files("masterapi.codemode").joinpath("runner.ts")
        return [self.deno, "run", "--no-prompt", "--no-remote", "--no-npm", "--no-config", "--quiet",
                f"--v8-flags={V8_FLAGS}", str(runner)]

    @staticmethod
    def _env(cache_dir: str) -> dict:
        # Nothing secret: no MASTERAPI_KEY, no provider keys, no user env. (The sandboxed
        # code can't read env at all; this is the Deno process itself.) Without PATH and
        # PATHEXT, Deno on Windows stalls about 2 seconds at startup.
        env = {"DENO_DIR": cache_dir, "NO_COLOR": "1", "DENO_NO_UPDATE_CHECK": "1"}
        for name in ("SystemRoot", "TEMP", "TMP", "PATH", "PATHEXT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def run(self, code: str) -> dict:
        """Run agent code. Returns {ok, result | error, logs, calls, seconds}."""
        if not self.available:
            raise CodeModeError("Deno is not installed; install it or set MASTERAPI_DENO (https://deno.com)")
        if len(code) > MAX_CODE_CHARS:
            return self._fail("code is too long", [], 0, 0.0)
        if IMPORT_RE.search(code):
            return self._fail("`import` is not available in the sandbox; everything you need is on `masterapi`. "
                              "If a string contains the word, split it: 'im' + 'port'.", [], 0, 0.0)

        start = time.monotonic()
        logs: list[str] = []
        calls = 0
        cache = Path(tempfile.gettempdir()) / "masterapi-deno-cache"
        with tempfile.TemporaryDirectory(prefix="masterapi-sandbox-") as workdir:
            proc = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, cwd=workdir, env=self._env(str(cache)),
                                    text=True, encoding="utf-8", bufsize=1)
            messages: queue.Queue = queue.Queue()
            threading.Thread(target=self._pump, args=(proc.stdout, messages), daemon=True).start()
            stderr: list[str] = []
            threading.Thread(target=lambda: stderr.extend(proc.stderr), daemon=True).start()
            write_lock = threading.Lock()

            def reply(message: dict) -> None:
                with write_lock:
                    try:
                        proc.stdin.write(json.dumps(message) + "\n")
                        proc.stdin.flush()
                    except (BrokenPipeError, OSError, ValueError):
                        pass  # sandbox already exited

            def serve(msg: dict) -> None:
                try:
                    value = self.bindings.dispatch(msg.get("method"), msg.get("args") or {})
                    reply({"type": "result", "id": msg["id"], "ok": True, "value": value})
                except MasterAPIError as e:
                    reply({"type": "result", "id": msg["id"], "ok": False, "error": f"{e} (HTTP {e.status})"})
                except Exception as e:  # never crash the host on bad input from the sandbox
                    reply({"type": "result", "id": msg["id"], "ok": False, "error": f"{type(e).__name__}: {e}"})

            reply({"type": "run", "code": code})
            pool = ThreadPoolExecutor(self.concurrency)
            try:
                while True:
                    remaining = self.timeout - (time.monotonic() - start)
                    if remaining <= 0:
                        return self._fail(f"timed out after {self.timeout:.0f}s", logs, calls, start)
                    try:
                        msg = messages.get(timeout=remaining)
                    except queue.Empty:
                        continue
                    if msg is None:
                        detail = "".join(stderr)[-2000:].strip()
                        return self._fail(f"sandbox exited unexpectedly{': ' + detail if detail else ''}",
                                          logs, calls, start)
                    kind = msg.get("type")
                    if kind == "log":
                        logs.append(f"[{msg.get('level', 'log')}] {msg.get('text', '')}")
                    elif kind == "call":
                        calls += 1
                        if calls > self.max_calls:
                            reply({"type": "result", "id": msg.get("id"), "ok": False,
                                   "error": f"call limit reached ({self.max_calls} per run)"})
                        else:
                            pool.submit(serve, msg)
                    elif kind == "done":
                        outcome = {"result": msg.get("value")} if msg.get("ok") else {"error": msg.get("error")}
                        return {"ok": bool(msg.get("ok")), **outcome, "logs": logs, "calls": calls,
                                "seconds": round(time.monotonic() - start, 2)}
            finally:
                # Don't wait for in-flight provider calls of an abandoned run.
                pool.shutdown(wait=False, cancel_futures=True)
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)

    @staticmethod
    def _pump(stream, messages: queue.Queue) -> None:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                messages.put(json.loads(line))
            except ValueError:
                messages.put({"type": "log", "level": "stdout", "text": line})
        messages.put(None)

    @staticmethod
    def _fail(error: str, logs: list[str], calls: int, start: float) -> dict:
        seconds = round(time.monotonic() - start, 2) if start else 0.0
        return {"ok": False, "error": error, "logs": logs, "calls": calls, "seconds": seconds}


def format_run(result: dict) -> str:
    """Render a run for the agent, capped so a huge result can't flood its context."""
    parts = []
    if result["ok"]:
        parts.append("Result:\n" + json.dumps(result.get("result"), indent=2, ensure_ascii=False))
    else:
        parts.append("Error:\n" + str(result.get("error")))
    if result.get("logs"):
        parts.append("Console:\n" + "\n".join(result["logs"]))
    parts.append(f"({result.get('calls', 0)} masterapi calls, {result.get('seconds', 0)}s)")
    text = "\n\n".join(parts)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f"\n\n[output truncated at {MAX_OUTPUT_CHARS} characters; return less data]"
    return text
