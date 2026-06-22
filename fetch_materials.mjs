#!/usr/bin/env node
/**
 * 从 Nexita CHL 拉取推广素材数据，输出 JSON 到 stdout
 * 用法:
 *   node fetch_materials.mjs --days=7
 *   node fetch_materials.mjs --start=2026-06-15 --end=2026-06-22
 */

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(
  resolve(process.env.HOME, ".claude/skills/zhixing-data-query/node_modules/playwright")
);
const STATE_PATH = resolve(
  process.env.HOME, ".claude/skills/zhixing-data-query/.session/nexita-storage-state.json"
);

function arg(name) {
  const hit = process.argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
}

const days = parseInt(arg("days") || "7");
const today = new Date().toISOString().slice(0, 10);
const defaultStart = new Date(Date.now() - (days - 1) * 86400000).toISOString().slice(0, 10);
const startDate = arg("start") || defaultStart;
const endDate = arg("end") || today;

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

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ storageState: state });

const allItems = [];
let page = 1;
const size = 100;

while (true) {
  const url = `https://console.nexita.net/api_web/chl/gtd/chl/api/material/media_material_list` +
    `?id=0&material_name=&customer_id=&app_id=&agent_id=&media_id=` +
    `&special=[]&order=[]&page=${page}&size=${size}` +
    `&start_date=${startDate}&end_date=${endDate}&data_type=1&ticket=`;

  const resp = await ctx.request.get(url, {
    headers: {
      "X-Proxy-App-Key": "zhixing",
      "Referer": "https://console.nexita.net/chl/smart-data/base/promote-material",
    },
  });
  const data = await resp.json();

  if (data.dm_error !== 0 || !data.data?.list) {
    process.stderr.write(`API error: ${JSON.stringify(data)}\n`);
    break;
  }

  const list = data.data.list;
  allItems.push(...list);
  process.stderr.write(`  page ${page}: ${list.length} 条 (共 ${data.data.total})\n`);

  if (allItems.length >= data.data.total || list.length < size) break;
  page++;
}

await browser.close();

// 只保留看板需要的字段
const output = allItems.map(m => ({
  id: m.id,
  dt: m.dt,
  media: m.media_name,
  name: m.material_name,
  url: m.material_url,
  type: m.material_type,  // 2=视频
  cost: m.cost,
  show: m.show_num,
  click: m.click,
  active: m.active,
  reg: m.register,
  pay_amt: m.attr_purchase_money,
  roi: m.roi,
  ctr: m.click_rate,
  reg_rate: m.register_rate,
  reg_cost: m.register_cost,
  cpm: m.cpm,
}));

process.stdout.write(JSON.stringify({ updated: new Date().toISOString(), startDate, endDate, list: output }));
