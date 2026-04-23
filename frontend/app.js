// Minimal API client + shared helpers. No framework, no build step.

const API = "/api";

export async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json", "X-User-Id": "default" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return null;
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export function fmtDate(s) {
  if (!s) return "";
  const d = new Date(s);
  return d.toLocaleString("en-SG", { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtDateOnly(s) {
  if (!s) return "";
  return new Date(s).toLocaleDateString("en-SG");
}

export function daysUntil(s) {
  if (!s) return null;
  return Math.ceil((new Date(s) - new Date()) / (1000 * 60 * 60 * 24));
}

export function statusPill(s) {
  return `<span class="status-pill status-${s}">${s}</span>`;
}

export function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== null && v !== undefined && v !== "") p.append(k, v); });
  return p.toString() ? "?" + p.toString() : "";
}
