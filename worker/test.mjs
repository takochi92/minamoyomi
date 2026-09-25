// node worker/test.mjs — 公式にはつながずに、解析・対象選び・保存の流れを確かめる
import assert from "node:assert/strict";
import W, { parseOdds3t, parseOddsTf, targets, jstNow, tick } from "./src/index.js";
const COMBOS = []; for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) for (let c = 1; c <= 6; c++) if (a !== b && b !== c && a !== c) COMBOS.push(`${a}-${b}-${c}`);
const cells = Array.from({ length: 120 }, (_, i) => `<td class="oddsPoint">${i}</td>`).join("");
const o = parseOdds3t(cells);
assert.equal(o[COMBOS.indexOf("1-2-3")], 0); assert.equal(o[COMBOS.indexOf("2-1-3")], 1); assert.equal(o[COMBOS.indexOf("1-2-4")], 6);
assert.deepEqual(parseOddsTf(["2.7","2.9","2.0","16.6","17.5","31.8","1.5-2.0"].map((x) => `<td class="oddsPoint">${x}</td>`).join("")), [2.7, 2.9, 2, 16.6, 17.5, 31.8]);
assert.equal(parseOdds3t("<td class=\"oddsPoint\">1</td>"), null);
const now = jstNow(new Date("2026-09-25T06:00:00Z")); // 15:00 JST
assert.equal(now.hm, "15:00");
const idx = { date: "20260925", venues: [{ jcd: "01", races: [{ rno: 1, deadline: "15:21" }, { rno: 2, deadline: "15:47" }] }, { jcd: "02", cancelled: true, races: [{ rno: 1, deadline: "15:05" }] }, { jcd: "03", races: [{ rno: 5, deadline: "14:59" }, { rno: 6, deadline: "15:30" }] }] };
assert.deepEqual(targets(idx, now).map((r) => `${r.jcd}-${r.rno}`), ["01-1", "03-6"]);
// 流れ全体（fetch と KV をまねる）
const kv = new Map(); const calls = [];
const env = { SITE_URL: "https://site", LIVE: { get: async (k) => (kv.has(k) ? JSON.parse(kv.get(k)) : null), put: async (k, v) => kv.set(k, v) } };
globalThis.fetch = async (url) => { calls.push(url); const u = String(url);
  if (u.includes("index.json")) return { ok: true, json: async () => idx };
  if (u.includes("odds3t")) return { ok: true, text: async () => cells };
  if (u.includes("oddstf")) return { ok: true, text: async () => ["2.7","2.9","2.0","16.6","17.5","31.8"].map((x) => `<td class="oddsPoint">${x}</td>`).join("") };
  return { ok: false, status: 404 }; };
for (let i = 0; i < 14; i++) await tick(env, new Date(Date.parse("2026-09-25T06:00:00Z") + i * 60e3));
const st = JSON.parse(kv.get("live:20260925"));
assert.equal(st.races["01-1"].snaps.length, 12); assert.equal(st.races["01-1"].first.t, "15:00"); assert.equal(st.races["01-1"].snaps.at(-1).t, "15:13");
assert.ok(calls.filter((u) => String(u).includes("boatrace")).length === 14 * 4);
const res = await W.fetch(new Request("https://w/live?race=20260925-01-1"), env);
const body = await res.json(); assert.equal(body.deadline, "15:21"); assert.equal(body.snaps.at(-1).o3.length, 120);
console.log("worker tests ok");
