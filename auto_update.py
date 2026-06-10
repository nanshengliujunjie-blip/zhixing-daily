#!/usr/bin/env python3
"""
知星全自动更新脚本 - 一键完成所有数据更新
用法: python3 ~/Desktop/知星/auto_update.py

更新内容:
  1. FALLBACK (index.html + dashboard.html) ← update_daily.py 逻辑
  2. user_orders.json ← Nexita dashboard 7 (fetch_orders.mjs)
  3. ad_users.json ← 归因工具 (fetch_attribution.mjs)
  4. consultant_data.json + consultant_all_data.json ← 重建
  5. git commit + push
"""
import json, re, subprocess, sys, os
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent
INDEX_HTML     = REPO / 'index.html'
DASHBOARD_HTML = REPO / 'dashboard.html'
AD_USERS       = REPO / 'ad_users.json'
USER_ORDERS    = REPO / 'user_orders.json'
USER_DATA      = REPO / 'user_data.json'
CONSULTANT_D   = REPO / 'consultant_data.json'
CONSULTANT_ALL = REPO / 'consultant_all_data.json'
FETCH_ORDERS   = REPO / 'fetch_orders.mjs'
FETCH_ATTR     = REPO / 'fetch_attribution.mjs'
UPDATE_DAILY   = REPO / 'update_daily.py'

today = date.today()
yesterday = today - timedelta(days=1)

print(f'\n{"="*55}')
print(f'  知星全自动更新  {today}')
print(f'{"="*55}\n')

# ═══════════════════════════════════════════════════════
# Step 1: 更新 FALLBACK（复用 update_daily.py）
# ═══════════════════════════════════════════════════════
print('【Step 1】更新 FALLBACK (index.html + dashboard.html)...')
result = subprocess.run([sys.executable, str(UPDATE_DAILY)], cwd=REPO)
if result.returncode != 0:
    print('  ⚠ update_daily.py 失败，继续其他步骤')
else:
    print('  ✓ index.html FALLBACK 已更新')
    # 同步 dashboard.html 的 FALLBACK（与 index.html 保持一致）
    idx = INDEX_HTML.read_text(encoding='utf-8')
    m = re.search(r'(const FALLBACK\s*=\s*\[)(.*?)(\];)', idx, re.DOTALL)
    if m:
        fb_content = m.group(2)
        dash = DASHBOARD_HTML.read_text(encoding='utf-8')
        dash2 = re.sub(r'(const FALLBACK\s*=\s*\[)(.*?)(\];)',
                       lambda x: x.group(1) + fb_content + x.group(3), dash, flags=re.DOTALL)
        DASHBOARD_HTML.write_text(dash2, encoding='utf-8')
        print('  ✓ dashboard.html FALLBACK 已同步')

# ═══════════════════════════════════════════════════════
# Step 2: 增量更新 user_orders.json
# ═══════════════════════════════════════════════════════
print('\n【Step 2】更新 user_orders.json...')

with open(USER_ORDERS) as f:
    orders_data = json.load(f)

# 找最新订单日期
all_dates = set()
for orders in orders_data.values():
    for o in orders:
        all_dates.add(o['d'])
last_order_date = max(all_dates) if all_dates else '2025-04-30'
fetch_from = (date.fromisoformat(last_order_date) + timedelta(days=1)).isoformat()
fetch_to   = yesterday.isoformat()

if fetch_from > fetch_to:
    print(f'  orders 已是最新 ({last_order_date})，跳过')
else:
    print(f'  拉取 {fetch_from} ~ {fetch_to} 的订单...')
    proc = subprocess.run(
        ['node', str(FETCH_ORDERS), f'--from={fetch_from}', f'--to={fetch_to}'],
        capture_output=True, text=True, timeout=300, cwd=REPO
    )
    if proc.returncode != 0:
        print(f'  ⚠ fetch_orders.mjs 失败: {proc.stderr[-300:]}')
    else:
        new_orders = 0
        done_info = {}
        for line in proc.stdout.strip().split('\n'):
            if not line: continue
            try:
                obj = json.loads(line)
            except:
                continue
            if obj.get('_done'):
                done_info = obj
                continue
            uid = obj['uid']
            entry = {'d': obj['d'], 'c': obj['c'], 'amt': obj['amt'], 'type': obj['type']}
            if uid not in orders_data:
                orders_data[uid] = []
            # 避免重复（同日期同订单）
            existing = {(o['d'], o.get('amt'), o.get('type')) for o in orders_data[uid]}
            key = (entry['d'], entry['amt'], entry['type'])
            if key not in existing:
                orders_data[uid].append(entry)
                new_orders += 1

        if new_orders > 0:
            with open(USER_ORDERS, 'w') as f:
                json.dump(orders_data, f, ensure_ascii=False, separators=(',', ':'))
            print(f'  ✓ user_orders.json 新增 {new_orders} 条（涉及 {len(orders_data)} 个用户）')
        else:
            print(f'  orders 无新数据')

# ═══════════════════════════════════════════════════════
# Step 3: 增量更新 ad_users.json（归因 Excel）
# ═══════════════════════════════════════════════════════
print('\n【Step 3】更新 ad_users.json...')

import openpyxl, tempfile

with open(AD_USERS) as f:
    ad = json.load(f)
existing_uids = set(str(u[0]) for u in ad['users'])
existing_reg_dates = set(u[10] for u in ad['users'] if u[10])
last_ad_date = max(existing_reg_dates) if existing_reg_dates else '2025-04-30'

fetch_attr_from = (date.fromisoformat(last_ad_date) + timedelta(days=1)).isoformat()
fetch_attr_to   = yesterday.isoformat()

with open(USER_DATA) as f:
    ud = json.load(f)
ud_map = {str(u[0]): u for u in (ud['users'] if 'users' in ud else ud)}

with open(USER_ORDERS) as f:
    orders_data_fresh = json.load(f)

total_ad_new = 0
if fetch_attr_from > fetch_attr_to:
    print(f'  ad_users 已是最新 ({last_ad_date})，跳过')
else:
    ds = fetch_attr_from
    while ds <= fetch_attr_to:
        print(f'  下载 {ds} 归因数据...')
        tmp_xlsx = os.path.join(tempfile.gettempdir(), f'attr_{ds}.xlsx')
        r = subprocess.run(
            ['node', str(FETCH_ATTR), f'--date={ds}', f'--out={tmp_xlsx}'],
            capture_output=True, text=True, timeout=180, cwd=REPO
        )
        if r.returncode != 0:
            print(f'    ⚠ 下载失败: {r.stderr[-200:]}')
        else:
            try:
                wb = openpyxl.load_workbook(tmp_xlsx, data_only=True)
                rows_xlsx = list(wb.active.iter_rows(values_only=True))
                new_uids = [str(r2[16]) for r2 in rows_xlsx[1:] if r2[3] == '新增注册' and r2[16]]
                truly_new = [u for u in new_uids if u not in existing_uids]
                for uid in truly_new:
                    uu = ud_map.get(uid)
                    gender = uu[2] if uu and len(uu) > 2 else 0
                    age    = uu[3] if uu and len(uu) > 3 else None
                    orders = orders_data_fresh.get(uid, [])
                    first_day = [o for o in orders if o['d'] == ds]
                    roi_pay = round(sum(o['amt'] for o in first_day), 2)
                    total_amt = round(sum(o['amt'] for o in orders), 2)
                    order_cnt = len(orders)
                    q_cnt  = sum(1 for o in orders if o.get('type') == '提问')
                    lm_cnt = sum(1 for o in orders if o.get('type') == '连麦')
                    zx_cnt = sum(1 for o in orders if o.get('type') == '咨询')
                    paid = [o for o in orders if o.get('amt', 0) > 0]
                    consultant = paid[0].get('c', '未知') if paid else '未知'
                    ad['users'].append([uid, gender, age, roi_pay, total_amt,
                                        order_cnt, q_cnt, lm_cnt, zx_cnt, consultant, ds])
                    existing_uids.add(uid)
                    total_ad_new += 1
                print(f'    新增 {len(truly_new)} 个投放用户')
                os.unlink(tmp_xlsx)
            except Exception as e:
                print(f'    ⚠ 解析失败: {e}')
        ds = (date.fromisoformat(ds) + timedelta(days=1)).isoformat()

if total_ad_new > 0:
    ad['users'].sort(key=lambda u: u[10] or '')
    with open(AD_USERS, 'w') as f:
        json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
    print(f'  ✓ ad_users.json 新增 {total_ad_new} 人（共 {len(ad["users"])} 人）')

# ═══════════════════════════════════════════════════════
# Step 4: 重建 consultant_data.json + consultant_all_data.json
# ═══════════════════════════════════════════════════════
print('\n【Step 4】重建 consultant 数据...')

with open(USER_ORDERS) as f:
    orders_data_final = json.load(f)
with open(AD_USERS) as f:
    ad_final = json.load(f)

# 投放用户 uid → reg_date
ad_uid_to_regdate = {str(u[0]): u[10] for u in ad_final['users'] if u[10]}

# consultant_data: 仅首日投放用户
daily = {}   # {date: {consultant: {amt, users: set, orders}}}
for uid, orders in orders_data_final.items():
    reg_date = ad_uid_to_regdate.get(uid)
    if not reg_date: continue
    for o in orders:
        if o['d'] != reg_date: continue   # 仅首日
        cons = o.get('c', '未知') or '未知'
        d = o['d']
        if d not in daily: daily[d] = {}
        if cons not in daily[d]: daily[d][cons] = {'amt': 0, 'users': set(), 'orders': 0}
        daily[d][cons]['amt'] += o['amt']
        daily[d][cons]['users'].add(uid)
        daily[d][cons]['orders'] += 1

daily_out = {}
for d, cons_map in daily.items():
    daily_out[d] = sorted(
        [{'name': c, 'amt': round(v['amt'], 2), 'users': len(v['users']), 'orders': v['orders']}
         for c, v in cons_map.items()],
        key=lambda x: -x['amt']
    )

# totals
totals = {}
for d, rows in daily_out.items():
    for r in rows:
        c = r['name']
        if c not in totals: totals[c] = {'amt': 0, 'users': 0, 'orders': 0}
        totals[c]['amt'] = round(totals[c]['amt'] + r['amt'], 2)
        totals[c]['users'] += r['users']
        totals[c]['orders'] += r['orders']

with open(CONSULTANT_D, 'w') as f:
    json.dump({'daily': daily_out, 'totals': totals}, f, ensure_ascii=False, separators=(',', ':'))
print(f'  ✓ consultant_data.json: {len(daily_out)} 天, {len(totals)} 个顾问')

# consultant_all_data: 所有付费用户（不限投放）
daily_all = {}
for uid, orders in orders_data_final.items():
    for o in orders:
        if o['amt'] <= 0: continue
        cons = o.get('c', '未知') or '未知'
        d = o['d']
        if d not in daily_all: daily_all[d] = {}
        if cons not in daily_all[d]: daily_all[d][cons] = {'amt': 0, 'users': set(), 'orders': 0}
        daily_all[d][cons]['amt'] += o['amt']
        daily_all[d][cons]['users'].add(uid)
        daily_all[d][cons]['orders'] += 1

daily_all_out = {}
for d, cons_map in daily_all.items():
    daily_all_out[d] = sorted(
        [{'name': c, 'amt': round(v['amt'], 2), 'users': len(v['users']), 'orders': v['orders']}
         for c, v in cons_map.items()],
        key=lambda x: -x['amt']
    )

totals_all = {}
for d, rows in daily_all_out.items():
    for r in rows:
        c = r['name']
        if c not in totals_all: totals_all[c] = {'amt': 0, 'users': 0, 'orders': 0}
        totals_all[c]['amt'] = round(totals_all[c]['amt'] + r['amt'], 2)
        totals_all[c]['users'] += r['users']
        totals_all[c]['orders'] += r['orders']

with open(CONSULTANT_ALL, 'w') as f:
    json.dump({'daily': daily_all_out, 'totals': totals_all}, f, ensure_ascii=False, separators=(',', ':'))
print(f'  ✓ consultant_all_data.json: {len(daily_all_out)} 天, {len(totals_all)} 个顾问')

# ═══════════════════════════════════════════════════════
# Step 5: Git commit + push
# ═══════════════════════════════════════════════════════
print('\n【Step 5】Git commit & push...')
files = ['index.html', 'dashboard.html', 'user_orders.json', 'ad_users.json',
         'consultant_data.json', 'consultant_all_data.json']
subprocess.run(['git', 'add'] + files, cwd=REPO, check=True)
msg = f'全量自动更新 {today}: orders+ad_users+consultant+FALLBACK'
try:
    subprocess.run(['git', 'commit', '-m', msg], cwd=REPO, check=True)
    subprocess.run(['git', 'push'], cwd=REPO, check=True)
    print('✅ 已推送到 GitHub Pages!')
except subprocess.CalledProcessError:
    print('  (无变更或 push 失败)')

print('\n✅ 全部更新完成！')
