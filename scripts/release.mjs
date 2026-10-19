#!/usr/bin/env node
// Release builds of every Samedia app, made on the spot from this checkout.
//
//   npm run build -- tv android ios     (or: all)     artifacts in dist/release/
//   npm run version -- 0.10.0                          set the version everywhere
//
// Every build carries the repo's VERSION plus a build number: the number of commits, with
// ".1" when there are uncommitted changes ("0.9.0+38", "0.9.0+38.1"). The apps report it to
// the server, which is how the updater tells what's out of date.
//
// Personal settings (Apple team id) come from the environment or the updater's config file
// (~/.config/samedia/updater.json), never from the repo.

import { execFileSync, spawn } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync, copyFileSync, createWriteStream } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const DIST = join(ROOT, "dist", "release");
const LOGS = join(ROOT, "dist", "logs");
export const CONFIG_FILE = join(homedir(), ".config", "samedia", "updater.json");

const STUDIO_JAVA = "/Applications/Android Studio.app/Contents/jbr/Contents/Home";
export const ANDROID_SDK = process.env.ANDROID_HOME || join(homedir(), "Library", "Android", "sdk");
const TIZEN = process.env.TIZEN_STUDIO || join(homedir(), "tizen-studio");
export const TOOL_PATH = [join(TIZEN, "tools", "ide", "bin"), join(TIZEN, "tools"), join(ANDROID_SDK, "platform-tools"),
  process.env.PATH].join(":");

export function loadConfig() {
  try { return JSON.parse(readFileSync(CONFIG_FILE, "utf8")); } catch { return {}; }
}

export function saveConfig(cfg) {
  mkdirSync(dirname(CONFIG_FILE), { recursive: true });
  writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2) + "\n", { mode: 0o600 });
  chmodSync(CONFIG_FILE, 0o600);          // it can hold a nasOS login token: yours only
}

function git(...args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

/** What a build made now would be called: { version, build, full }. */
export function buildInfo() {
  const version = readFileSync(join(ROOT, "VERSION"), "utf8").trim();
  const count = git("rev-list", "--count", "HEAD");
  const dirty = git("status", "--porcelain", "--", "tv", "android", "ios", "server", "VERSION") !== "";
  const build = dirty ? `${count}.1` : count;
  return { version, build, full: `${version}+${build}` };
}

/** Run a build step, its output going to dist/logs/<name>.log (shown on failure). */
export function run(name, cmd, args, opts = {}) {
  mkdirSync(LOGS, { recursive: true });
  const logFile = join(LOGS, `${name}.log`);
  const log = createWriteStream(logFile);
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { cwd: opts.cwd || ROOT, env: { ...process.env, PATH: TOOL_PATH, ...opts.env } });
    p.stdout.pipe(log, { end: false });
    p.stderr.pipe(log, { end: false });
    p.on("error", reject);
    p.on("close", (code) => {
      log.end();
      if (code === 0) return resolve();
      const tail = readFileSync(logFile, "utf8").split("\n").filter(Boolean).slice(-25).join("\n");
      reject(new Error(`${name} failed (exit ${code}); log: ${logFile}\n${tail}`));
    });
  });
}

// ── the builds ──

export async function buildTv(info, { devlog } = {}) {
  const args = [join(ROOT, "scripts", "package-tv.sh")];
  if (devlog) args.push("--devlog", devlog);
  await run("tv", "bash", args, { env: { SAMEDIA_VERSION: info.version, SAMEDIA_BUILD: info.full } });
  mkdirSync(DIST, { recursive: true });
  const out = join(DIST, `samedia-tv-${info.full}.wgt`);
  copyFileSync(join(ROOT, "dist", "Samedia.wgt"), out);
  return out;
}

export async function buildAndroid(info) {
  const dir = join(ROOT, "android");
  if (!existsSync(join(dir, "local.properties"))) writeFileSync(join(dir, "local.properties"), `sdk.dir=${ANDROID_SDK}\n`);
  const env = process.env.JAVA_HOME ? {} : { JAVA_HOME: STUDIO_JAVA };
  await run("android", "./gradlew", ["--console=plain", "-q", "assembleRelease",
    `-PsamediaVersion=${info.version}`, `-PsamediaBuild=${info.build}`], { cwd: dir, env });
  mkdirSync(DIST, { recursive: true });
  const out = join(DIST, `samedia-android-${info.full}.apk`);
  copyFileSync(join(dir, "app", "build", "outputs", "apk", "release", "app-release.apk"), out);
  return out;
}

export function appleTeam() {
  return process.env.SAMEDIA_TEAM || loadConfig().appleTeam || "";
}

export async function buildIos(info) {
  const team = appleTeam();
  if (!team) throw new Error("No Apple team: set SAMEDIA_TEAM, or run npm run updater once to save it.");
  const dir = join(ROOT, "ios");
  await run("ios-avatars", "bash", [join(ROOT, "scripts", "sync-ios-avatars.sh")]);
  await run("ios-project", "xcodegen", ["generate", "--quiet"], { cwd: dir });
  await run("ios", "xcodebuild", ["-project", "Samedia.xcodeproj", "-scheme", "Samedia", "-configuration", "Release",
    "-destination", "generic/platform=iOS", "-derivedDataPath", "build", "-allowProvisioningUpdates", "-quiet",
    `DEVELOPMENT_TEAM=${team}`, `PRODUCT_BUNDLE_IDENTIFIER=${process.env.SAMEDIA_BUNDLE_ID || "io.samedia.player"}`,
    `MARKETING_VERSION=${info.version}`, `CURRENT_PROJECT_VERSION=${info.build}`, "build"], { cwd: dir });
  return join(dir, "build", "Build", "Products", "Release-iphoneos", "Samedia.app");
}

export const BUILDERS = { tv: buildTv, android: buildAndroid, ios: buildIos };

// ── version ──

/** Set the version in VERSION and every place that carries it. */
export function setVersion(v) {
  if (!/^\d+\.\d+\.\d+$/.test(v)) throw new Error(`Version must look like 1.2.3 (got ${v})`);
  const edits = [
    ["VERSION", /^.*$/s, `${v}\n`],
    ["server/samedia/config.py", /^VERSION = ".*"$/m, `VERSION = "${v}"`],
    ["tv/config.xml", /(<widget[^>]* version=")[0-9.]+"/, `$1${v}"`],
    ["tv/js/app.js", /SM\.VERSION = '[^']*'/, `SM.VERSION = '${v}'`],
    ["ios/project.yml", /MARKETING_VERSION: "[^"]*"/, `MARKETING_VERSION: "${v}"`],
  ];
  for (const [file, re, rep] of edits) {
    const p = join(ROOT, file);
    const before = readFileSync(p, "utf8");
    const after = before.replace(re, rep);
    if (before === after && file !== "VERSION") throw new Error(`Couldn't set the version in ${file}`);
    writeFileSync(p, after);
  }
}

// ── command line ──

async function main(argv) {
  const [cmd, ...rest] = argv;
  if (cmd === "version") {
    if (rest[0]) setVersion(rest[0]);
    console.log(buildInfo().full);
    return;
  }
  if (cmd === "build") {
    const targets = rest.includes("all") || !rest.length ? Object.keys(BUILDERS) : rest;
    const devlog = rest.find((a) => a.startsWith("--devlog="))?.slice(9);
    const info = buildInfo();
    console.log(`Samedia ${info.full}`);
    for (const t of targets.filter((t) => !t.startsWith("--"))) {
      if (!BUILDERS[t]) throw new Error(`Unknown target ${t} (tv, android, ios, all)`);
      const started = Date.now();
      process.stdout.write(`  building ${t}… `);
      const out = await BUILDERS[t](info, { devlog });
      console.log(`done in ${Math.round((Date.now() - started) / 1000)}s → ${out.replace(ROOT + "/", "")}`);
    }
    return;
  }
  console.log("usage: release.mjs build [tv|android|ios|all] | version [x.y.z]");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch((e) => { console.error(`\n${e.message}`); process.exit(1); });
}
