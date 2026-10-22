"use strict";

// MasterAPI dashboard. All data comes from the admin API; it never receives a
// plaintext key back. The DOM is built with textContent only (no innerHTML).

/* ---------- Utilities ---------- */

const $ = (sel, root = document) => root.querySelector(sel);
const OPS = ["chat", "embeddings", "images"];
const OP_LABEL = { chat: "Chat", embeddings: "Embeddings", images: "Images" };
const state = { token: null, me: null, providers: {}, aliases: [], health: [], live: null, seq: 0, usageSort: ["requests", -1] };
let uid = 0;
const nextId = () => `u${++uid}`;

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

// Icons: 24px grid, 1.75 stroke, drawn for this dashboard.
const ICONS = {
  overview: [["rect", { x: 3, y: 3, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 14, y: 3, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 3, y: 14, width: 7, height: 7, rx: 1.5 }], ["rect", { x: 14, y: 14, width: 7, height: 7, rx: 1.5 }]],
  key: [["circle", { cx: 7.5, cy: 15.5, r: 4.5 }], ["path", "M10.7 12.3 20 3"], ["path", "M16 7l3 3"], ["path", "M18.5 4.5 21 7"]],
  health: [["path", "M3 12h4l3 7 4-14 3 7h4"]],
  usage: [["path", "M3 20h18"], ["path", "M6 16v-5"], ["path", "M11 16V6"], ["path", "M16 16v-8"]],
  token: [["path", "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"], ["path", "M9 12l2 2 4-4"]],
  plus: [["path", "M12 5v14"], ["path", "M5 12h14"]],
  search: [["circle", { cx: 11, cy: 11, r: 7 }], ["path", "M20 20l-3.5-3.5"]],
  copy: [["rect", { x: 9, y: 9, width: 11, height: 11, rx: 2 }], ["path", "M5 15V5a2 2 0 0 1 2-2h10"]],
  check: [["path", "M5 12.5l4.5 4.5L19 7"]],
  trash: [["path", "M4 7h16"], ["path", "M9 7V4h6v3"], ["path", "M6 7l1 13h10l1-13"]],
  x: [["path", "M6 6l12 12"], ["path", "M18 6 6 18"]],
  sun: [["circle", { cx: 12, cy: 12, r: 4 }], ["path", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"]],
  moon: [["path", "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"]],
  system: [["rect", { x: 3, y: 4, width: 18, height: 12, rx: 2 }], ["path", "M8 20h8M12 16v4"]],
  logout: [["path", "M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"], ["path", "M10 17l-5-5 5-5"], ["path", "M5 12h11"]],
  refresh: [["path", "M20 11a8 8 0 0 0-14.6-4.5L4 8"], ["path", "M4 3v5h5"], ["path", "M4 13a8 8 0 0 0 14.6 4.5L20 16"], ["path", "M20 21v-5h-5"]],
  alert: [["path", "M12 3 2 20h20z"], ["path", "M12 10v4"], ["path", "M12 17h.01"]],
  eye: [["path", "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"], ["circle", { cx: 12, cy: 12, r: 3 }]],
  eyeOff: [["path", "M3 3l18 18"], ["path", "M10.6 5.1A10.7 10.7 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.7"], ["path", "M6.6 6.6C3.8 8.4 2 12 2 12s3.5 7 10 7c1.9 0 3.5-.5 4.9-1.3"], ["path", "M9.9 9.9a3 3 0 0 0 4.2 4.2"]],
  chevron: [["path", "M9 6l6 6-6 6"]],
  back: [["path", "M15 6l-6 6 6 6"]],
  clock: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", "M12 7v5l3 2"]],
  sort: [["path", "M8 9l4-4 4 4"], ["path", "M8 15l4 4 4-4"]],
};

function icon(name, cls = "") {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `icon ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  for (const [tag, spec] of ICONS[name]) {
    const el = document.createElementNS(NS, tag);
    if (tag === "path") el.setAttribute("d", spec);
    else for (const [k, v] of Object.entries(spec)) el.setAttribute(k, v);
    svg.append(el);
  }
  return svg;
}

const storage = (area) => ({
  get(k) { try { return area().getItem(k); } catch { return null; } },
  set(k, v) { try { area().setItem(k, v); } catch { /* storage blocked */ } },
  del(k) { try { area().removeItem(k); } catch { /* storage blocked */ } },
});
const session = storage(() => sessionStorage);
const local = storage(() => localStorage);

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(method, path, body) {
  const headers = { Authorization: `Bearer ${state.token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Can't reach the MasterAPI server. Check that `masterapi serve` is still running.", 0);
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && path !== "/admin/me") signOut("Your session ended. Sign in again.");
    throw new ApiError(data.error?.message || data.detail?.[0]?.msg || `Request failed (HTTP ${res.status}).`, res.status);
  }
  return data;
}

function toast(message, kind = "ok") {
  const el = h("div", { class: `toast ${kind === "bad" ? "bad" : ""}` }, icon(kind === "bad" ? "alert" : "check", "sm"), h("span", {}, message));
  const remove = () => { el.classList.add("out"); setTimeout(() => el.remove(), 150); };
  el.addEventListener("click", remove);
  $("#toasts").append(el);
  setTimeout(remove, kind === "bad" ? 6000 : 3500);
}

// Disable a button and show a spinner while `fn` runs.
async function busy(button, fn) {
  if (!button) return fn();
  const saved = [...button.childNodes];
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), ...saved.filter((n) => n.nodeType === 3));
  try {
    return await fn();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.replaceChildren(...saved);
  }
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    if (button) {
      button.replaceChildren(icon("check", "sm"));
      setTimeout(() => button.replaceChildren(icon("copy", "sm")), 1400);
    }
    toast("Copied");
  } catch {
    toast("Copy is blocked here. Select the text and press Ctrl+C.", "bad");
  }
}

const fmt = (n) => (n ?? 0).toLocaleString();
const lines = (text) => text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l && !l.startsWith("#"));
const enc = encodeURIComponent;

function duration(seconds) {
  if (seconds <= 0) return "now";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  return seconds % 60 ? `${m}m ${seconds % 60}s` : `${m}m`;
}

function relative(iso) {
  const diff = (new Date(iso) - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(diff) >= size) return rtf.format(Math.round(diff / size), unit);
  }
  return "just now";
}

/* ---------- Form pieces ---------- */

function field({ label, input, hint, error, aside }) {
  const hintId = hint ? nextId() : null;
  const errId = nextId();
  input.id ||= nextId();
  input.setAttribute("aria-describedby", [hintId, errId].filter(Boolean).join(" "));
  const err = h("span", { class: "err", id: errId, role: "alert" }, error || "");
  const labelEl = h("label", { for: input.id }, label);
  const wrap = h("div", { class: "field" }, aside ? h("div", { class: "label-row" }, labelEl, aside) : labelEl, input, hint && h("span", { class: "hint", id: hintId }, hint), err);
  wrap.setError = (msg) => { err.textContent = msg || ""; input.setAttribute("aria-invalid", msg ? "true" : "false"); };
  return wrap;
}

const textInput = (attrs = {}) => h("input", { class: "input", type: "text", autocomplete: "off", spellcheck: "false", ...attrs });

// Keys textarea, masked by default, with a show/hide toggle.
function secretArea(placeholder = "One key per line") {
  const area = h("textarea", { class: "input secret", placeholder, spellcheck: "false", autocomplete: "off", autocapitalize: "off" });
  const toggle = h("button", { type: "button", class: "btn ghost reveal", "aria-pressed": "false" }, icon("eye", "sm"), "Show");
  toggle.addEventListener("click", () => {
    const on = area.classList.toggle("revealed");
    toggle.setAttribute("aria-pressed", String(on));
    toggle.replaceChildren(icon(on ? "eyeOff" : "eye", "sm"), on ? "Hide" : "Show");
  });
  return { area, toggle };
}

function codeBlock(text) {
  const btn = h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Copy code" }, icon("copy", "sm"));
  btn.addEventListener("click", () => copy(text, btn));
  return h("pre", { class: "code" }, h("code", {}, text), btn);
}

function snippetTabs(alias) {
  const origin = location.origin;
  const name = alias?.name || "my-alias";
  const caps = alias?.resolved_capabilities || ["chat"];
  const py = caps.includes("chat") ? `from masterapi import chat\n\nprint(chat("${name}", "Hello!"))`
    : caps.includes("embeddings") ? `from masterapi import embed\n\nvectors = embed("${name}", ["Hello!"])`
      : caps.includes("images") ? `from masterapi import image\n\npictures = image("${name}", "a red fox")`
        : `from masterapi import request\n\nresponse = request("${name}", "GET", "/path")`;
  const tabs = {
    Python: py,
    "OpenAI SDK": `from openai import OpenAI\n\nclient = OpenAI(base_url="${origin}/v1", api_key="<project token>")\nclient.chat.completions.create(\n    model="${name}",\n    messages=[{"role": "user", "content": "Hello!"}],\n)`,
    curl: caps.length
      ? `curl ${origin}/v1/chat/completions \\\n  -H "Authorization: Bearer $MASTERAPI_TOKEN" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model": "${name}", "messages": [{"role": "user", "content": "Hello!"}]}'`
      : `curl ${origin}/proxy/${name}/path \\\n  -H "Authorization: Bearer $MASTERAPI_TOKEN"`,
  };
  const panel = h("div", {});
  const buttons = Object.keys(tabs).map((label) => h("button", { type: "button", role: "tab", "aria-selected": "false" }, label));
  const select = (i) => {
    buttons.forEach((b, j) => b.setAttribute("aria-selected", String(i === j)));
    panel.replaceChildren(codeBlock(tabs[buttons[i].textContent]));
  };
  buttons.forEach((b, i) => b.addEventListener("click", () => select(i)));
  select(0);
  return h("div", {}, h("div", { class: "snippet-tabs", role: "tablist", "aria-label": "Language" }, buttons), panel);
}

/* ---------- Dialogs ---------- */

function openDialog({ title, description, body = [], submit, submitKind = "primary", cancel = "Cancel", wide = false, onSubmit }) {
  const titleId = nextId();
  const errorBox = h("div", { class: "error-box", role: "alert", hidden: true });
  const submitBtn = submit ? h("button", { type: "submit", class: `btn ${submitKind}` }, submit) : null;
  const cancelBtn = h("button", { type: "button", class: "btn" }, cancel);
  const bodyEl = h("div", { class: "dialog-body" }, errorBox, body);
  const footEl = h("div", { class: "dialog-foot" }, cancelBtn, submitBtn);
  const form = h("form", { class: "dialog-form", novalidate: true },
    h("div", { class: "dialog-head" },
      h("div", {}, h("h2", { id: titleId }, title), description && h("p", {}, description)),
      h("button", { type: "button", class: "btn ghost icon-only", "aria-label": "Close" }, icon("x"))),
    bodyEl, footEl);
  const dlg = h("dialog", { class: wide ? "wide" : null, "aria-labelledby": titleId }, form);

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    dlg.classList.add("closing");
    const done = () => { dlg.close(); dlg.remove(); };
    dlg.addEventListener("animationend", done, { once: true });
    setTimeout(done, 200);
  };
  const ctl = {
    dlg, close, body: bodyEl, foot: footEl, submitBtn,
    setError(msg) {
      errorBox.hidden = !msg;
      errorBox.replaceChildren(icon("alert"), h("div", {}, msg || ""));
      if (msg) errorBox.scrollIntoView({ block: "nearest" });
    },
  };
  form.querySelector(".dialog-head button").addEventListener("click", close);
  cancelBtn.addEventListener("click", close);
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!onSubmit) return close();
    ctl.setError("");
    try {
      await busy(submitBtn, () => onSubmit(ctl));
    } catch (err) {
      ctl.setError(err.message);
    }
  });
  document.body.append(dlg);
  dlg.showModal();
  (bodyEl.querySelector("input, select, textarea") || submitBtn || cancelBtn).focus();
  return ctl;
}

function confirmDialog({ title, message, confirm, danger = true, requireText }) {
  return new Promise((resolve) => {
    let result = false;
    const input = requireText ? textInput({ autocomplete: "off" }) : null;
    const ctl = openDialog({
      title, submit: confirm, submitKind: danger ? "danger solid" : "primary",
      body: [h("p", { class: "muted" }, message),
        input && field({ label: h("span", {}, "Type ", h("code", {}, requireText), " to confirm"), input })],
      onSubmit: async (c) => { result = true; c.close(); },
    });
    if (input) {
      ctl.submitBtn.disabled = true;
      input.addEventListener("input", () => { ctl.submitBtn.disabled = input.value.trim() !== requireText; });
    }
    ctl.dlg.addEventListener("close", () => resolve(result), { once: true });
  });
}

/* ---------- Theme ---------- */

function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  local.set("masterapi.theme", mode);
  for (const b of document.querySelectorAll("[data-theme-mode]")) b.setAttribute("aria-pressed", String(b.dataset.themeMode === mode));
}

function themeSwitch() {
  const current = local.get("masterapi.theme") || "system";
  const modes = [["system", "system", "Match system"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]];
  return h("div", { class: "theme-switch", role: "group", "aria-label": "Theme" },
    modes.map(([mode, ic, label]) => h("button", {
      type: "button", "data-theme-mode": mode, "aria-pressed": String(mode === current), "aria-label": label, title: label,
      onclick: () => applyTheme(mode),
    }, icon(ic, "sm"))));
}

/* ---------- Sign in ---------- */

function showLogin(message = "") {
  stopLive();
  const input = h("input", { class: "input", type: "password", name: "token", autocomplete: "current-password", spellcheck: "false", required: true, placeholder: "mapi-…" });
  const tokenField = field({ label: "Admin token", input, hint: "masterapi serve prints one on first start. You can also run masterapi token create admin --admin.", error: message });
  if (message) input.setAttribute("aria-invalid", "true");
  const submit = h("button", { type: "submit", class: "btn primary" }, "Sign in");
  const form = h("form", { class: "login-card", novalidate: true },
    h("div", { class: "brand" }, h("span", { class: "ring", "aria-hidden": "true" }), "MasterAPI"),
    h("h1", {}, "Sign in"),
    h("p", {}, "Manage the API keys your projects call by name."),
    tokenField, submit);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value) return tokenField.setError("Paste your admin token.");
    state.token = value;
    try {
      await busy(submit, async () => { state.me = await api("GET", "/admin/me"); });
      session.set("masterapi.token", value);
      await start();
    } catch (err) {
      state.token = null;
      tokenField.setError(err.status === 401 ? "That token isn't valid." : err.status === 403 ? "That is a project token. Use an admin token." : err.message);
      input.focus();
    }
  });
  $("#root").replaceChildren(h("main", { class: "login" }, form));
  input.focus();
}

function signOut(message = "") {
  session.del("masterapi.token");
  state.token = null;
  state.me = null;
  showLogin(message);
}

/* ---------- Shell and routing ---------- */

const ROUTES = [
  ["overview", "Overview", "overview"],
  ["keys", "Keys", "key"],
  ["health", "Health", "health"],
  ["usage", "Usage", "usage"],
  ["tokens", "Tokens", "token"],
];

function parseHash() {
  const [view, ...rest] = location.hash.replace(/^#\/?/, "").split("/");
  return { view: ROUTES.some(([r]) => r === view) ? view : "overview", param: rest.length ? decodeURIComponent(rest.join("/")) : null };
}

function buildShell() {
  const navLinks = (cls) => ROUTES.map(([route, label, ic]) => h("a", { href: `#/${route}`, "data-route": route },
    icon(ic), h("span", {}, label), cls === "nav" && h("span", { class: "count", "data-count": route })));
  const signOutBtn = (cls) => h("button", { type: "button", class: `btn ghost ${cls}`, onclick: () => signOut() }, icon("logout", "sm"), h("span", { class: cls === "icon-only" ? "sr-only" : "" }, "Sign out"));
  $("#root").replaceChildren(h("div", { class: "shell" },
    h("aside", { class: "sidebar" },
      h("div", { class: "brand" }, h("span", { class: "ring", "aria-hidden": "true" }), "MasterAPI"),
      h("nav", { class: "nav", "aria-label": "Main" }, navLinks("nav")),
      h("div", { class: "sidebar-foot" },
        themeSwitch(),
        h("p", { class: "signed-in" }, "Signed in as ", h("strong", {}, state.me?.name || "admin")),
        signOutBtn(""))),
    h("div", { class: "main" },
      h("header", { class: "mobile-bar" },
        h("div", { class: "brand" }, h("span", { class: "ring", "aria-hidden": "true" }), "MasterAPI"),
        h("div", { class: "row" }, themeSwitch(), signOutBtn("icon-only"))),
      h("main", { id: "view", tabindex: "-1" })),
    h("nav", { class: "tabbar", "aria-label": "Main" }, navLinks("tabbar"))));
}

function updateNav(view) {
  for (const a of document.querySelectorAll("[data-route]")) {
    if (a.dataset.route === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const rejected = state.health.filter((k) => k.status === "invalid").length;
  const counts = { keys: [state.aliases.length, false], health: [rejected || "", rejected > 0] };
  for (const el of document.querySelectorAll("[data-count]")) {
    const [value, alert] = counts[el.dataset.count] || ["", false];
    el.textContent = value;
    el.classList.toggle("alert", alert);
    el.title = alert ? `${rejected} rejected ${rejected === 1 ? "key" : "keys"}` : "";
  }
}

async function loadCore() {
  [state.aliases, state.health] = await Promise.all([api("GET", "/admin/aliases"), api("GET", "/admin/keys")]);
}

function skeleton() {
  return [h("div", { class: "page-head" }, h("div", { class: "skeleton sk-line" }, "")),
    h("div", { class: "page-body" }, h("div", { class: "stats" }, [1, 2, 3, 4].map(() => h("div", { class: "card skeleton sk-block" }))),
      h("div", { class: "card skeleton sk-block section-gap" }))];
}

async function route({ quiet = false } = {}) {
  if (!state.token) return;
  const seq = ++state.seq;
  const { view, param } = parseHash();
  stopLive();
  updateNav(view);
  const target = $("#view");
  if (!quiet) target.replaceChildren(...skeleton());
  try {
    await loadCore();
    const nodes = await VIEWS[view](param);
    if (seq !== state.seq) return;
    updateNav(view);
    target.replaceChildren(...nodes);
    if (!quiet) {
      target.classList.remove("view-enter");
      void target.offsetWidth;
      target.classList.add("view-enter");
    }
    document.title = `${ROUTES.find(([r]) => r === view)[1]} · MasterAPI`;
  } catch (err) {
    if (seq !== state.seq || !state.token) return;
    target.replaceChildren(pageHead("Something went wrong"), h("div", { class: "page-body" },
      h("div", { class: "error-box", role: "alert" }, icon("alert"),
        h("div", {}, h("p", {}, err.message), h("div", { class: "row" }, h("button", { class: "btn", onclick: () => route() }, icon("refresh", "sm"), "Try again"))))));
  }
}

const refresh = () => route({ quiet: true });

function pageHead(title, sub, ...actions) {
  return h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, title), sub && h("p", { class: "sub" }, sub)),
    actions.length ? h("div", { class: "row" }, actions) : null);
}

function emptyState(ic, title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "art" }, icon(ic)), h("h2", {}, title), h("p", {}, text), action);
}

/* ---------- Shared alias helpers ---------- */

function keyHealth(alias, fingerprint) {
  return state.health.find((k) => k.alias === alias && k.fingerprint === fingerprint);
}

function keyStatus(health) {
  if (!health || health.status === "ready") return { kind: "ready", label: "Ready", badge: "ok" };
  if (health.status === "invalid") return { kind: "rejected", label: `Rejected, retry in ${duration(health.cooldown_seconds)}`, badge: "bad" };
  return { kind: "resting", label: `Resting ${duration(health.cooldown_seconds)}`, badge: "warn" };
}

function aliasStatus(alias) {
  if (!alias.keys.length) return "idle";
  const kinds = alias.keys.map((k) => keyStatus(keyHealth(alias.name, k.fingerprint)).kind);
  if (kinds.every((k) => k === "rejected")) return "bad";
  if (kinds.some((k) => k !== "ready")) return "warn";
  return "ok";
}

const statusText = { ok: "All keys ready", warn: "Some keys resting or rejected", bad: "All keys rejected", idle: "No key needed" };

function capabilityChips(alias) {
  const caps = alias.resolved_capabilities;
  if (!caps.length) return [h("span", { class: "chip" }, "Raw requests only")];
  return OPS.filter((op) => caps.includes(op)).map((op) => h("span", { class: "chip on" }, icon("check", "sm"), OP_LABEL[op]));
}

function newAliasButton(label = "New alias") {
  return h("button", { type: "button", class: "btn primary", onclick: newAliasDialog }, icon("plus", "sm"), label);
}

/* ---------- Overview ---------- */

async function viewOverview() {
  const usage = await api("GET", "/admin/usage");
  const keys = state.aliases.reduce((n, a) => n + a.keys.length, 0);
  const statuses = state.health.map((k) => keyStatus(k).kind);
  const rejected = statuses.filter((s) => s === "rejected").length;
  const resting = statuses.filter((s) => s === "resting").length;
  const requests = usage.reduce((n, r) => n + r.requests, 0);
  const errors = usage.reduce((n, r) => n + r.errors, 0);
  const tokens = usage.reduce((n, r) => n + r.prompt_tokens + r.completion_tokens, 0);

  const stat = (ic, label, value, note, attention = false) =>
    h("div", { class: `card stat ${attention ? "attention" : ""}` }, h("div", { class: "label" }, icon(ic, "sm"), label), h("div", { class: "value" }, value), h("div", { class: "note" }, note));

  const aliasesCard = state.aliases.length
    ? h("div", { class: "card card-pad" },
      h("div", { class: "section-head" }, h("h2", {}, "Aliases"), h("a", { href: "#/keys", class: "small" }, "Manage keys")),
      h("div", { class: "alias-mini" }, state.aliases.slice(0, 6).map((a) => {
        const st = aliasStatus(a);
        return h("a", { href: `#/keys/${enc(a.name)}` },
          h("div", {}, h("div", { class: "name" }, a.name), h("div", { class: "muted small" }, `${a.provider}, ${a.keys.length} ${a.keys.length === 1 ? "key" : "keys"}`)),
          h("span", { class: `dot ${st}`, title: statusText[st] }, h("span", { class: "sr-only" }, statusText[st])));
      })))
    : h("div", { class: "card" }, emptyState("key", "Store your first key", "Give a set of keys one name. Your projects call that name and never see the keys.", newAliasButton("Add a key")));

  return [
    pageHead("Overview", "Everything your projects can call, in one place.", newAliasButton()),
    h("div", { class: "page-body" },
      h("div", { class: "stats" },
        stat("key", "Aliases", fmt(state.aliases.length), `${fmt(keys)} ${keys === 1 ? "key" : "keys"} stored`),
        stat("health", "Keys ready", `${fmt(keys - rejected - resting)} / ${fmt(keys)}`,
          rejected || resting ? `${rejected} rejected, ${resting} resting` : "No problems", rejected > 0),
        stat("usage", "Requests", fmt(requests), errors ? `${fmt(errors)} failed` : "Since the server started"),
        stat("token", "Model tokens", fmt(tokens), "Prompt and output, since start")),
      h("div", { class: "overview-grid" },
        h("div", { class: "card card-pad" },
          h("div", { class: "section-head" }, h("div", {}, h("h2", {}, "Call your keys"), h("p", {}, "Use an alias name wherever a model name goes."))),
          snippetTabs(state.aliases[0])),
        aliasesCard)),
  ];
}

/* ---------- Keys ---------- */

async function viewKeys(param) {
  const wide = $("#view").clientWidth - 64 > 720;  // matches the split container query
  if (!param && wide && state.aliases.length) {
    history.replaceState(null, "", `#/keys/${enc(state.aliases[0].name)}`);
    param = state.aliases[0].name;
  }
  const head = pageHead("Keys", "Each alias holds one or more keys for a provider.", newAliasButton());
  if (!state.aliases.length) {
    return [head, h("div", { class: "page-body" }, h("div", { class: "card" },
      emptyState("key", "No keys yet", "Add an alias, paste one key or many, and call it by name from any project.", newAliasButton("Add a key"))))];
  }

  const search = textInput({ type: "search", placeholder: "Search aliases", "aria-label": "Search aliases" });
  const list = h("div", { class: "alias-list", role: "list" });
  const renderList = () => {
    const q = search.value.trim().toLowerCase();
    const items = state.aliases.filter((a) => !q || a.name.toLowerCase().includes(q) || a.provider.toLowerCase().includes(q));
    list.replaceChildren(...(items.length ? items.map((a) => {
      const st = aliasStatus(a);
      return h("a", { class: "alias-item", role: "listitem", href: `#/keys/${enc(a.name)}`, "aria-current": a.name === param ? "page" : null },
        h("span", { class: "name" }, a.name), h("span", { class: `dot ${st}`, title: statusText[st] }, h("span", { class: "sr-only" }, statusText[st])),
        h("span", { class: "meta" }, `${a.provider}, ${a.keys.length} ${a.keys.length === 1 ? "key" : "keys"}`));
    }) : [h("p", { class: "empty-list" }, `No alias matches "${search.value}".`)]));
  };
  search.addEventListener("input", renderList);
  search.addEventListener("keydown", (e) => { if (e.key === "Escape") { search.value = ""; renderList(); } });
  renderList();

  const current = state.aliases.find((a) => a.name === param);
  const detail = current ? aliasDetail(current)
    : param ? h("div", { class: "card" }, emptyState("alert", "Alias not found", `There is no alias named "${param}". It may have been deleted.`, h("a", { class: "btn", href: "#/keys" }, "Back to keys")))
      : null;

  return [head, h("div", { class: "page-body" },
    h("div", { class: "split", "data-mode": detail ? "detail" : "list" },
      h("div", { class: "list-panel" },
        h("div", { class: "search" }, icon("search", "sm"), search, h("kbd", { "aria-hidden": "true" }, "/")),
        list),
      h("div", { class: "detail-panel" }, detail)))];
}

function aliasDetail(a) {
  const base = `/admin/aliases/${enc(a.name)}`;
  const provider = state.providers[a.provider] || {};
  const caps = a.resolved_capabilities;
  const st = aliasStatus(a);

  // Keys
  const tags = a.keys.length
    ? h("div", { class: "tags" }, a.keys.map((k) => {
      const s = keyStatus(keyHealth(a.name, k.fingerprint));
      const tag = h("span", { class: "tag", "data-state": s.kind },
        h("span", { class: "k" }, k.key),
        h("span", { class: "state" }, s.kind !== "ready" && icon(s.kind === "rejected" ? "alert" : "clock", "sm"), s.label));
      const remove = h("button", { type: "button", class: "remove", "aria-label": `Remove key ending ${k.key.slice(3)}`, title: "Remove key" }, icon("x", "sm"));
      remove.addEventListener("click", async () => {
        const ok = await confirmDialog({ title: "Remove this key?", message: `Key ${k.key} will be deleted from "${a.name}". Calls keep working with the other keys.`, confirm: "Remove key" });
        if (!ok) return;
        tag.classList.add("leaving");
        try {
          await api("DELETE", `${base}/keys/${k.fingerprint}`);
          toast(`Removed key ${k.key}`);
        } catch (err) {
          toast(err.message, "bad");
        }
        refresh();
      });
      tag.append(remove);
      return tag;
    }))
    : h("p", { class: "muted small" }, "This provider needs no key.");

  // Models
  const modelInputs = Object.fromEntries(OPS.filter((op) => caps.includes(op)).map((op) => [op, textInput({ value: a.models?.[op] || "", placeholder: "model id" })]));
  const saveModels = h("button", { type: "submit", class: "btn", disabled: true }, "Save models");
  const modelsForm = h("form", { novalidate: true },
    h("div", { class: "grid c3" }, Object.entries(modelInputs).map(([op, input]) => field({ label: `${OP_LABEL[op]} model`, input }))),
    h("div", { class: "row end" }, saveModels));
  modelsForm.addEventListener("input", () => { saveModels.disabled = Object.entries(modelInputs).every(([op, i]) => i.value.trim() === (a.models?.[op] || "")); });
  modelsForm.addEventListener("submit", (e) => {
    e.preventDefault();
    busy(saveModels, async () => {
      await api("PATCH", base, { models: Object.fromEntries(Object.entries(modelInputs).map(([op, i]) => [op, i.value.trim()])) });
      toast("Models saved");
      refresh();
    }).catch((err) => toast(err.message, "bad"));
  });

  // Connection
  const baseUrl = textInput({ value: a.base_url || "", placeholder: provider.base_url || "https://…", inputmode: "url" });
  const auth = textInput({ value: a.auth || "", placeholder: provider.auth || "bearer" });
  const saveConn = h("button", { type: "submit", class: "btn", disabled: true }, "Save connection");
  const connForm = h("form", { novalidate: true },
    h("div", { class: "grid c2" },
      field({ label: "Base URL", input: baseUrl, hint: "Empty uses the provider default." }),
      field({ label: "Key placement", input: auth, hint: "bearer, header:NAME, query:NAME or none." })),
    h("div", { class: "row end" }, saveConn));
  connForm.addEventListener("input", () => { saveConn.disabled = baseUrl.value.trim() === (a.base_url || "") && auth.value.trim() === (a.auth || ""); });
  connForm.addEventListener("submit", (e) => {
    e.preventDefault();
    busy(saveConn, async () => {
      await api("PATCH", base, { base_url: baseUrl.value.trim(), auth: auth.value.trim() });
      toast("Connection saved");
      refresh();
    }).catch((err) => toast(err.message, "bad"));
  });

  const remove = h("button", { type: "button", class: "btn danger" }, icon("trash", "sm"), "Delete alias");
  remove.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: `Delete "${a.name}"?`, confirm: "Delete alias", requireText: a.name,
      message: `This deletes the alias and its ${a.keys.length} ${a.keys.length === 1 ? "key" : "keys"} from the vault. Projects calling "${a.name}" will get errors. This can't be undone.`,
    });
    if (!ok) return;
    try {
      await api("DELETE", base);
      toast(`Deleted "${a.name}"`);
      location.hash = "#/keys";
    } catch (err) {
      toast(err.message, "bad");
    }
  });

  return h("article", { class: "card card-pad", "aria-labelledby": "alias-title" },
    h("a", { href: "#/keys", class: "btn ghost back" }, icon("back", "sm"), "All aliases"),
    h("div", { class: "detail-head" },
      h("div", {},
        h("h2", { id: "alias-title" }, a.name),
        h("div", { class: "chips" }, h("span", { class: "chip" }, a.provider), capabilityChips(a),
          h("span", { class: `badge ${{ ok: "ok", warn: "warn", bad: "bad", idle: "neutral" }[st]}` }, statusText[st]))),
      remove),
    h("section", { class: "section" },
      h("div", { class: "section-head" },
        h("div", {}, h("h3", {}, "Keys"), h("p", {}, "Calls take turns across these keys. A rate-limited key rests; a rejected key is skipped for 10 minutes.")),
        a.keys.length || provider.auth !== "none" ? h("button", { type: "button", class: "btn", onclick: () => addKeysDialog(a) }, icon("plus", "sm"), "Add keys") : null),
      tags),
    Object.keys(modelInputs).length ? h("section", { class: "section" },
      h("div", { class: "section-head" }, h("div", {}, h("h3", {}, "Default models"), h("p", {}, `Used when a project calls "${a.name}" without ":model".`))),
      modelsForm) : null,
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("div", {}, h("h3", {}, "Connection"), h("p", {}, "Override where requests go and how the key is sent."))),
      connForm),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("div", {}, h("h3", {}, "Use it"), h("p", {}, "Copy into any project.")))
      , snippetTabs(a)));
}

function addKeysDialog(a) {
  const { area, toggle } = secretArea();
  const keysField = field({ label: "Keys", input: area, aside: toggle, hint: "Paste one key per line. Duplicates are skipped." });
  openDialog({
    title: `Add keys to "${a.name}"`, submit: "Add keys",
    body: [keysField],
    onSubmit: async (ctl) => {
      const keys = lines(area.value);
      if (!keys.length) { keysField.setError("Paste at least one key."); area.focus(); return; }
      const r = await api("POST", `/admin/aliases/${enc(a.name)}/keys`, { keys });
      ctl.close();
      toast(r.added ? `Added ${r.added} ${r.added === 1 ? "key" : "keys"}` : "Those keys were already stored");
      refresh();
    },
  });
}

function newAliasDialog() {
  const providers = Object.keys(state.providers);
  const name = textInput({ placeholder: "my-gemini", maxlength: 64, autocapitalize: "off" });
  const provider = h("select", { class: "input" }, providers.map((p) => h("option", { value: p }, p)), h("option", { value: "custom" }, "custom (any API)"));
  const capsNote = h("span", {});
  const { area, toggle } = secretArea();
  const models = Object.fromEntries(OPS.map((op) => [op, textInput({ placeholder: "model id" })]));
  const modelFields = Object.fromEntries(OPS.map((op) => [op, field({ label: `${OP_LABEL[op]} model`, input: models[op] })]));
  const baseUrl = textInput({ inputmode: "url" });
  const auth = textInput({});
  const adapter = h("select", { class: "input" }, h("option", { value: "" }, "Provider default"),
    h("option", { value: "openai" }, "OpenAI-compatible"), h("option", { value: "anthropic" }, "Anthropic"), h("option", { value: "http" }, "Raw HTTP only"));
  const capBoxes = Object.fromEntries(OPS.map((op) => [op, h("input", { type: "checkbox" })]));

  const nameField = field({ label: "Name", input: name, hint: "Projects use this name. Letters, digits, dot, dash, underscore." });
  const providerField = field({ label: "Provider", input: provider, hint: capsNote });
  const keysField = field({ label: "Keys", input: area, aside: toggle, hint: "One key per line. Several keys spread the load." });
  const keysBlock = keysField;
  const baseField = field({ label: "Base URL", input: baseUrl });

  const currentCaps = () => {
    const p = state.providers[provider.value];
    const chosen = OPS.filter((op) => capBoxes[op].checked);
    return chosen.length || !p ? chosen : p.capabilities;
  };
  const syncModels = () => { for (const op of OPS) modelFields[op].hidden = !currentCaps().includes(op); };
  const syncProvider = () => {
    const p = state.providers[provider.value] || { base_url: "", auth: "bearer", capabilities: ["chat"] };
    capsNote.textContent = p.capabilities.length ? `Supports ${p.capabilities.map((c) => OP_LABEL[c].toLowerCase()).join(", ")}.` : "Raw requests only, through /proxy or request().";
    baseUrl.placeholder = p.base_url || "https://api.example.com/v1";
    auth.placeholder = p.auth;
    keysBlock.hidden = p.auth === "none";
    for (const op of OPS) capBoxes[op].checked = p.capabilities.includes(op);
    advanced.open = provider.value === "custom" || advanced.open;
    syncModels();
  };
  const advanced = h("details", { class: "more" },
    h("summary", {}, icon("chevron", "sm"), "Connection settings"),
    h("div", { class: "grid c2" },
      baseField,
      field({ label: "Key placement", input: auth, hint: "bearer, header:x-api-key, header:Authorization=Token {key}, query:key or none" }),
      field({ label: "Request format", input: adapter }),
      h("div", { class: "field" }, h("span", { class: "label" }, "Supports"),
        h("div", { class: "row" }, OPS.map((op) => h("label", { class: "check" }, capBoxes[op], OP_LABEL[op]))))));
  provider.addEventListener("change", syncProvider);
  for (const box of Object.values(capBoxes)) box.addEventListener("change", syncModels);
  syncProvider();

  openDialog({
    title: "New alias", description: "Store keys under a name your projects can call.", submit: "Save alias", wide: true,
    body: [h("div", { class: "grid c2" }, nameField, providerField), keysBlock,
      h("div", { class: "grid c3" }, OPS.map((op) => modelFields[op])), advanced],
    onSubmit: async (ctl) => {
      const n = name.value.trim();
      nameField.setError(/^[A-Za-z0-9_.-]{1,64}$/.test(n) ? "" : "Use 1 to 64 letters, digits, dots, dashes or underscores.");
      const p = state.providers[provider.value];
      const keys = lines(area.value);
      keysField.setError(!keysBlock.hidden && !keys.length ? "Paste at least one key." : "");
      baseField.setError(provider.value === "custom" && !baseUrl.value.trim() ? "Custom providers need a base URL." : "");
      const invalid = ctl.body.querySelector('[aria-invalid="true"]');
      if (invalid) { if (invalid.closest("details")) advanced.open = true; invalid.focus(); return; }
      const caps = OPS.filter((op) => capBoxes[op].checked);
      await api("POST", "/admin/aliases", {
        name: n, provider: provider.value, keys,
        models: Object.fromEntries(OPS.filter((op) => !modelFields[op].hidden).map((op) => [op, models[op].value.trim()])),
        base_url: baseUrl.value.trim() || null, auth: auth.value.trim() || null, adapter: adapter.value || null,
        capabilities: p && caps.join() === p.capabilities.join() ? null : caps,
      });
      ctl.close();
      toast(`Saved "${n}"`);
      if (location.hash === `#/keys/${enc(n)}`) refresh();
      else location.hash = `#/keys/${enc(n)}`;
    },
  });
}

/* ---------- Health ---------- */

function stopLive() {
  clearInterval(state.live);
  state.live = null;
}

async function viewHealth() {
  const onlyProblems = h("input", { type: "checkbox", checked: local.get("masterapi.healthProblems") === "1" });
  const live = h("input", { type: "checkbox", checked: local.get("masterapi.healthLive") !== "0" });
  const body = h("div", {});

  const draw = () => {
    const rows = state.health.filter((k) => !onlyProblems.checked || k.status !== "ready");
    if (!state.health.length) {
      body.replaceChildren(emptyState("health", "No calls yet", "Key health appears after the first request through this server. Rate-limited keys rest, then return to rotation."));
      return;
    }
    if (!rows.length) {
      body.replaceChildren(emptyState("check", "All keys are ready", "No key is resting or rejected right now."));
      return;
    }
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Status"), h("th", {}, "Alias"), h("th", {}, "Key"), h("th", { class: "num" }, "Requests"),
        h("th", { class: "num" }, "Errors"), h("th", { class: "num hide-sm" }, "Error rate"), h("th", { class: "hide-sm" }, "Last error"))),
      h("tbody", {}, rows.map((k) => {
        const s = keyStatus(k);
        return h("tr", {},
          h("td", {}, h("span", { class: `badge ${s.badge}` }, icon(s.kind === "ready" ? "check" : s.kind === "rejected" ? "alert" : "clock", "sm"), s.label)),
          h("td", {}, h("a", { href: `#/keys/${enc(k.alias)}` }, k.alias)),
          h("td", {}, h("code", {}, k.key)),
          h("td", { class: "num" }, fmt(k.requests)),
          h("td", { class: "num" }, fmt(k.errors)),
          h("td", { class: "num hide-sm" }, k.requests ? `${Math.round((k.errors / k.requests) * 100)}%` : "–"),
          h("td", { class: "hide-sm muted" }, k.last_error || ""));
      })))));
  };

  const poll = async () => {
    try {
      state.health = await api("GET", "/admin/keys");
      updateNav("health");
      draw();
    } catch { /* keep the last data; the next tick retries */ }
  };
  const setLive = () => {
    stopLive();
    local.set("masterapi.healthLive", live.checked ? "1" : "0");
    if (live.checked) state.live = setInterval(poll, 5000);
  };
  live.addEventListener("change", setLive);
  onlyProblems.addEventListener("change", () => { local.set("masterapi.healthProblems", onlyProblems.checked ? "1" : "0"); draw(); });
  const refreshBtn = h("button", { type: "button", class: "btn" }, icon("refresh", "sm"), "Refresh");
  refreshBtn.addEventListener("click", () => busy(refreshBtn, poll));
  draw();
  setLive();

  return [
    pageHead("Health", "How each key is doing since the server started.", refreshBtn),
    h("div", { class: "page-body" }, h("div", { class: "card" },
      h("div", { class: "toolbar" },
        h("label", { class: "check" }, onlyProblems, "Only show problems"),
        h("label", { class: "check live" }, live, h("span", { class: "pulse", "aria-hidden": "true" }), "Update every 5 seconds")),
      body)),
  ];
}

/* ---------- Usage ---------- */

async function viewUsage() {
  const rows = await api("GET", "/admin/usage");
  const total = (k) => rows.reduce((n, r) => n + r[k], 0);
  const body = h("div", {});
  const cols = [["token", "Token"], ["alias", "Alias"], ["op", "Operation"], ["requests", "Requests", true], ["errors", "Errors", true],
    ["prompt_tokens", "Prompt tokens", true], ["completion_tokens", "Output tokens", true]];

  const draw = () => {
    const [key, dir] = state.usageSort;
    const sorted = [...rows].sort((a, b) => (a[key] > b[key] ? 1 : a[key] < b[key] ? -1 : 0) * dir);
    const max = Math.max(1, ...rows.map((r) => r.requests));
    body.replaceChildren(h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, cols.map(([k, label, num]) => {
        const btn = h("button", { type: "button" }, label, icon("sort", "sm"));
        btn.addEventListener("click", () => { state.usageSort = [k, state.usageSort[0] === k ? -state.usageSort[1] : num ? -1 : 1]; draw(); });
        return h("th", { class: num ? "num" : null, "aria-sort": key === k ? (dir > 0 ? "ascending" : "descending") : "none" }, btn);
      }), h("th", { class: "hide-sm" }, h("span", { class: "sr-only" }, "Share of requests")))),
      h("tbody", {}, sorted.map((r) => {
        const fill = h("span", {});
        fill.style.transform = `scaleX(${r.requests / max})`;
        return h("tr", {},
          h("td", {}, r.token), h("td", {}, h("a", { href: `#/keys/${enc(r.alias)}` }, r.alias)), h("td", {}, r.op),
          h("td", { class: "num" }, fmt(r.requests)), h("td", { class: "num" }, r.errors ? h("span", { class: "badge bad" }, fmt(r.errors)) : "0"),
          h("td", { class: "num" }, fmt(r.prompt_tokens)), h("td", { class: "num" }, fmt(r.completion_tokens)),
          h("td", { class: "hide-sm" }, h("div", { class: "bar", "aria-hidden": "true" }, fill)));
      })))));
  };
  if (rows.length) draw();

  const stat = (label, value) => h("div", { class: "card stat" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value));
  return [
    pageHead("Usage", "Requests through this server since it started, per project token."),
    h("div", { class: "page-body" },
      h("div", { class: "stats" }, stat("Requests", fmt(total("requests"))), stat("Failed", fmt(total("errors"))),
        stat("Prompt tokens", fmt(total("prompt_tokens"))), stat("Output tokens", fmt(total("completion_tokens")))),
      h("div", { class: "card" }, rows.length ? body
        : emptyState("usage", "No requests yet", "Point a project at this server with a project token. Its calls show up here."))),
  ];
}

/* ---------- Tokens ---------- */

function createTokenDialog() {
  const name = textInput({ placeholder: "my-project", maxlength: 64 });
  const nameField = field({ label: "Name", input: name, hint: "Usually the project that will use it." });
  const aliasBoxes = state.aliases.map((a) => [a.name, h("input", { type: "checkbox", value: a.name })]);
  const admin = h("input", { type: "checkbox" });
  const ctl = openDialog({
    title: "Create a token", description: "One token per project lets you revoke a project without touching the others.", submit: "Create token",
    body: [nameField,
      h("fieldset", { class: "field" },
        h("legend", { class: "label" }, "Aliases it can use"),
        h("span", { class: "hint" }, "Leave all unchecked to allow every alias."),
        aliasBoxes.length ? h("div", { class: "row" }, aliasBoxes.map(([n, box]) => h("label", { class: "check" }, box, n))) : h("span", { class: "hint" }, "No aliases yet.")),
      h("label", { class: "check" }, admin, "Can manage keys and tokens (admin)")],
    onSubmit: async (c) => {
      const n = name.value.trim();
      nameField.setError(/^[A-Za-z0-9_.-]{1,64}$/.test(n) ? "" : "Use 1 to 64 letters, digits, dots, dashes or underscores.");
      if (name.getAttribute("aria-invalid") === "true") { name.focus(); return; }
      const aliases = aliasBoxes.filter(([, b]) => b.checked).map(([n2]) => n2);
      const r = await api("POST", "/admin/tokens", { name: n, aliases, admin: admin.checked });
      const copyBtn = h("button", { type: "button", class: "btn primary" }, icon("copy", "sm"), "Copy token");
      copyBtn.addEventListener("click", () => copy(r.token));
      c.body.replaceChildren(h("div", { class: "secret-box" },
        h("div", { class: "warnline" }, icon("alert", "sm"), "Copy this token now. It won't be shown again."),
        h("code", {}, r.token), h("div", {}, copyBtn)),
      h("p", { class: "muted small" }, "Use it as the API key in your project: ", h("code", {}, "Authorization: Bearer <token>"), "."));
      c.foot.replaceChildren(h("button", { type: "button", class: "btn", onclick: c.close }, "Done"));
      copyBtn.focus();
      refresh();
    },
  });
  return ctl;
}

async function viewTokens() {
  const tokens = await api("GET", "/admin/tokens");
  const createBtn = h("button", { type: "button", class: "btn primary", onclick: createTokenDialog }, icon("plus", "sm"), "Create token");
  const table = h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "Access"), h("th", {}, "Aliases"), h("th", { class: "hide-sm" }, "Created"), h("th", {}, h("span", { class: "sr-only" }, "Actions")))),
    h("tbody", {}, tokens.map((t) => {
      const self = t.name === state.me?.name;
      const revoke = h("button", { type: "button", class: "btn danger", disabled: self, title: self ? "You are signed in with this token" : null }, "Revoke");
      revoke.addEventListener("click", async () => {
        const ok = await confirmDialog({ title: `Revoke "${t.name}"?`, message: "Anything using this token stops working right away. This can't be undone.", confirm: "Revoke token" });
        if (!ok) return;
        try {
          await api("DELETE", `/admin/tokens/${enc(t.name)}`);
          toast(`Revoked "${t.name}"`);
          refresh();
        } catch (err) {
          toast(err.message, "bad");
        }
      });
      return h("tr", {},
        h("td", {}, h("strong", {}, t.name), self && h("span", { class: "muted small" }, " (you)")),
        h("td", {}, h("span", { class: `badge ${t.admin ? "warn" : "neutral"}` }, t.admin ? "Admin" : "Project")),
        h("td", {}, t.aliases ? t.aliases.join(", ") : h("span", { class: "muted" }, "All")),
        h("td", { class: "hide-sm muted", title: new Date(t.created).toLocaleString() }, relative(t.created)),
        h("td", { class: "num" }, revoke));
    }))));
  return [
    pageHead("Tokens", "Projects use a token to call your aliases. They never see the keys.", createBtn),
    h("div", { class: "page-body" }, h("div", { class: "card" }, tokens.length ? table : emptyState("token", "No tokens", "Create a token for each project that calls this server.", createBtn))),
  ];
}

const VIEWS = { overview: viewOverview, keys: viewKeys, health: viewHealth, usage: viewUsage, tokens: viewTokens };

/* ---------- Boot ---------- */

async function start() {
  state.providers = await api("GET", "/admin/providers");
  buildShell();
  await route();
}

window.addEventListener("hashchange", async () => {
  if (!state.token) return;
  await route();
  $("#view")?.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
});

document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.querySelector("dialog[open]");
  if (e.key === "/" && !typing) {
    const search = $(".search input");
    if (search) { e.preventDefault(); search.focus(); }
  }
});

applyTheme(local.get("masterapi.theme") || "system");
state.token = session.get("masterapi.token");
if (state.token) {
  api("GET", "/admin/me").then((me) => { state.me = me; return start(); }).catch(() => signOut());
} else {
  showLogin();
}
