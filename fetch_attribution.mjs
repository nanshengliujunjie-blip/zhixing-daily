#!/usr/bin/env node
/**
 * 自动从 Nexita 点击归因明细查询工具 下载指定日期的归因数据
 * 用法：
 *   node fetch_attribution.mjs --date=2026-06-09
 *   node fetch_attribution.mjs --date=2026-06-09 --out=/tmp/attr.xlsx
 *
 * 成功时最后一行输出下载文件路径
 * 依赖 ~/.claude/skills/zhixing-data-query/.session/nexita-storage-state.json
 */

import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(
  resolve(process.env.HOME, ".claude/skills/zhixing-data-query/node_modules/playwright")
);
const STATE_PATH = resolve(
  process.env.HOME, ".claude/skills/zhixing-data-query/.session/nexita-storage-state.json"
);
const TOOL_URL = "https://console.nexita.net/chl/smart-data/channel/attribution-tool";

function arg(name) {
  const hit = process.argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : null;
}

async function main() {
  const date    = arg("date") || new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  const outPath = arg("out")  || resolve(process.env.HOME, `Desktop/知星/_attr_${date}.xlsx`);
  const dateFrom = `${date} 00:00:00`;
  const dateTo   = `${date} 23:59:59`;

  console.log(`[归因] 日期: ${date}`);
  if (!existsSync(STATE_PATH)) { console.error("未找到 session，请先登录"); process.exit(1); }

  const storageState = JSON.parse(readFileSync(STATE_PATH, "utf8"));
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ storageState });
  const page = await ctx.newPage();

  try {
    await page.goto(TOOL_URL, { waitUntil: "networkidle", timeout: 30000 });
    if (page.url().includes("sso.nexita.net")) {
      console.error("session 已过期，请重新执行 zhixing-data-query 登录");
      process.exit(2);
    }

    // ── 1. 点 + 新增 ─────────────────────────────────────────
    await page.locator("button:has-text('新增')").first().click();
    await page.waitForTimeout(800);

    // ── 2. 填时间范围（键盘输入） ────────────────────────────
    const startInput = page.locator(".ant-picker-range input").first();
    await startInput.click();
    await page.waitForTimeout(200);
    await page.keyboard.type(dateFrom);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(200);

    const endInput = page.locator(".ant-picker-range input").nth(1);
    await endInput.click();
    await page.waitForTimeout(200);
    await page.keyboard.type(dateTo);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);

    // ── 3. 选产品：知星（Modal 内部的 ant-select） ───────────
    const modalSelect = page.locator(".ant-modal-body .ant-select").first();
    await modalSelect.click();
    await page.waitForTimeout(400);
    const zhixingOpt = page.locator(".ant-select-dropdown:visible .ant-select-item:has-text('知星')").first();
    if (await zhixingOpt.count() > 0) {
      await zhixingOpt.click();
      console.log("[归因] 已选产品: 知星");
    } else {
      // 打印可见选项
      const opts = await page.locator(".ant-select-dropdown:visible .ant-select-item").allTextContents();
      console.error("未找到知星选项，现有:", opts);
      await page.keyboard.press("Escape");
      process.exit(3);
    }
    await page.waitForTimeout(200);

    // ── 4. 勾选类型 ──────────────────────────────────────────
    // 勾：点击归因回传明细 + 真实付费用户统计明细
    const typeLabels = ["点击归因回传明细", "真实付费用户统计明细"];
    for (const label of typeLabels) {
      const cb = page.locator(`.ant-modal-body .ant-checkbox-wrapper:has-text('${label}')`);
      if (await cb.count() > 0) {
        const checked = await cb.locator("input").isChecked();
        if (!checked) {
          await cb.click();
          console.log(`[归因] 勾选类型: ${label}`);
        }
      }
    }
    await page.waitForTimeout(200);

    // ── 5. 点确定 ────────────────────────────────────────────
    const okBtn = page.locator(".ant-modal-footer .ant-btn-primary").first();
    await okBtn.click();
    console.log("[归因] 已提交，等待数据生成...");
    await page.waitForTimeout(2000);

    // ── 6. 等待导出按钮（最多 120s，每 8s 刷新） ────────────
    let exportBtn = null;
    for (let i = 0; i < 15; i++) {
      await page.reload({ waitUntil: "networkidle" });
      // 等表格真正渲染出来（不是 0px 占位行）
      try {
        await page.waitForSelector(".ant-table-tbody tr td:not([style*='height: 0'])", { timeout: 8000 });
      } catch {}

      // 找到第一个可见的"导出" span（最新一行）
      const spans = page.locator(".ant-table-tbody tr td span:has-text('导出'), .ant-table-tbody tr td a:has-text('导出')");
      const cnt = await spans.count();
      if (cnt > 0) {
        exportBtn = spans.first();
        console.log(`[归因] 数据就绪，找到 ${cnt} 个导出按钮`);
        break;
      }
      console.log(`[归因] 等待数据... ${(i+1)*8}s`);
      await page.waitForTimeout(8000);
    }

    if (!exportBtn) throw new Error("超时：120s 内数据未就绪");

    // ── 7. 下载 ──────────────────────────────────────────────
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 30000 }),
      exportBtn.click(),
    ]);
    await download.saveAs(outPath);
    console.log(`[归因] 下载完成: ${outPath}`);
    console.log(outPath);  // ← 最后一行供 Python 读取路径

  } finally {
    await browser.close();
  }
}

main().catch(e => { console.error("[归因] 失败:", e.message); process.exit(1); });
