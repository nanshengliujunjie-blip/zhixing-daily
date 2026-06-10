#!/usr/bin/env node
/**
 * 从 Nexita dashboard 7 增量拉取订单数据，输出 NDJSON 到 stdout
 * 用法:
 *   node fetch_orders.mjs --from=2026-06-10 --to=2026-06-10
 *   node fetch_orders.mjs --from=2026-06-10          # to 默认昨天
 *
 * 每行输出一个 JSON 对象: {"uid":"xxx","d":"2026-06-10","c":"咨询师","amt":10,"type":"提问"}
 * 最后一行输出: {"_done":true,"count":N}
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
const EXECUTE_URL = "https://console.nexita.net/api_web/databusi/gtd/databusi/admin/compass/bd/v4/query/execute?power_module_id=1&app_key=zhixing";
const EXTRA_HEADERS = {
  "Accept": "application/json, text/plain, */*",
  "Content-Type": "application/json;charset=UTF-8",
  "Origin": "https://console.nexita.net",
  "Referer": "https://console.nexita.net/databusi/func/dashboard?app_key=zhixing&id=7",
  "X-Proxy-App-Key": "zhixing",
  "X-Proxy-Cluster": "tx-bj3",
};

function arg(name) {
  const hit = process.argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
}
function ymd(s) { return s.replace(/-/g, ""); }  // "2026-06-10" → "20260610"
function fmtDate(s) {                              // "20260610" → "2026-06-10"
  return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}`;
}

const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
const fromDate  = arg("from") || yesterday;
const toDate    = arg("to")   || yesterday;

if (!readFileSync(STATE_PATH, "utf8")) { process.stderr.write("no session\n"); process.exit(1); }
// 加入项目上下文 cookies（与 query.mjs 一致）
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

// 基础请求体（来自 dashboard 7 截获）
const BASE_BODY = {
  reportId: 15,
  queryType: "dataSet",
  dataSource: "zhixing",
  type: "detail",
  unit: "ymd",
  actions: [{
    table: "hive_062cb51d98ed7252e60ed224e81c203c_local",
    metrics: [
      { column: "ymd" },
      { column: "uid" },
      { column: "user_nick" },
      { column: "user_gender", function: "case when user_gender = 1 then '女'\nwhen user_gender = 2 then '男'\nelse '未知' end " },
      { column: "user_age" },
      { column: "source_desc" },
      { column: "stargazer_uid" },
      { column: "stargazer_nick" },
      { column: "reg_days" },
      { column: "order_id" },
      { column: "dice" },
      { column: "coin_num" },
      { column: "discount_payment" },
      { column: "started_at" },
      { column: "created_at" },
      { column: "updated_at" },
      { column: "reply_time_min" },
      { column: "status" },
    ],
    orders: [{ column: "ymd", order: "DESC" }],
  }],
  affiliate: { groups: [], filter: null },
  appendTime: false,
  pivot: false,
  showLabel: true,
  actionType: "report_query",
  datasetId: 14165,
  dashboardId: 7,
  power_module_id: 1,
};

async function executeQuery(ctx, body) {
  const resp = await ctx.request.post(EXECUTE_URL, {
    data: body,
    timeout: 30000,
  });
  const json = await resp.json();
  if (json.dm_error !== 0) throw new Error(`API错误: ${json.error_msg}`);
  return json.data?.data?.data || [];
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const storageState = storageStateWithProjectContext();
  const ctx = await browser.newContext({ storageState, extraHTTPHeaders: EXTRA_HEADERS });

  try {
    const time = {
      start: { value: ymd(fromDate), column: "ymd" },
      end:   { value: ymd(toDate),   column: "ymd" },
    };

    // 1. 先查总数
    const countRows = await executeQuery(ctx, { ...BASE_BODY, time, isCount: true, page: { limit: 1, offset: 0 } });
    const total = parseInt(countRows[1] || "0", 10);
    process.stderr.write(`[orders] ${fromDate} ~ ${toDate}: 共 ${total} 条订单\n`);

    if (total === 0) {
      process.stdout.write(JSON.stringify({ _done: true, count: 0 }) + "\n");
      return;
    }

    // 2. 分页拉取（每次 5000 条）
    const PAGE = 5001; // 5000 数据 + 1 表头（第一次有表头，后续页不确定，统一处理）
    let offset = 0;
    let count = 0;
    let headers = null;

    while (offset < total) {
      const rows = await executeQuery(ctx, {
        ...BASE_BODY, time,
        isCount: false,
        page: { limit: PAGE, offset },
      });

      for (const row of rows) {
        if (!headers) {
          // 第一行是表头
          headers = row.split("\t");
          continue;
        }
        const cols = row.split("\t");
        const uid     = String(cols[1]);
        const d       = fmtDate(cols[0]);
        const type    = cols[5] || "未知";   // source_desc → 订单类型
        const starNick = cols[7] || "未知";  // stargazer_nick → 咨询师
        const amt     = parseFloat(cols[11]) || 0;  // coin_num → 金额
        // 性别: API返回 '女'/'男'/'未知' → 存为 2/1/0
        const gStr    = cols[3] || "";
        const gender  = gStr === "女" ? 2 : gStr === "男" ? 1 : 0;
        const age     = parseInt(cols[4]) || null;  // user_age

        if (!uid || !d) continue;
        process.stdout.write(JSON.stringify({ uid, d, c: starNick, amt, type, gender, age }) + "\n");
        count++;
      }

      const fetched = rows.length - (offset === 0 ? 1 : 0); // 减去表头
      process.stderr.write(`[orders] 已拉取 ${offset + fetched}/${total}\n`);
      if (rows.length < PAGE) break;
      offset += fetched;
    }

    process.stdout.write(JSON.stringify({ _done: true, count }) + "\n");
  } finally {
    await browser.close();
  }
}

main().catch(e => { process.stderr.write(`[orders] 失败: ${e.message}\n`); process.exit(1); });
