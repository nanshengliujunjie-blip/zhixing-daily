#!/usr/bin/env node
/**
 * 从 Nexita 表 2（双新设备）按一级/二级渠道拉取回收曲线。
 * 用法: node fetch_channel_roi.mjs --start=2025-04-01 --end=2026-07-29
 */
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = [
  resolve(process.env.HOME, ".agents/skills/zhixing-data-query"),
  resolve(process.env.HOME, ".claude/skills/zhixing-data-query"),
].find(path => existsSync(resolve(path, ".session/nexita-storage-state.json")));
if (!root) throw new Error("未找到 Nexita 登录会话");
const { chromium } = require(resolve(root, "node_modules/playwright"));
const statePath = resolve(root, ".session/nexita-storage-state.json");
const repo = dirname(fileURLToPath(import.meta.url));
const sourceBodies = JSON.parse(readFileSync(resolve(repo, ".fallback_bodies.json"), "utf8"));
const url = "https://console.nexita.net/api_web/databusi/gtd/databusi/admin/compass/bd/v4/query/execute?power_module_id=1&app_key=zhixing";

function arg(name) {
  const value = process.argv.find(item => item.startsWith(`--${name}=`));
  return value ? value.slice(name.length + 3) : null;
}
function dayAfter(date, offset) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}
function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
function parseRows(rows) {
  if (!rows?.length) return [];
  const headers = rows[0].split("\t");
  return rows.slice(1).map(line => {
    const values = line.split("\t");
    return Object.fromEntries(headers.map((header, index) => [header, values[index]]));
  });
}
function channelName(level1, level2) {
  return level1 === 'IOS' && level2 === 'APPSTORE' ? 'iOS / AppStore' : `${level1} / ${level2}`;
}
function bodyFor(sourceBody, table, start, end) {
  const body = JSON.parse(sourceBody);
  body.page = { limit: 5000, offset: 0 };
  const isTable2 = table === 'table2';
  // 去掉产品、代理商和渠道号，直接按一级/二级渠道汇总。
  body.affiliate.groups = [
    { column: isTable2 ? "dt" : "ymd", isPivot: false, alias: isTable2 ? "日" : "日期" },
    { column: "cc_level1_name", isPivot: false, alias: "一级渠道" },
    { column: "cc_level2_name", isPivot: false, alias: "二级渠道" },
  ];
  body.actions[0].orders = [
    { column: isTable2 ? "dt" : "ymd", order: "DESC", isValue: false },
    { column: "cc_level1_name", order: "DESC", isValue: false },
    { column: "cc_level2_name", order: "DESC", isValue: false },
  ];
  body.time = {
    start: { column: "ymd", value: start.replace(/-/g, "") },
    end: { column: "ymd", value: end.replace(/-/g, "") },
  };
  return body;
}
function appendRows(records, rows, table) {
  let kept = 0;
  for (const row of rows) {
    const rawDate = String(row["日"] || row["日期"] || row.dt || row.ymd || "").replace(/\D/g, "");
    const level1 = row["一级渠道"] || row.cc_level1_name || "";
    const level2 = row["二级渠道"] || row.cc_level2_name || "";
    const spend = number(table === 'table2' ? row["折后支出金额（元）"] : row["消耗"]);
    if (!/^\d{8}$/.test(rawDate) || !level1 || !level2 || level1 === "汇总" || level2 === "汇总") continue;
    const date = `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6, 8)}`;
    const key = `${date}\u0000${level1}\u0000${level2}`;
    if (table === 'table2') {
      if (spend <= 0) continue;
      records.set(key, {
        date, level1, level2, channel: `${level1} / ${level2}`,
        spend, activate: number(row["新增激活设备数"]), reg: number(row["净注册设备数"]),
        payAmount: 0, paidUsers: 0, table1Reg: 0, aiQuestions: 0, enterRoom: 0, mic: 0,
        nextRetained: number(row["次日留存设备数"]), retentionReg: number(row["净注册设备数"]),
        ltv3: number(row.LTV3), ltv7: number(row.LTV7), ltv15: number(row.LTV15), ltv30: number(row.LTV30),
      });
      kept++;
      continue;
    }
    const existing = records.get(key);
    if (existing) {
      // 表 1 是回收金额和首日行为的权威来源，即使其消耗为 0 也要覆盖这些字段。
      existing.payAmount = number(row["首日充值金额"]);
      existing.paidUsers = number(row["首日付费用户数"]);
      existing.table1Reg = number(row["注册用户数"]);
      existing.aiQuestions = number(row["首日ai提问用户数"]);
      existing.enterRoom = number(row["首日进房用户数"]);
      existing.mic = number(row["首日连麦用户数"]);
      existing.ltv3 = number(row.ltv3);
      existing.ltv7 = number(row.ltv7);
      existing.ltv15 = number(row.ltv15);
      existing.ltv30 = number(row.ltv30);
      continue;
    }
    // 表 2 尚无记录的历史日期，保留表 1 回退行；仅 AppStore 可作为无消耗行为渠道展示。
    const isAppStore = level1 === 'IOS' && level2 === 'APPSTORE';
    if (spend <= 0 && !isAppStore) continue;
    records.set(key, {
      date, level1, level2, channel: channelName(level1, level2),
      spend, activate: number(row["激活设备数"]), reg: isAppStore ? 0 : number(row["注册用户数"]),
      payAmount: number(row["首日充值金额"]), paidUsers: number(row["首日付费用户数"]), table1Reg: number(row["注册用户数"]), aiQuestions: number(row["首日ai提问用户数"]),
      enterRoom: number(row["首日进房用户数"]), mic: number(row["首日连麦用户数"]),
      nextRetained: 0, retentionReg: 0,
      ltv3: number(row.ltv3), ltv7: number(row.ltv7), ltv15: number(row.ltv15), ltv30: number(row.ltv30),
    });
    kept++;
  }
  return kept;
}

const startDate = arg("start") || dayAfter(new Date().toISOString().slice(0, 10), -180);
const endDate = arg("end") || new Date().toISOString().slice(0, 10);
const state = JSON.parse(readFileSync(statePath, "utf8"));
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  storageState: state,
  extraHTTPHeaders: {
    "Content-Type": "application/json;charset=UTF-8",
    Origin: "https://console.nexita.net",
    Referer: "https://console.nexita.net/databusi/func/dashboard?app_key=zhixing&id=12",
    "X-Proxy-App-Key": "zhixing",
    "X-Proxy-Cluster": "tx-bj3",
  },
});

try {
  const records = new Map();
  for (let start = startDate; start <= endDate; start = dayAfter(start, 31)) {
    const end = dayAfter(start, 30) < endDate ? dayAfter(start, 30) : endDate;
    const stats = [];
    for (const [table, sourceBody] of [['table2', sourceBodies.b25], ['table1', sourceBodies.b26]]) {
      const response = await context.request.post(url, { data: bodyFor(sourceBody, table, start, end), timeout: 60000 });
      const payload = await response.json();
      if (payload.dm_error !== 0) throw new Error(`${start}~${end} ${table}: ${payload.error_msg || "查询失败"}`);
      const rows = parseRows(payload.data?.data?.data || []);
      stats.push(`${table} ${rows.length}/${appendRows(records, rows, table)}`);
    }
    process.stderr.write(`[渠道ROI] ${start}~${end}: ${stats.join('；')}\n`);
  }
  const list = [...records.values()].sort((a, b) => a.date.localeCompare(b.date) || a.channel.localeCompare(b.channel));
  const dates = [...new Set(list.map(item => item.date))];
  process.stdout.write(JSON.stringify({
    updated: new Date().toISOString(), startDate, endDate,
    availableStartDate: dates[0] || null, availableEndDate: dates.at(-1) || null,
    source: "消耗、次日留存：表 2；充值、付费率、进房、连麦、AI 提问、ROI 回收金额：表 1；ROI = 表 1 回收金额 / 表 2 消耗。iOS / AppStore 无表 2 消耗，仅展示行为数据。",
    list,
  }));
  await context.storageState({ path: statePath });
} finally {
  await browser.close();
}
