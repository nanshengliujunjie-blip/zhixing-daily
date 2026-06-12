#!/usr/bin/env node
/**
 * 通过 Nexita compass API 拉取 表1(首日行为,chart26) + 表2(双新设备,chart25) 的"汇总"行，
 * 输出某日 FALLBACK(营销总览/日报) 所需字段。替代原来不可靠的 SQL 路径(update_daily.py)。
 *
 * 用法:
 *   node fetch_fallback.mjs --date=2026-06-10
 *   node fetch_fallback.mjs --dates=2026-06-10,2026-06-11
 *   node fetch_fallback.mjs --from=2026-06-01 --to=2026-06-11
 * 输出(stdout, NDJSON 每行一天): {"date":"...","spend":..,"activate":..,"reg":..,"ai":..,
 *   "enterRoom":..,"mic":..,"payCount":..,"payAmount":..,"nextRetention":..,
 *   "roi3":..,"roi7":..,"roi15":..,"roi30":..,"roi60":..,"roi90":..,"roi120":..,"roi150":..,"roi180":..}
 * 某天表1未出则该天跳过(不输出)。失败时 stderr 写错误并 exit 1。
 *
 * 字段口径(与历史 FALLBACK 一致):
 *   spend = 表2 折后支出金额（元）
 *   activate/reg/ai/enterRoom/mic/payCount/payAmount = 表1 汇总
 *   nextRetention + roiCurve[1..] (ROI3/7/15/30/...) = 表2 汇总
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(
  resolve(process.env.HOME, ".claude/skills/zhixing-data-query/node_modules/playwright")
);
const STATE_PATH = resolve(
  process.env.HOME, ".claude/skills/zhixing-data-query/.session/nexita-storage-state.json"
);
const REPO = dirname(fileURLToPath(import.meta.url));
const BODIES = JSON.parse(readFileSync(resolve(REPO, ".fallback_bodies.json"), "utf8"));

const EXECUTE_URL = "https://console.nexita.net/api_web/databusi/gtd/databusi/admin/compass/bd/v4/query/execute?power_module_id=1&app_key=zhixing";
const EXTRA_HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Content-Type": "application/json;charset=UTF-8",
  "Origin": "https://console.nexita.net",
  "Referer": "https://console.nexita.net/databusi/func/dashboard?app_key=zhixing&id=12",
  "X-Proxy-App-Key": "zhixing",
  "X-Proxy-Cluster": "tx-bj3",
};

function arg(name) {
  const hit = process.argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
}
function dateList() {
  const single = arg("date");
  if (single) return [single];
  const csv = arg("dates");
  if (csv) return csv.split(",").map(s => s.trim()).filter(Boolean);
  const from = arg("from"), to = arg("to") || new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (from) {
    const out = []; let d = new Date(from + "T00:00:00");
    const end = new Date(to + "T00:00:00");
    while (d <= end) { out.push(d.toISOString().slice(0, 10)); d.setDate(d.getDate() + 1); }
    return out;
  }
  return [new Date(Date.now() - 86400000).toISOString().slice(0, 10)];
}
const DATES = dateList();

function storageStateWithProjectContext() {
  const state = JSON.parse(readFileSync(STATE_PATH, "utf8"));
  const PROJECT_COOKIES = {
    nexita_company_abbr_v1: "twxy",
    nexita_pdl_key: "cop.twxy_owt.inno_pdl.zhixing",
    save_project_key: "zhixing",
  };
  const cookies = Array.isArray(state.cookies) ? state.cookies : [];
  for (const [name, value] of Object.entries(PROJECT_COOKIES)) {
    const ex = cookies.find(c => c.name === name && /\.?nexita\.net$/.test(c.domain || ""));
    if (ex) ex.value = value;
    else cookies.push({ name, value, domain: ".nexita.net", path: "/", expires: -1 });
  }
  state.cookies = cookies;
  return state;
}

function num(v) {
  if (v === undefined || v === null) return null;
  const s = String(v).trim();
  if (s === "" || s === "null" || s === "—") return null;
  const f = parseFloat(s);
  return isNaN(f) ? null : f;
}

// 把响应解析成 [{header:value}] 行对象数组；第一行是表头(中文别名)
function parseRows(rows) {
  if (!rows || !rows.length) return [];
  const header = rows[0].split("\t");
  return rows.slice(1).map(r => {
    const cols = r.split("\t");
    const o = {};
    header.forEach((h, i) => { o[h] = cols[i]; });
    return o;
  });
}

async function query(ctx, baseBody, ymd) {
  const body = JSON.parse(JSON.stringify(baseBody));
  body.isCount = false;
  body.page = { limit: 5000, offset: 0 };
  body.time = { start: { column: "ymd", value: ymd }, end: { column: "ymd", value: ymd } };
  const resp = await ctx.request.post(EXECUTE_URL, { data: body, timeout: 60000 });
  const json = await resp.json();
  if (json.dm_error !== 0) throw new Error(`compass错误: ${json.error_msg}`);
  return parseRows(json.data?.data?.data || []);
}

// 找"汇总"行：表1 cc列='汇总'；表2 产品列='汇总'(或第一行总计)
function findSum(rows, keyCol) {
  return rows.find(r => r[keyCol] === "汇总") || rows[0] || null;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    storageState: storageStateWithProjectContext(),
    extraHTTPHeaders: EXTRA_HEADERS,
  });
  const b26 = JSON.parse(BODIES.b26), b25 = JSON.parse(BODIES.b25);
  try {
    for (const date of DATES) {
      const ymd = date.replace(/-/g, "");
      const r1 = await query(ctx, b26, ymd);
      const s1 = findSum(r1, "cc");
      if (!s1 || num(s1["注册用户数"]) === null) {
        process.stderr.write(`[fallback] ${date} 表1未出，跳过\n`);
        continue;
      }
      const r2 = await query(ctx, b25, ymd);
      const s2 = findSum(r2, "产品");
      const out = {
        date,
        spend: num((s2 || {})["折后支出金额（元）"]),
        nextRetention: num((s2 || {})["次日留存率"]),
        roi3: num((s2 || {})["ROI3"]), roi7: num((s2 || {})["ROI7"]), roi15: num((s2 || {})["ROI15"]),
        roi30: num((s2 || {})["ROI30"]), roi60: num((s2 || {})["ROI60"]), roi90: num((s2 || {})["ROI90"]),
        roi120: num((s2 || {})["ROI120"]), roi150: num((s2 || {})["ROI150"]), roi180: num((s2 || {})["ROI180"]),
        activate: num(s1["激活设备数"]),
        reg: num(s1["注册用户数"]),
        ai: num(s1["首日ai提问用户数"]),
        enterRoom: num(s1["首日进房用户数"]),
        mic: num(s1["首日连麦用户数"]),
        payCount: num(s1["首日付费用户数"]),
        payAmount: num(s1["首日充值金额"]),
      };
      process.stdout.write(JSON.stringify(out) + "\n");
    }
    // 保存轮换后的会话(关键：避免下次失效)
    try { await ctx.storageState({ path: STATE_PATH }); } catch {}
  } finally {
    await browser.close();
  }
}
main().catch(e => { process.stderr.write(`[fallback] 失败: ${e.message}\n`); process.exit(1); });
