#!/usr/bin/env node
/**
 * 从 Nexita 表 1（首日行为）按一级/二级渠道拉取回收曲线。
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
const sourceBody = JSON.parse(readFileSync(resolve(repo, ".fallback_bodies.json"), "utf8")).b26;
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
function bodyFor(start, end) {
  const body = JSON.parse(sourceBody);
  body.page = { limit: 5000, offset: 0 };
  // 去掉渠道号，直接由表 1 按一级/二级渠道汇总，避免前端重复累加层级行。
  body.affiliate.groups = [
    { column: "ymd", isPivot: false },
    { column: "cc_level1_name", isPivot: false },
    { column: "cc_level2_name", isPivot: false },
  ];
  body.actions[0].orders = [
    { column: "ymd", order: "DESC", isValue: false },
    { column: "cc_level1_name", order: "DESC", isValue: false },
    { column: "cc_level2_name", order: "DESC", isValue: false },
  ];
  body.time = {
    start: { column: "ymd", value: start.replace(/-/g, "") },
    end: { column: "ymd", value: end.replace(/-/g, "") },
  };
  return body;
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
    const response = await context.request.post(url, { data: bodyFor(start, end), timeout: 60000 });
    const payload = await response.json();
    if (payload.dm_error !== 0) throw new Error(`${start}~${end}: ${payload.error_msg || "查询失败"}`);
    const rows = parseRows(payload.data?.data?.data || []);
    let kept = 0;
    for (const row of rows) {
      const rawDate = row["日期"] || "";
      const level1 = row["一级渠道"] || "";
      const level2 = row["二级渠道"] || "";
      const spend = number(row["消耗"]);
      if (!/^\d{8}$/.test(rawDate) || !level1 || !level2 || level1 === "汇总" || level2 === "汇总" || spend <= 0) continue;
      const date = `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6, 8)}`;
      const key = `${date}\u0000${level1}\u0000${level2}`;
      records.set(key, {
        date, level1, level2, channel: `${level1} / ${level2}`,
        spend, activate: number(row["激活设备数"]), reg: number(row["注册用户数"]),
        payAmount: number(row["首日充值金额"]), ltv3: number(row.ltv3), ltv7: number(row.ltv7),
        ltv15: number(row.ltv15), ltv30: number(row.ltv30),
      });
      kept++;
    }
    process.stderr.write(`[渠道ROI] ${start}~${end}: ${rows.length} 行，保留 ${kept} 行\n`);
  }
  const list = [...records.values()].sort((a, b) => a.date.localeCompare(b.date) || a.channel.localeCompare(b.channel));
  const dates = [...new Set(list.map(item => item.date))];
  process.stdout.write(JSON.stringify({
    updated: new Date().toISOString(), startDate, endDate,
    availableStartDate: dates[0] || null, availableEndDate: dates.at(-1) || null,
    source: "Nexita 表 1（首日行为）按一级/二级渠道汇总；ROI 使用各回收节点 LTV / 消耗计算。",
    list,
  }));
  await context.storageState({ path: statePath });
} finally {
  await browser.close();
}
