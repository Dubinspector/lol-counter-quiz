#!/usr/bin/env node
/**
 * scripts/extract.mjs
 *
 * Účel:
 * - Stahuje Riot match-v5 data (volitelně), ukládá raw JSONy do scripts/match/raw a scripts/timeline/raw
 * - Normalizuje match JSON -> cleaned JSONL do scripts/out/cleaned/matches.jsonl
 *
 * Bez externích závislostí. Node >= 18 (ty máš 24).
 */

import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      i++;
    }
  }
  return args;
}

async function exists(p) {
  try {
    await fsp.access(p);
    return true;
  } catch {
    return false;
  }
}

async function ensureDir(p) {
  await fsp.mkdir(p, { recursive: true });
}

function toPatch(gameVersion) {
  // typicky "14.2.556.1234" -> "14.2"
  if (typeof gameVersion !== "string") return "unknown";
  const parts = gameVersion.split(".");
  if (parts.length < 2) return gameVersion;
  return `${parts[0]}.${parts[1]}`;
}

function safeNumber(x, fallback = 0) {
  return Number.isFinite(x) ? x : fallback;
}

function normalizeMatch(matchJson) {
  // match-v5 format: { metadata: {...}, info: {...} }
  const md = matchJson?.metadata ?? {};
  const info = matchJson?.info ?? {};
  const participants = Array.isArray(info.participants) ? info.participants : [];
  const teams = Array.isArray(info.teams) ? info.teams : [];

  const matchId = md.matchId ?? info.gameId ?? null;

  const out = {
    matchId,
    platformId: info.platformId ?? null,
    gameCreation: info.gameCreation ?? null,
    gameStartTimestamp: info.gameStartTimestamp ?? null,
    gameEndTimestamp: info.gameEndTimestamp ?? null,
    gameDuration: info.gameDuration ?? null,
    gameMode: info.gameMode ?? null,
    gameType: info.gameType ?? null,
    queueId: info.queueId ?? null,
    mapId: info.mapId ?? null,
    gameVersion: info.gameVersion ?? null,
    patch: toPatch(info.gameVersion),
    participants: participants.map((p) => ({
      puuid: p.puuid ?? null,
      summonerName: p.summonerName ?? null,
      teamId: p.teamId ?? null,
      win: !!p.win,
      championId: p.championId ?? null,
      championName: p.championName ?? null,

      lane: p.lane ?? null,
      role: p.role ?? null,
      individualPosition: p.individualPosition ?? null,

      kills: safeNumber(p.kills),
      deaths: safeNumber(p.deaths),
      assists: safeNumber(p.assists),

      goldEarned: safeNumber(p.goldEarned),
      totalDamageDealtToChampions: safeNumber(p.totalDamageDealtToChampions),
      totalMinionsKilled: safeNumber(p.totalMinionsKilled),
      neutralMinionsKilled: safeNumber(p.neutralMinionsKilled),
      visionScore: safeNumber(p.visionScore),

      item0: p.item0 ?? null,
      item1: p.item1 ?? null,
      item2: p.item2 ?? null,
      item3: p.item3 ?? null,
      item4: p.item4 ?? null,
      item5: p.item5 ?? null,
      item6: p.item6 ?? null
    })),
    teams: teams.map((t) => ({
      teamId: t.teamId ?? null,
      win: (t.win === true) || (t.win === "Win"),
      objectives: t.objectives ?? null
    }))
  };

  return out;
}

/** jednoduchý async pool bez externích deps */
async function asyncPool(limit, items, worker) {
  const ret = [];
  const executing = new Set();
  for (const item of items) {
    const p = Promise.resolve().then(() => worker(item));
    ret.push(p);
    executing.add(p);
    p.finally(() => executing.delete(p));
    if (executing.size >= limit) {
      await Promise.race(executing);
    }
  }
  return Promise.all(ret);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchWithRetry(url, { headers = {}, retries = 6 } = {}) {
  let attempt = 0;
  let backoff = 800;

  while (true) {
    attempt++;
    const res = await fetch(url, { headers });

    if (res.status === 429) {
      // Riot rate limit: čekej podle Retry-After pokud je
      const ra = res.headers.get("retry-after");
      const waitMs = ra ? Math.max(1000, Number(ra) * 1000) : backoff;
      await sleep(waitMs);
      backoff = Math.min(backoff * 1.8, 15000);
      if (attempt <= retries) continue;
    }

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      if (attempt <= retries && (res.status >= 500 || res.status === 408)) {
        await sleep(backoff);
        backoff = Math.min(backoff * 1.8, 15000);
        continue;
      }
      throw new Error(`HTTP ${res.status} for ${url}\n${text.slice(0, 400)}`);
    }

    return res.json();
  }
}

async function loadDotEnv(repoRoot) {
  const envPath = path.join(repoRoot, ".env");
  if (!(await exists(envPath))) return;
  const txt = await fsp.readFile(envPath, "utf8");
  for (const line of txt.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq <= 0) continue;
    const k = t.slice(0, eq).trim();
    let v = t.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    if (!process.env[k]) process.env[k] = v;
  }
}

async function findRepoRoot(startDir) {
  let cur = startDir;
  while (true) {
    const pj = path.join(cur, "package.json");
    if (await exists(pj)) return cur;
    const parent = path.dirname(cur);
    if (parent === cur) return startDir;
    cur = parent;
  }
}

export async function extract(options = {}) {
  const repoRoot = await findRepoRoot(process.cwd());
  await loadDotEnv(repoRoot);

  const scriptsDir = path.join(repoRoot, "scripts");
  const rawMatchDir = path.join(scriptsDir, "match", "raw");
  const rawTimelineDir = path.join(scriptsDir, "timeline", "raw");
  const cleanedDir = path.join(scriptsDir, "out", "cleaned");
  const cleanedMatchesPath = path.join(cleanedDir, "matches.jsonl");

  await ensureDir(rawMatchDir);
  await ensureDir(rawTimelineDir);
  await ensureDir(cleanedDir);

  const matchIdsFile = options.matchIds ?? process.env.MATCH_IDS_FILE ?? null;
  const region = options.region ?? process.env.RIOT_REGION ?? "europe"; // americas/europe/asia/sea
  const apiKey = options.apiKey ?? process.env.RIOT_API_KEY ?? null;
  const concurrency = Number(options.concurrency ?? process.env.CONCURRENCY ?? 4);

  // 1) volitelné: stáhnout raw JSONy podle listu matchId
  if (matchIdsFile) {
    if (!apiKey) throw new Error("MATCH_IDS_FILE je nastavené, ale chybí RIOT_API_KEY.");
    const listPath = path.isAbsolute(matchIdsFile) ? matchIdsFile : path.join(repoRoot, matchIdsFile);
    const content = await fsp.readFile(listPath, "utf8");
    const matchIds = content
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);

    const headers = { "X-Riot-Token": apiKey };

    await asyncPool(concurrency, matchIds, async (matchId) => {
      const matchOut = path.join(rawMatchDir, `${matchId}.json`);
      if (!(await exists(matchOut))) {
        const url = `https://${region}.api.riotgames.com/lol/match/v5/matches/${encodeURIComponent(matchId)}`;
        const data = await fetchWithRetry(url, { headers });
        await fsp.writeFile(matchOut, JSON.stringify(data));
      }

      // timeline je volitelný, ale typicky ho chceš
      const tlOut = path.join(rawTimelineDir, `${matchId}.json`);
      if (!(await exists(tlOut))) {
        const url = `https://${region}.api.riotgames.com/lol/match/v5/matches/${encodeURIComponent(matchId)}/timeline`;
        const data = await fetchWithRetry(url, { headers });
        await fsp.writeFile(tlOut, JSON.stringify(data));
      }
    });
  }

  // 2) vyčistit z raw match souborů -> matches.jsonl
  const rawFiles = (await fsp.readdir(rawMatchDir))
    .filter((f) => f.toLowerCase().endsWith(".json"))
    .map((f) => path.join(rawMatchDir, f));

  if (rawFiles.length === 0) {
    throw new Error(
      `Nenalezeny raw match soubory v ${rawMatchDir}.\n` +
      `Buď sem dej *.json, nebo nastav MATCH_IDS_FILE + RIOT_API_KEY a spust extract znovu.`
    );
  }

  const outStream = fs.createWriteStream(cleanedMatchesPath, { flags: "w" });

  for (const filePath of rawFiles) {
    const txt = await fsp.readFile(filePath, "utf8");
    let json;
    try {
      json = JSON.parse(txt);
    } catch (e) {
      throw new Error(`Neplatný JSON: ${filePath}`);
    }
    const norm = normalizeMatch(json);
    if (!norm.matchId) continue;
    outStream.write(JSON.stringify(norm) + "\n");
  }

  await new Promise((resolve, reject) => {
    outStream.end(() => resolve());
    outStream.on("error", reject);
  });

  return { cleanedMatchesPath, rawCount: rawFiles.length };
}

async function main() {
  const args = parseArgs(process.argv);

  if (args.help) {
    console.log(`
Usage:
  node scripts/extract.mjs [--match-ids <file>] [--region europe] [--concurrency 4]

Env:
  RIOT_API_KEY       Riot API key (pokud stahuješ)
  RIOT_REGION        europe|americas|asia|sea  (match-v5 routing)
  MATCH_IDS_FILE     cesta k souboru s matchId (1 na řádek)
  CONCURRENCY        počet paralelních requestů

Poznámka:
  Pokud máš už raw match JSONy v scripts/match/raw/*.json, extract jen vyčistí a nevytváří requesty.
`.trim());
    process.exit(0);
  }

  const res = await extract({
    matchIds: args["match-ids"],
    region: args.region,
    concurrency: args.concurrency
  });

  console.log(`OK: cleaned -> ${res.cleanedMatchesPath} (raw files: ${res.rawCount})`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error(err?.stack || String(err));
    process.exit(1);
  });
}