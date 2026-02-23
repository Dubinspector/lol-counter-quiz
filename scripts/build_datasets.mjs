#!/usr/bin/env node
/**
 * scripts/build_datasets.mjs
 *
 * Vstup:
 *   scripts/out/cleaned/matches.jsonl
 *
 * Výstup (default):
 *   public/data/*.json
 *
 * Datasets:
 *   meta.json
 *   champions.json
 *   queues.json
 *   patches.json
 *   timeseries_daily.json
 *   matches_compact.json
 */

import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";
import { pathToFileURL } from "node:url";

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

function safeDiv(a, b) {
  if (!Number.isFinite(a) || !Number.isFinite(b) || b === 0) return 0;
  return a / b;
}

function round(x, digits = 4) {
  if (!Number.isFinite(x)) return 0;
  const m = 10 ** digits;
  return Math.round(x * m) / m;
}

function toISODate(tsMs) {
  if (!Number.isFinite(tsMs)) return null;
  const d = new Date(tsMs);
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

export async function buildDatasets(options = {}) {
  const repoRoot = await findRepoRoot(process.cwd());
  const scriptsDir = path.join(repoRoot, "scripts");

  const cleanedMatchesPath =
    options.input ??
    path.join(scriptsDir, "out", "cleaned", "matches.jsonl");

  const outDir =
    options.out ??
    path.join(repoRoot, "public", "data");

  await ensureDir(outDir);

  if (!(await exists(cleanedMatchesPath))) {
    throw new Error(
      `Chybí vstup: ${cleanedMatchesPath}\n` +
      `Spusť nejdřív: npm run extract (nebo vytvoř scripts/out/cleaned/matches.jsonl).`
    );
  }

  const rl = readline.createInterface({
    input: fs.createReadStream(cleanedMatchesPath, "utf8"),
    crlfDelay: Infinity
  });

  // agregace
  const championAgg = new Map(); // championId -> stats
  const queueAgg = new Map();    // queueId -> stats
  const patchAgg = new Map();    // patch -> stats
  const dailyAgg = new Map();    // YYYY-MM-DD -> stats

  let matchCount = 0;
  let participantCount = 0;
  let minTs = Infinity;
  let maxTs = -Infinity;

  const matchesCompact = [];

  for await (const line of rl) {
    const t = line.trim();
    if (!t) continue;

    let m;
    try {
      m = JSON.parse(t);
    } catch {
      continue;
    }

    if (!m.matchId) continue;
    matchCount++;

    const startTs = Number(m.gameStartTimestamp ?? m.gameCreation ?? NaN);
    const duration = Number(m.gameDuration ?? NaN);
    const queueId = m.queueId ?? null;
    const patch = m.patch ?? "unknown";

    if (Number.isFinite(startTs)) {
      minTs = Math.min(minTs, startTs);
      maxTs = Math.max(maxTs, startTs);
    }

    // zjisti win pro "blue" a "red" pokud jsou teams
    let blueWin = null;
    let redWin = null;
    if (Array.isArray(m.teams)) {
      for (const tm of m.teams) {
        if (tm?.teamId === 100) blueWin = !!tm.win;
        if (tm?.teamId === 200) redWin = !!tm.win;
      }
    }

    matchesCompact.push({
      matchId: m.matchId,
      gameStartTimestamp: Number.isFinite(startTs) ? startTs : null,
      queueId,
      patch,
      gameDuration: Number.isFinite(duration) ? duration : null,
      blueWin,
      redWin
    });

    // match-level agregace do queue/patch/day
    const day = Number.isFinite(startTs) ? toISODate(startTs) : null;

    function bump(map, key) {
      if (key === null || key === undefined) return null;
      const k = String(key);
      if (!map.has(k)) {
        map.set(k, { games: 0, durationSum: 0, durationN: 0, killsSum: 0 });
      }
      const s = map.get(k);
      s.games += 1;
      if (Number.isFinite(duration)) {
        s.durationSum += duration;
        s.durationN += 1;
      }
      return s;
    }

    const qS = bump(queueAgg, queueId);
    const pS = bump(patchAgg, patch);
    const dS = day ? bump(dailyAgg, day) : null;

    // participants agregace (champions + kills pro match-level stats)
    const parts = Array.isArray(m.participants) ? m.participants : [];
    participantCount += parts.length;

    let matchKills = 0;

    for (const p of parts) {
      const champId = p?.championId;
      if (champId === null || champId === undefined) continue;
      const champKey = String(champId);

      if (!championAgg.has(champKey)) {
        championAgg.set(champKey, {
          championId: champId,
          games: 0,
          wins: 0,
          kills: 0,
          deaths: 0,
          assists: 0,
          gold: 0,
          damage: 0,
          cs: 0
        });
      }
      const s = championAgg.get(champKey);

      const kills = Number(p.kills ?? 0);
      const deaths = Number(p.deaths ?? 0);
      const assists = Number(p.assists ?? 0);
      const gold = Number(p.goldEarned ?? 0);
      const damage = Number(p.totalDamageDealtToChampions ?? 0);
      const cs = Number(p.totalMinionsKilled ?? 0) + Number(p.neutralMinionsKilled ?? 0);

      s.games += 1;
      s.wins += p.win ? 1 : 0;
      s.kills += Number.isFinite(kills) ? kills : 0;
      s.deaths += Number.isFinite(deaths) ? deaths : 0;
      s.assists += Number.isFinite(assists) ? assists : 0;
      s.gold += Number.isFinite(gold) ? gold : 0;
      s.damage += Number.isFinite(damage) ? damage : 0;
      s.cs += Number.isFinite(cs) ? cs : 0;

      matchKills += Number.isFinite(kills) ? kills : 0;
    }

    if (qS) qS.killsSum += matchKills;
    if (pS) pS.killsSum += matchKills;
    if (dS) dS.killsSum += matchKills;
  }

  // serializace datasetů
  const champions = Array.from(championAgg.values())
    .map((s) => {
      const winRate = safeDiv(s.wins, s.games);
      const avgKills = safeDiv(s.kills, s.games);
      const avgDeaths = safeDiv(s.deaths, s.games);
      const avgAssists = safeDiv(s.assists, s.games);
      const kda = safeDiv(s.kills + s.assists, Math.max(1, s.deaths));
      return {
        championId: s.championId,
        games: s.games,
        wins: s.wins,
        winRate: round(winRate, 4),
        avgKills: round(avgKills, 3),
        avgDeaths: round(avgDeaths, 3),
        avgAssists: round(avgAssists, 3),
        avgKda: round(kda, 3),
        avgGold: round(safeDiv(s.gold, s.games), 1),
        avgDamageToChamps: round(safeDiv(s.damage, s.games), 1),
        avgCs: round(safeDiv(s.cs, s.games), 1)
      };
    })
    .sort((a, b) => b.games - a.games);

  function mapToArray(map, keyName) {
    return Array.from(map.entries())
      .map(([k, s]) => ({
        [keyName]: isNaN(Number(k)) ? k : Number(k),
        games: s.games,
        avgDuration: s.durationN ? round(s.durationSum / s.durationN, 2) : 0,
        avgTotalKills: s.games ? round(s.killsSum / s.games, 2) : 0
      }))
      .sort((a, b) => b.games - a.games);
  }

  const queues = mapToArray(queueAgg, "queueId");
  const patches = mapToArray(patchAgg, "patch");

  const timeseriesDaily = Array.from(dailyAgg.entries())
    .map(([date, s]) => ({
      date,
      games: s.games,
      avgDuration: s.durationN ? round(s.durationSum / s.durationN, 2) : 0,
      avgTotalKills: s.games ? round(s.killsSum / s.games, 2) : 0
    }))
    .sort((a, b) => (a.date < b.date ? -1 : 1));

  const meta = {
    generatedAt: new Date().toISOString(),
    matchCount,
    participantCount,
    dateRange: {
      minGameStartTimestamp: Number.isFinite(minTs) ? minTs : null,
      maxGameStartTimestamp: Number.isFinite(maxTs) ? maxTs : null
    },
    outputs: {
      outDir
    }
  };

  // zapis souborů
  await fsp.writeFile(path.join(outDir, "meta.json"), JSON.stringify(meta, null, 2), "utf8");
  await fsp.writeFile(path.join(outDir, "champions.json"), JSON.stringify(champions, null, 2), "utf8");
  await fsp.writeFile(path.join(outDir, "queues.json"), JSON.stringify(queues, null, 2), "utf8");
  await fsp.writeFile(path.join(outDir, "patches.json"), JSON.stringify(patches, null, 2), "utf8");
  await fsp.writeFile(path.join(outDir, "timeseries_daily.json"), JSON.stringify(timeseriesDaily, null, 2), "utf8");
  await fsp.writeFile(path.join(outDir, "matches_compact.json"), JSON.stringify(matchesCompact, null, 2), "utf8");

  return { outDir, matchCount };
}

async function main() {
  const args = parseArgs(process.argv);

  if (args.help) {
    console.log(`
Usage:
  node scripts/build_datasets.mjs [--input <matches.jsonl>] [--out <dir>]

Default input:
  scripts/out/cleaned/matches.jsonl

Default out:
  public/data
`.trim());
    process.exit(0);
  }

  const res = await buildDatasets({
    input: args.input,
    out: args.out
  });

  console.log(`OK: datasets -> ${res.outDir} (matches: ${res.matchCount})`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error(err?.stack || String(err));
    process.exit(1);
  });
}