#!/usr/bin/env node

import fs from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { request } = require("playwright");

const SESSION = "/Users/oulei/.agents/skills/zhixing-data-query/.session/nexita-storage-state.json";
const OUTPUT = new URL("./risk_daily_data.js", import.meta.url);
const START = process.env.RISK_START || "2026-06-01";
const END = process.env.RISK_END || "2026-07-28";
const FOCUS_RULES = new Set([
  "数字+字母6-11字符",
  "正则-纯手机号-11位纯数字",
  "数字+字母",
  "数美-微信号",
]);
const API_URL = "https://console.nexita.net/risk/manager/server_log/query_server_log?env=online&domain_from=nexita&ticket=-&system_id=68";
const PAGE = "https://console.nexita.net/riskcontrol/identification-record/text-discern-log?app_key=zhixing";

function dateList(start, end) {
  const days = [];
  for (const cursor = new Date(`${start}T00:00:00Z`); cursor <= new Date(`${end}T00:00:00Z`); cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    days.push(cursor.toISOString().slice(0, 10));
  }
  return days;
}

function unwrap(value) {
  if (value && typeof value === "object") return value.text ?? value.label ?? value.value ?? value.key ?? "";
  return value ?? "";
}

function ruleInfo(value) {
  const text = String(unwrap(value)).trim();
  const match = text.match(/^(.*?)[「(](上线|灰度|下线)[」)]$/);
  return { name: (match ? match[1] : text).trim(), stage: match?.[2] || "未知" };
}

function queryBody(day, additions = {}) {
  return {
    app_name: "zhixing",
    page: 1,
    page_size: 1,
    snap_type: "1",
    start_time: `${day} 00:00:00`,
    end_time: `${day} 23:59:59`,
    ...additions,
  };
}

async function requestData(api, body) {
  const response = await api.post(API_URL, { data: body, timeout: 90_000 });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok() || Number(payload?.dm_error ?? payload?.code) !== 0) {
    throw new Error(`Risk API failed: ${payload?.error_msg || payload?.message || response.status()}`);
  }
  return payload.data || {};
}

async function rejectRows(api, day) {
  const rows = [];
  let page = 1;
  let total = 0;
  do {
    const result = await requestData(api, queryBody(day, { page, page_size: 10_000, content_risk_level: "reject" }));
    total = Number(result.total || 0);
    rows.push(...(Array.isArray(result.result) ? result.result : []));
    page += 1;
  } while (rows.length < total);
  return rows;
}

function summarizeRules(rows) {
  const requests = new Map();
  for (const row of rows) {
    const requestId = String(unwrap(row.request_id) || "");
    if (!requestId) continue;
    const rules = String(unwrap(row.content_hit_rules))
      .split(/[;；]/)
      .map(ruleInfo)
      .filter((rule) => rule.name);
    const existing = requests.get(requestId) || new Map();
    for (const rule of rules) existing.set(`${rule.name}\u0000${rule.stage}`, rule);
    requests.set(requestId, existing);
  }

  const strategies = new Map();
  let focusRejects = 0;
  for (const rules of requests.values()) {
    let hitsFocus = false;
    for (const rule of rules.values()) {
      const key = `${rule.name}\u0000${rule.stage}`;
      const current = strategies.get(key) || { ...rule, reject: 0 };
      current.reject += 1;
      strategies.set(key, current);
      if (FOCUS_RULES.has(rule.name)) hitsFocus = true;
    }
    if (hitsFocus) focusRejects += 1;
  }

  return {
    focusRejects,
    strategies: [...strategies.values()].sort((left, right) => left.name.localeCompare(right.name, "zh-CN")),
  };
}

async function mapWithConcurrency(items, limit, callback) {
  const output = new Array(items.length);
  let index = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (index < items.length) {
      const current = index++;
      output[current] = await callback(items[current], current);
    }
  }));
  return output;
}

const api = await request.newContext({
  storageState: SESSION,
  extraHTTPHeaders: {
    Accept: "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
    Origin: "https://console.nexita.net",
    Referer: PAGE,
  },
});

try {
  for (const origin of ["https://console.nexita.net", "https://sso.nexita.net"]) {
    await api.post(`${origin}/api/sso/authorize/company/login`, { data: { company_abbr: "twxy" }, timeout: 20_000 }).catch(() => null);
  }

  const days = await mapWithConcurrency(dateList(START, END), 3, async (date) => {
    const [all, pass, reject, rows] = await Promise.all([
      requestData(api, queryBody(date)),
      requestData(api, queryBody(date, { content_risk_level: "pass" })),
      requestData(api, queryBody(date, { content_risk_level: "reject" })),
      rejectRows(api, date),
    ]);
    const rules = summarizeRules(rows);
    const item = {
      date,
      total: Number(all.total || 0),
      pass: Number(pass.total || 0),
      reject: Number(reject.total || 0),
      focusRejects: rules.focusRejects,
      strategies: rules.strategies,
    };
    item.available = item.total > 0;
    console.log(`${date}: ${item.total} total, ${item.reject} rejects`);
    return item;
  });

  const data = {
    generatedAt: new Date().toISOString(),
    start: START,
    end: END,
    source: "Nexita 文本风控线上环境；按自然日聚合；策略拒绝数按 request_id 去重，同一请求可命中多个策略。",
    focusRules: [...FOCUS_RULES],
    days,
  };
  await fs.writeFile(OUTPUT, `const RISK_DAILY = ${JSON.stringify(data)};\n`, "utf8");
  console.log(JSON.stringify({ output: OUTPUT.pathname, start: START, end: END, days: days.length }, null, 2));
} finally {
  await api.dispose();
}
