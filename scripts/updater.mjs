#!/usr/bin/env node
// Samedia updater: every screen that runs Samedia, what version it has, and one keypress to
// put the latest build (made on the spot from this checkout) on any of them.
//
//   npm run updater                    pick screens from the list
//   npm run updater -- --list          just show them
//   npm run updater -- --all --yes     update everything that's reachable and not playing
//   npm run updater -- --only "Living room,Kitchen TV" --yes
//   options: --launch (open the app after installing), --server http://host:8097,
//            --tv-devlog http://<this mac>:8199/log (diagnostic TV build)
//
// Screens come from the Samedia server (every app registers there, with its version) and from
// what this Mac can reach: Android phones and Google TVs over adb (Wireless debugging), iPhones
// and iPads paired with Xcode, Samsung TVs in Developer Mode over sdb.

import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import net from "node:net";
import { networkInterfaces, tmpdir } from "node:os";
import { join } from "node:path";
import readline from "node:readline";
import { BUILDERS, CONFIG_FILE, TOOL_PATH, appleTeam, buildInfo, loadConfig, saveConfig } from "./release.mjs";

const PKG = "io.samedia.player";
const TIZEN_APP = "SamediaTV0.Samedia";
const KIND = { tv: "Samsung TV", googletv: "Google TV", android: "Android", ios: "iPhone/iPad" };
const BUILD_FOR = { tv: "tv", googletv: "android", android: "android", ios: "ios" };

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const option = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : undefined; };

const c = process.stdout.isTTY
  ? { dim: (s) => `\x1b[2m${s}\x1b[0m`, bold: (s) => `\x1b[1m${s}\x1b[0m`, green: (s) => `\x1b[32m${s}\x1b[0m`,
      yellow: (s) => `\x1b[33m${s}\x1b[0m`, red: (s) => `\x1b[31m${s}\x1b[0m`, cyan: (s) => `\x1b[36m${s}\x1b[0m` }
  : { dim: String, bold: String, green: String, yellow: String, red: String, cyan: String };

// ── small helpers ──

function sh(cmd, argv, timeout = 20000) {
  return new Promise((resolve) => {
    execFile(cmd, argv, { timeout, env: { ...process.env, PATH: TOOL_PATH }, maxBuffer: 32 << 20 },
      (err, stdout, stderr) => resolve({ ok: !err, out: String(stdout || ""), err: String(stderr || (err && err.message) || "") }));
  });
}

async function getJson(url, timeout = 5000) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(timeout), headers: { "X-Samedia-Device": "updater" } });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function portOpen(host, port, timeout = 1500) {
  return new Promise((resolve) => {
    const s = net.connect({ host, port });
    const done = (ok) => { s.destroy(); resolve(ok); };
    s.setTimeout(timeout, () => done(false));
    s.on("connect", () => done(true));
    s.on("error", () => done(false));
  });
}

const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

function ask(question) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (a) => { rl.close(); resolve(a.trim()); }));
}

/** "0.9.0+38.1" → [0, 9, 0, 38, 1] for comparing. */
function versionKey(v) {
  return String(v || "0").split(/[+.]/).map((x) => parseInt(x, 10) || 0);
}
function older(a, b) {
  const x = versionKey(a), y = versionKey(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) < (y[i] || 0);
  }
  return false;
}

// ── the server ──

async function findServer(cfg) {
  const given = option("--server") || cfg.server;
  for (const url of [given, "http://nasos.local:8097"].filter(Boolean)) {
    const info = await getJson(`${url.replace(/\/+$/, "")}/api/v1/info`);
    if (info && info.app === "samedia") return { url: url.replace(/\/+$/, ""), info };
  }
  if (!process.stdin.isTTY) return null;
  const typed = await ask("Samedia server address (e.g. 192.168.1.20): ");
  const url = (typed.includes("://") ? typed : `http://${typed}`).replace(/\/+$/, "");
  const withPort = /:\d+$/.test(url) ? url : `${url}:8097`;
  const info = await getJson(`${withPort}/api/v1/info`);
  return info && info.app === "samedia" ? { url: withPort, info } : null;
}

/** The kind of app a registered device runs (older servers don't say: tell by its id). */
function kindOf(dev) {
  if (dev.app) return dev.app;
  const id = dev.id || "";
  if (id.startsWith("gtv-")) return "googletv";
  if (id.startsWith("android-")) return "android";
  if (id.startsWith("ios-")) return "ios";
  return "tv";
}

// ── what this Mac can reach ──

async function adbTargets() {
  await sh("adb", ["start-server"], 10000);
  const { out } = await sh("adb", ["devices", "-l"]);
  const lines = out.split("\n").slice(1).filter((l) => /\sdevice\s/.test(l));
  return Promise.all(lines.map(async (line) => {
    const serial = line.split(/\s+/)[0];
    const model = (line.match(/model:(\S+)/) || [])[1]?.replace(/_/g, "-") || serial;
    const s = (...a) => sh("adb", ["-s", serial, "shell", ...a], 15000).then((r) => r.out.trim());
    const [name, leanback, pkg] = await Promise.all([s("settings", "get", "global", "device_name"),
      s("pm", "has-feature", "android.software.leanback"), s("dumpsys", "package", PKG)]);
    const installed = (pkg.match(/versionName=(\S+)/) || [])[1] || null;
    return { kind: leanback === "true" ? "googletv" : "android", name: name && name !== "null" ? name : model, model,
             via: { adb: serial }, installed };
  }));
}

async function iosTargets() {
  const dir = mkdtempSync(join(tmpdir(), "samedia-"));
  try {
    const list = join(dir, "devices.json");
    if (!(await sh("xcrun", ["devicectl", "list", "devices", "--json-output", list], 30000)).ok) return [];
    const devices = JSON.parse(readFileSync(list, "utf8")).result.devices.filter((d) =>
      d.hardwareProperties?.platform === "iOS" && d.connectionProperties?.pairingState === "paired");
    return await Promise.all(devices.map(async (d) => {
      const apps = join(dir, `${d.identifier}.json`);
      let installed = null;
      const r = await sh("xcrun", ["devicectl", "device", "info", "apps", "--device", d.identifier, "--bundle-id", PKG,
        "--json-output", apps], 30000);
      if (r.ok) {
        let app = null;
        try { app = JSON.parse(readFileSync(apps, "utf8")).result?.apps?.[0]; } catch { /* no answer */ }
        if (app) installed = app.version + (app.bundleVersion && app.bundleVersion !== "1" ? `+${app.bundleVersion}` : "");
      }
      return { kind: "ios", name: d.deviceProperties?.name || "iPhone/iPad", model: d.hardwareProperties?.marketingName,
               via: { ios: d.identifier }, installed, reachable: r.ok,
               why: r.ok ? null : "not reachable: wake it and keep it on the same Wi-Fi" };
    }));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** Samsung TVs in Developer Mode on this Mac's network (they listen on port 26101). */
async function scanForTvs() {
  const mine = Object.values(networkInterfaces()).flat()
    .filter((a) => a && a.family === "IPv4" && !a.internal && /^(10|172|192)\./.test(a.address)).map((a) => a.address);
  const found = [];
  for (const ip of mine.slice(0, 2)) {
    const prefix = ip.split(".").slice(0, 3).join(".");
    const hosts = Array.from({ length: 254 }, (_, i) => `${prefix}.${i + 1}`).filter((h) => h !== ip);
    for (let i = 0; i < hosts.length; i += 64) {
      const batch = hosts.slice(i, i + 64);
      const open = await Promise.all(batch.map((h) => portOpen(h, 26101, 700)));
      batch.forEach((h, j) => open[j] && found.push(h));
    }
  }
  return found;
}

/** Connect sdb to a TV (restarting sdb's own server once if it has got stuck). */
async function sdbConnect(ip) {
  const listed = async () => (await sh("sdb", ["devices"], 8000)).out.includes(`${ip}:26101`);
  if (await listed()) return true;
  if (/connected to/.test((await sh("sdb", ["connect", ip], 15000)).out) && await listed()) return true;
  await sh("sdb", ["kill-server"], 8000);
  await sh("sdb", ["start-server"], 15000);
  await sh("sdb", ["connect", ip], 15000);
  return listed();
}

async function tvTargets(addresses) {
  const out = [];
  for (const ip of addresses) {           // one at a time: sdb's server is shared
    const open = await portOpen(ip, 26101);
    const ok = open && await sdbConnect(ip);
    let installed = null;
    if (ok) {
      const apps = (await sh("sdb", ["-s", `${ip}:26101`, "shell", "0", "vd_applist"], 20000)).out;
      const entry = apps.split(/app_id\s*=/).find((e) => e.startsWith("SamediaTV0.Samedia"));
      installed = entry && (entry.match(/app_version\s*=([0-9.]+)/) || [])[1] || null;
    }
    out.push({ kind: "tv", name: `Samsung TV ${ip}`, via: { sdb: ip }, address: ip, reachable: ok, installed,
               why: ok ? null : open ? "TV refused this Mac: set Developer Mode's Host PC IP to this Mac"
                 : "not reachable: TV off, or Developer Mode not on (Apps → 1 2 3 4 5)" });
  }
  return out;
}

// ── putting it together ──

async function discover(cfg, server) {
  const reg = server ? ((await getJson(`${server.url}/api/v1/admin/devices`))?.devices || []) : [];
  const playing = new Map((server ? ((await getJson(`${server.url}/api/v1/remote/players`))?.players || []) : [])
    .filter((p) => p.now_playing).map((p) => [p.id, p.now_playing.title]));
  const tvAddresses = new Set(cfg.tvs || []);
  for (const d of reg) if (kindOf(d) === "tv" && d.address) tvAddresses.add(d.address);
  const sdbList = await sh("sdb", ["devices"], 8000);
  for (const m of sdbList.out.matchAll(/^(\d+\.\d+\.\d+\.\d+):26101\s+device/gm)) tvAddresses.add(m[1]);
  // a Samsung TV the server knows of but can't place: look for it on the network
  const tvsKnown = reg.filter((d) => kindOf(d) === "tv").length;
  if (tvsKnown > tvAddresses.size) (await scanForTvs()).forEach((ip) => tvAddresses.add(ip));

  const [adb, ios, tvs] = await Promise.all([adbTargets(), iosTargets(), tvTargets(tvAddresses)]);
  const targets = [...adb.map((t) => ({ ...t, reachable: true })), ...ios, ...tvs];

  // match the server's devices to what can be reached: by address, name or model, else the
  // only one of its kind
  const used = new Set();
  for (const dev of reg) {
    const kind = kindOf(dev);
    const same = targets.filter((t) => t.kind === kind && !t.reg);
    const hit = same.find((t) => dev.address && t.address === dev.address)
      || same.find((t) => [dev.name, dev.model].some((n) => n && (norm(n) === norm(t.name) || norm(n) === norm(t.model))))
      || (same.length === 1 && reg.filter((d) => kindOf(d) === kind && !used.has(d.id)).length === 1 ? same[0] : null);
    used.add(dev.id);
    if (hit) {
      hit.reg = dev;
      if (kind === "tv" || kind === "ios") hit.name = dev.name || hit.name;
      if (dev.version && (!hit.installed || versionKey(dev.version).length > versionKey(hit.installed).length)) {
        hit.installed = dev.version;
      }
    } else if (Date.now() / 1000 - dev.last_seen < 60 * 86400) {
      const hint = { tv: "not reachable: turn on Developer Mode with this Mac's address, or add it: --tv <ip>",
        googletv: "not reachable: Developer options → Wireless debugging, then adb pair",
        android: "not reachable: Developer options → Wireless debugging, then adb pair",
        ios: "not reachable: pair it with Xcode (Window → Devices)" }[kind];
      targets.push({ kind, name: dev.name, reg: dev, installed: dev.version || null, reachable: false, why: hint });
    }
  }
  for (const t of targets) t.playing = t.reg && playing.get(t.reg.id);
  return targets.sort((a, b) => (b.reachable - a.reachable) || a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name));
}

function describe(t, latest) {
  const have = t.installed || (t.reachable ? "not installed" : "?");
  const state = !t.reachable ? c.red(t.why || "not reachable")
    : t.playing ? c.yellow(`▶ playing ${t.playing} (updating stops it)`)
    : !t.installed ? c.cyan("ready")
    : older(t.installed, latest) ? c.cyan("update available") : c.green("up to date");
  return `${t.name.padEnd(18).slice(0, 18)} ${KIND[t.kind].padEnd(11)} ${String(have).padEnd(14)} ${state}`;
}

/** Checkbox list in the terminal: ↑/↓, space, a (all), enter. */
function pick(targets, latest, initial) {
  return new Promise((resolve) => {
    const selected = new Set(initial);
    let cur = 0, drawn = 0;
    const draw = () => {
      if (drawn) process.stdout.write(`\x1b[${drawn}A\x1b[J`);
      const lines = targets.map((t, i) => {
        const box = !t.reachable ? c.dim("[ ]") : selected.has(i) ? c.green("[x]") : "[ ]";
        return `${i === cur ? c.bold("›") : " "} ${box} ${describe(t, latest)}`;
      });
      lines.push(c.dim("  ↑/↓ move · space select · a all · enter update · q quit"));
      process.stdout.write(lines.join("\n") + "\n");
      drawn = lines.length;
    };
    readline.emitKeypressEvents(process.stdin);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const done = (value) => { process.stdin.setRawMode(false); process.stdin.pause(); process.stdin.off("keypress", onKey); resolve(value); };
    const onKey = (_, key = {}) => {
      if (key.ctrl && key.name === "c" || key.name === "q" || key.name === "escape") return done(null);
      if (key.name === "up") cur = (cur + targets.length - 1) % targets.length;
      else if (key.name === "down") cur = (cur + 1) % targets.length;
      else if (key.name === "space" && targets[cur].reachable) selected.has(cur) ? selected.delete(cur) : selected.add(cur);
      else if (key.name === "a") {
        const all = targets.map((t, i) => i).filter((i) => targets[i].reachable);
        const every = all.every((i) => selected.has(i));
        all.forEach((i) => (every ? selected.delete(i) : selected.add(i)));
      } else if (key.name === "return") return done([...selected].map((i) => targets[i]));
      draw();
    };
    process.stdin.on("keypress", onKey);
    draw();
  });
}

// ── installing ──

async function install(t, artifact) {
  const launch = flag("--launch");
  if (t.via?.adb) {
    const r = await sh("adb", ["-s", t.via.adb, "install", "-r", artifact], 300000);
    if (!r.ok || !/Success/.test(r.out)) throw new Error((r.out + r.err).trim().split("\n").pop());
    if (launch) await sh("adb", ["-s", t.via.adb, "shell", "am", "start", "-n",
      `${PKG}/.${t.kind === "googletv" ? "tv.TvActivity" : "MainActivity"}`]);
    const pkg = await sh("adb", ["-s", t.via.adb, "shell", "dumpsys", "package", PKG]);
    return (pkg.out.match(/versionName=(\S+)/) || [])[1];
  }
  if (t.via?.ios) {
    const r = await sh("xcrun", ["devicectl", "device", "install", "app", "--device", t.via.ios, artifact], 300000);
    if (!r.ok) throw new Error((r.err || r.out).trim().split("\n").pop());
    if (launch) await sh("xcrun", ["devicectl", "device", "process", "launch", "--device", t.via.ios, PKG], 60000);
    return null;
  }
  if (t.via?.sdb) {
    const serial = `${t.via.sdb}:26101`;
    if (!(await sdbConnect(t.via.sdb))) throw new Error("couldn't connect to the TV");
    const r = await sh("tizen", ["install", "-n", artifact, "-s", serial], 300000);
    if (!/successfully installed/i.test(r.out)) throw new Error((r.out + r.err).trim().split("\n").slice(-2).join(" "));
    if (launch) await sh("tizen", ["run", "-p", TIZEN_APP, "-s", serial], 60000);
    return null;
  }
  throw new Error("no way to reach it");
}

async function main() {
  const cfg = loadConfig();
  const extraTv = option("--tv");
  if (extraTv) cfg.tvs = [...new Set([...(cfg.tvs || []), extraTv])];
  const info = buildInfo();
  process.stdout.write(c.dim("Looking for Samedia screens…\n"));
  const server = await findServer(cfg);
  if (server && server.url !== cfg.server) cfg.server = server.url;

  const targets = await discover(cfg, server);
  // remember Samsung TVs, which can't be found by asking around
  cfg.tvs = [...new Set([...(cfg.tvs || []), ...targets.filter((t) => t.kind === "tv" && t.address).map((t) => t.address)])];
  saveConfig(cfg);

  console.log(`\n${c.bold("Samedia updater")}  latest build ${c.bold(info.full)}`);
  if (server) {
    const sv = server.info.version;
    console.log(`Server ${server.info.name} (${server.url}) runs ${sv}` +
      (older(sv, info.version) ? c.yellow(`: update Samedia in the nasOS App Store to get ${info.version}`) : ""));
  } else {
    console.log(c.yellow("No Samedia server found: showing only the screens this Mac can reach."));
  }
  if (!targets.length) { console.log("\nNo screens found."); return; }
  console.log("");

  if (flag("--list")) {
    targets.forEach((t) => console.log(`  ${describe(t, info.full)}`));
    return;
  }

  const want = (t) => t.reachable && !t.playing && (!t.installed || older(t.installed, info.full));
  let chosen;
  if (option("--only")) {
    const names = option("--only").split(",").map(norm);
    chosen = targets.filter((t) => t.reachable && names.includes(norm(t.name)));
  } else if (flag("--all")) {
    chosen = targets.filter((t) => t.reachable && !t.playing);
  } else if (process.stdin.isTTY) {
    chosen = await pick(targets, info.full, targets.map((t, i) => (want(t) ? i : -1)).filter((i) => i >= 0));
    if (!chosen) return;
  } else {
    targets.forEach((t) => console.log(`  ${describe(t, info.full)}`));
    console.log("\nNot a terminal: pass --all or --only <names>.");
    return;
  }
  if (!chosen.length) { console.log("Nothing selected."); return; }

  if (chosen.some((t) => t.kind === "ios") && !appleTeam()) {
    const team = await ask("Apple development team id for iPhone/iPad builds (Xcode → Settings → Accounts): ");
    if (team) { cfg.appleTeam = team; saveConfig(cfg); console.log(c.dim(`Saved in ${CONFIG_FILE}`)); }
  }

  // one build per platform, then install
  const builds = {};
  for (const platform of [...new Set(chosen.map((t) => BUILD_FOR[t.kind]))]) {
    const started = Date.now();
    process.stdout.write(`Building ${platform} ${info.full}… `);
    try {
      builds[platform] = await BUILDERS[platform](info, { devlog: option("--tv-devlog") });
      console.log(c.green(`done (${Math.round((Date.now() - started) / 1000)}s)`));
    } catch (e) {
      console.log(c.red("failed"));
      console.log(c.dim(e.message));
    }
  }
  let failed = 0;
  for (const t of chosen) {
    const artifact = builds[BUILD_FOR[t.kind]];
    process.stdout.write(`Installing on ${t.name}… `);
    if (!artifact) { console.log(c.red("skipped (no build)")); failed++; continue; }
    try {
      const now = await install(t, artifact);
      console.log(c.green(`done${now ? ` (${now})` : ""}`));
    } catch (e) {
      failed++;
      console.log(c.red(`failed: ${e.message}`));
    }
  }
  if (failed) process.exitCode = 1;
}

main().catch((e) => { console.error(c.red(e.stack || e.message)); process.exit(1); });
