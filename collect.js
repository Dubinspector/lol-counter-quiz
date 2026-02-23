import { setTimeout as sleep } from "node:timers/promises";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pLimit from "p-limit";

const API_KEY = process.env.RIOT_API_KEY;
if (!API_KEY) throw new Error("Missing RIOT_API_KEY env var");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const OUT_DIR = path.join(__dirname, "out");
const RAW_DIR = path.join(OUT_DIR, "raw");

// EUW routing
const PLATFORM = "EUW1";   // league endpoints
const REGIONAL = "EUROPE"; // match-v5

// queues
const QUEUE_RANKED_SOLO = 420;
const QUEUE_NORMAL_DRAFT = 400;
const ALLOWED_QUEUES = new Set([QUEUE_RANKED_SOLO, QUEUE_NORMAL_DRAFT]);

// Silver+ tiers supported by /entries
const TIERS = ["SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"];
const DIVISIONS = ["I", "II", "III", "IV"];

// sampling knobs
const PAGES_PER_DIV = 2;        // 1 page ~200 entries
const MAX_PLAYERS = 1400;       // unique puuids cap
const MATCH_IDS_PER_PUUID = 18; // take recent match ids, then filter by queue
const MAX_MATCHES_TOTAL = 2600; // cap match downloads

// rate limiting (100/120s => ~0.83 rps; safe 1/1300ms)
const BASE_DELAY_MS = 1300;
let lastTs = 0;

async function throttle() {
  const now = Date.now();
  const wait = Math.max(0, lastTs + BASE_DELAY_MS - now);
  if (wait) await sleep(wait);
  lastTs = Date.now();
}

async function riotFetch(url, { tries = 8 } = {}) {
  for (let attempt = 0; attempt < tries; attempt++) {
    await throttle();
    const res = await fetch(url, { headers: { "X-Riot-Token": API_KEY } });

    if (res.status === 429) {
      const ra = res.headers.get("retry-after");
      const ms = ra ? Math.ceil(Number(ra) * 1000) : (1500 * (attempt + 1));
      await sleep(ms);
      continue;
    }
    if (res.status >= 500) {
      await sleep(900 * (attempt + 1));
      continue;
    }
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${res.statusText} :: ${url} :: ${txt.slice(0,200)}`);
    }
    return res.json();
  }
  throw new Error(`Failed after retries: ${url}`);
}

const platBase = `https://${PLATFORM.toLowerCase()}.api.riotgames.com`;
const regBase = `https://${REGIONAL.toLowerCase()}.api.riotgames.com`;

async function getLeagueEntries(queue, tier, division, page) {
  const u = `${platBase}/lol/league/v4/entries/${queue}/${tier}/${division}?page=${page}`;
  return riotFetch(u);
}

async function getMatchIdsByPuuid(puuid, count) {
  const u = `${regBase}/lol/match/v5/matches/by-puuid/${puuid}/ids?start=0&count=${count}`;
  return riotFetch(u);
}

async function getMatch(matchId) {
  const u = `${regBase}/lol/match/v5/matches/${matchId}`;
  return riotFetch(u);
}

async function getTimeline(matchId) {
  const u = `${regBase}/lol/match/v5/matches/${matchId}/timeline`;
  return riotFetch(u);
}

function safeName(s) {
  return String(s).replace(/[^a-zA-Z0-9_-]+/g, "_");
}

async function saveJson(relPath, obj) {
  const full = path.join(RAW_DIR, relPath);
  await mkdir(path.dirname(full), { recursive: true });
  await writeFile(full, JSON.stringify(obj));
}

function tierToBucket(tier) {
  return String(tier || "").toLowerCase();
}

async function main() {
  await mkdir(RAW_DIR, { recursive: true });

  // --------- SEED players by PUUID directly from entries ---------
  const puuidToTier = {};
  const puuidOrder = [];
  let printedSchema = false;

  for (const tier of TIERS) {
    for (const div of DIVISIONS) {
      for (let page = 1; page <= PAGES_PER_DIV; page++) {
        console.log(`ENTRIES: ${tier} ${div} page ${page}`);
        const arr = await getLeagueEntries("RANKED_SOLO_5x5", tier, div, page);
        const n = Array.isArray(arr) ? arr.length : 0;
        console.log(`  -> got ${n}`);

        if (!printedSchema && n > 0) {
          printedSchema = true;
          console.log("ENTRY KEYS SAMPLE:", Object.keys(arr[0]));
          console.log("ENTRY PUUID SAMPLE:", arr[0]?.puuid);
        }

        for (const e of (arr || [])) {
          const puuid = e?.puuid;
          if (!puuid) continue;

          if (!puuidToTier[puuid]) {
            puuidToTier[puuid] = tierToBucket(tier);
            puuidOrder.push(puuid);
            if (puuidOrder.length >= MAX_PLAYERS) break;
          }
        }

        console.log(`  Unique players: ${puuidOrder.length}`);
        if (puuidOrder.length >= MAX_PLAYERS) break;
        if (n < 150) break;
      }
      if (puuidOrder.length >= MAX_PLAYERS) break;
    }
    if (puuidOrder.length >= MAX_PLAYERS) break;
  }

  console.log(`Players (unique puuid): ${puuidOrder.length}`);
  if (puuidOrder.length === 0) {
    console.log("STOP: no PUUIDs collected.");
    return;
  }

  await writeFile(path.join(OUT_DIR, "players.json"), JSON.stringify({ puuidToTier }, null, 2));

  // --------- Collect match IDs (dedupe) ---------
  const matchSet = new Set();

  for (let i = 0; i < puuidOrder.length; i++) {
    if (matchSet.size >= MAX_MATCHES_TOTAL) break;
    const puuid = puuidOrder[i];
    const tier = puuidToTier[puuid] || "silver_plus";

    console.log(`Match IDs ${i + 1}/${puuidOrder.length} (${tier})`);
    const ids = await getMatchIdsByPuuid(puuid, MATCH_IDS_PER_PUUID);

    for (const id of (ids || [])) {
      matchSet.add(id);
      if (matchSet.size >= MAX_MATCHES_TOTAL) break;
    }
  }

  const matchIds = [...matchSet];
  console.log(`Unique matchIds (pre-filter): ${matchIds.length}`);

  // --------- Download match + timeline; keep only queue 400/420 ---------
  const limit = pLimit(1);
  let saved = 0;
  let skippedQueue = 0;

  for (const matchId of matchIds) {
    await limit(async () => {
      console.log(`Downloading ${matchId} (${saved + 1}/${matchIds.length})`);
      const m = await getMatch(matchId);

      const q = m?.info?.queueId;
      if (!ALLOWED_QUEUES.has(q)) {
        skippedQueue++;
        return;
      }

      const dur = (m?.info?.gameDuration || 0) * 1000;
      if (dur < 10 * 60 * 1000) return;

      const t = await getTimeline(matchId);

      const rel = `${safeName(matchId)}.json`;
      await saveJson(`match/${rel}`, m);
      await saveJson(`timeline/${rel}`, t);
      saved++;
    });
  }

  await writeFile(path.join(OUT_DIR, "meta.json"), JSON.stringify({
    platform: PLATFORM,
    regional: REGIONAL,
    queues: [...ALLOWED_QUEUES],
    tiers: TIERS,
    divisions: DIVISIONS,
    collectedAt: new Date().toISOString(),
    players: puuidOrder.length,
    matchesSaved: saved,
    skippedQueue
  }, null, 2));

  console.log("DONE. Raw saved in out/raw/");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});