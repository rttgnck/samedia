// The NAS side of the updater: nasOS itself (OTA packages built from a nasOS checkout) and the
// Samedia server app on it (updated through the nasOS App Store, from the image CI publishes).
//
// Whether nasOS is out of sync: OTA builds made here carry a short fingerprint of the nasOS
// source in their version ("102026-153000-ga1b2c3", like git describe), which the NAS reports without a login
// (/api/system/health). A different fingerprint, or a build without one, needs an update.
//
// Installing needs a nasOS login: asked once in the terminal (remember me), only the token is
// kept, in the updater's own config file (~/.config/samedia/updater.json, readable by you only).

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import { ROOT, run } from "./release.mjs";

/** Where the nasOS checkout is: NASOS_REPO, the config, or a "nasOS" folder next to this repo. */
export function nasosRepo(cfg) {
  const candidates = [process.env.NASOS_REPO, cfg.nasos && cfg.nasos.repo, resolve(ROOT, "..", "nasOS")];
  return candidates.find((p) => p && existsSync(join(p, "scripts", "build-ota.sh"))) || null;
}

/** nasOS's address: the config, else the Samedia server's host on nasOS's port. */
export function nasosUrl(cfg, serverUrl) {
  if (cfg.nasos && cfg.nasos.url) return cfg.nasos.url;
  if (!serverUrl) return null;
  const u = new URL(serverUrl);
  return `${u.protocol}//${u.hostname}:8080`;
}

// Files the OTA package is made from, and the lines build-ota.sh stamps the version into
// (ignored, or every build would look like a change)
const SOURCES = ["frontend", "backend", "electron", "system/scripts", "system/systemd", "scripts/build-ota.sh"];
const SKIP = /(^|\/)(node_modules|dist|__pycache__|\.data|[^/]+\.egg-info)(\/|$)|\.pyc$/;
const STAMPED = {
  "frontend/package.json": "json", "electron/package.json": "json", "frontend/package-lock.json": "lock",
  "backend/pyproject.toml": /^version = ".*?"/m, "backend/app/core/config.py": /version: str = ".*?"/,
};

/** A short hash of the nasOS source as an OTA would package it. */
export function fingerprint(repo) {
  const files = execFileSync("git", ["ls-files", "-co", "--exclude-standard", "--", ...SOURCES], { cwd: repo, encoding: "utf8" })
    .split("\n").filter((f) => f && !SKIP.test(f)).sort();
  const h = createHash("sha256");
  for (const f of files) {
    let data;
    try { data = readFileSync(join(repo, f)); } catch { continue; }      // deleted, not yet committed
    const kind = STAMPED[f];
    if (kind) {
      let text = data.toString("utf8");
      if (kind === "json" || kind === "lock") {
        try {
          const j = JSON.parse(text);
          delete j.version;
          if (kind === "lock" && j.packages && j.packages[""]) delete j.packages[""].version;
          text = JSON.stringify(j);
        } catch { /* hash it as it is */ }
      } else {
        text = text.replace(kind, "");
      }
      data = Buffer.from(text);
    }
    h.update(f).update("\0").update(data).update("\0");
  }
  return h.digest("hex").slice(0, 6);
}

/** "102026-153000-ga1b2c3": nasOS's date-style version plus the source fingerprint. */
export function otaVersion(fp, when = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${p(when.getMonth() + 1)}${p(when.getDate())}${String(when.getFullYear()).slice(2)}-` +
    `${p(when.getHours())}${p(when.getMinutes())}${p(when.getSeconds())}-g${fp}`;
}

export function inSync(installed, fp) {
  return !!installed && installed.endsWith(`-g${fp}`);
}

export async function health(url) {
  try {
    const r = await fetch(`${url}/api/system/health`, { signal: AbortSignal.timeout(5000) });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

/** The checkout's branch and how many files differ from its last commit (shown before building). */
export function checkoutState(repo) {
  const g = (...a) => execFileSync("git", a, { cwd: repo, encoding: "utf8" }).trim();
  const changed = g("status", "--porcelain", "--", ...SOURCES).split("\n").filter(Boolean)
    .filter((l) => !Object.keys(STAMPED).includes(l.slice(3)));
  return { branch: g("rev-parse", "--abbrev-ref", "HEAD"), commit: g("rev-parse", "--short", "HEAD"), changed: changed.length };
}

/** Build the OTA package with the checkout's own script; the path of the package. */
export async function buildOta(repo, version) {
  await run("nasos-ota", "bash", [join(repo, "scripts", "build-ota.sh"), version], { cwd: repo });
  const out = join(repo, "dist", `nasos-update-${version}.nasos`);
  if (!existsSync(out)) throw new Error(`nasOS OTA build made no ${basename(out)}`);
  return out;
}

// ── talking to nasOS ──

async function call(url, token, path, init = {}) {
  const r = await fetch(`${url}${path}`, { ...init, headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(init.timeout || 30000) });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401) throw Object.assign(new Error("nasOS login needed"), { auth: true });
  if (!r.ok) throw new Error(body.detail || `nasOS answered ${r.status}`);
  return body;
}

export async function login(url, username, password) {
  const r = await fetch(`${url}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, remember_me: true }), signal: AbortSignal.timeout(15000),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || "nasOS refused that login");
  return body.access_token;
}

/** Is a saved token still good? */
export async function tokenWorks(url, token) {
  if (!token) return false;
  try { await call(url, token, "/api/auth/me", { timeout: 8000 }); return true; } catch { return false; }
}

/** Upload, apply, and wait until nasOS comes back on the new version. */
export async function installOta(url, token, file, version, progress = () => {}) {
  progress(`uploading ${(statSync(file).size / 1048576).toFixed(1)} MB`);
  const form = new FormData();
  form.append("file", new Blob([readFileSync(file)]), basename(file));
  await call(url, token, "/api/update/upload", { method: "POST", body: form, timeout: 600000 });
  // what the last update left behind, so an old failure isn't taken for this one's
  const before = JSON.stringify((await call(url, token, "/api/update/status").catch(() => ({}))).progress || null);
  progress("applying");
  await call(url, token, "/api/update/apply", { method: "POST", timeout: 60000 });
  // the backend restarts part-way (the whole NAS may reboot): wait for it on the new version
  const until = Date.now() + 15 * 60000;
  let last = "";
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 5000));
    const h = await health(url);
    if (h && h.version === version) return h.version;
    let p = null;
    try { p = (await call(url, token, "/api/update/status", { timeout: 8000 })).progress; } catch { /* restarting */ }
    if (!p || JSON.stringify(p) === before) continue;
    if (p.status === "error") throw new Error(`nasOS update failed: ${p.message || p.phase}`);
    const step = p.message ? `${p.message}${p.percent ? ` (${p.percent}%)` : ""}` : "";
    if (step && step !== last) progress((last = step));
  }
  throw new Error("nasOS didn't come back on the new version within 15 minutes");
}

/** Update an App Store app (e.g. "samedia") to its newest image. */
export async function updateApp(url, token, appId) {
  return call(url, token, `/api/docker/update/${encodeURIComponent(appId)}`, { method: "POST", timeout: 600000 });
}
