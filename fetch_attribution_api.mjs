#!/usr/bin/env node
// 日报专用：通过已有 Nexita 接口生成报表，以日期、产品和唯一备注匹配本次任务。
import {createRequire} from 'node:module';
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';

export function matchesReport(row, date, remark) {
  return Number(row.app_id) === 135 && row.start_time === `${date} 00:00:00` &&
    row.end_time === `${date} 23:59:59` && row.query_type === '1,2' && row.remark === remark;
}

function arg(name) {
  return process.argv.find(value => value.startsWith(`--${name}=`))?.slice(name.length + 3);
}

async function main() {
  const date = arg('date');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '')) throw new Error('需要 --date=YYYY-MM-DD');
  const outPath = arg('out') || resolve(`attr_${date}.xlsx`);
  const root = ['.agents', '.claude'].map(dir => resolve(process.env.HOME, dir, 'skills/zhixing-data-query'))
    .find(dir => existsSync(resolve(dir, '.session/nexita-storage-state.json')));
  if (!root) throw new Error('未找到 Nexita 会话，请先登录');
  const require = createRequire(import.meta.url);
  const {request} = require(resolve(root, 'node_modules/playwright'));
  const state = JSON.parse(readFileSync(resolve(root, '.session/nexita-storage-state.json'), 'utf8'));
  for (const [name, value] of Object.entries({nexita_company_abbr_v1:'twxy',
    nexita_pdl_key:'cop.twxy_owt.inno_pdl.zhixing', save_project_key:'zhixing'})) {
    const cookies = state.cookies.filter(cookie => cookie.name === name && /\.?nexita\.net$/.test(cookie.domain));
    if (cookies.length) cookies.forEach(cookie => { cookie.value = value; });
    else state.cookies.push({name, value, domain:'.nexita.net', path:'/', expires:-1});
  }
  const api = await request.newContext({storageState:state, extraHTTPHeaders:{
    Accept:'application/json, text/plain, */*', 'X-Proxy-App-Key':'zhixing',
    Origin:'https://console.nexita.net', Referer:'https://console.nexita.net/chl/smart-data/channel/attribution-tool'
  }});
  const base = 'https://console.nexita.net/api_web/chl/gtd/chl/api/attrbution/detail';
  const remark = `daily:${date}:${randomUUID().slice(0, 8)}`;
  try {
    const added = await api.post(`${base}/add?ticket=`, {timeout:15000, data:{
      app_id:135, query_type:'1,2', remark, channel_code:'',
      start_time:`${date} 00:00:00`, end_time:`${date} 23:59:59`
    }});
    const result = await added.json();
    if (!added.ok() || Number(result.dm_error) !== 0) throw new Error(`归因查询失败：${result.error_msg || '请检查登录'}`);
    console.error(`[归因] 已创建 ${date} 报表，等待本次任务完成`);
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      const response = await api.get(`${base}/list?app_id=135&query_status=&page=1&size=100&ticket=`, {timeout:15000});
      const payload = await response.json();
      if (!response.ok() || Number(payload.dm_error) !== 0) throw new Error(`归因列表失败：${payload.error_msg || '请检查登录'}`);
      const report = (payload.data?.list || []).find(row => matchesReport(row, date, remark));
      if (report && Number(report.query_status) === 2 && report.detail_file_url) {
        const download = await api.get(report.detail_file_url, {timeout:30000});
        const bytes = await download.body();
        if (!download.ok() || bytes[0] !== 0x50 || bytes[1] !== 0x4b) throw new Error('归因文件未正确生成');
        writeFileSync(outPath, bytes);
        console.error(`[归因] 已验证日期 ${date}，报表 ID ${report.id}`);
        console.log(outPath);
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    throw new Error(`${date} 归因报表尚未生成，下次自动补拉`);
  } finally {
    await api.dispose();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
