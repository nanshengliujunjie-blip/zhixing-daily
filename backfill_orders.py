#!/usr/bin/env python3
"""
补拉 2026-06-03 ~ 2026-06-09 的全量订单（含0元）
目的：为近期注册的投放用户补全咨询师姓名
用法: python3 backfill_orders.py
"""
import json, subprocess, sys, os
from pathlib import Path
from datetime import date, timedelta

REPO = Path(__file__).parent
USER_ORDERS = REPO / 'user_orders.json'
FETCH_ORDERS = REPO / 'fetch_orders.mjs'
OUT_FILE = '/tmp/backfill_orders_out.ndjson'

# 补拉日期范围
FROM_DATE = '2026-06-03'
TO_DATE   = '2026-06-09'

print(f'补拉 {FROM_DATE} ~ {TO_DATE} 全量订单（含0元）...')

# 运行 fetch_orders.mjs，输出写到文件
proc = subprocess.Popen(
    ['node', str(FETCH_ORDERS), f'--from={FROM_DATE}', f'--to={TO_DATE}'],
    stdout=open(OUT_FILE, 'w'),
    stderr=subprocess.PIPE,
    text=True,
    cwd=REPO
)
_, stderr = proc.communicate(timeout=300)
if proc.returncode != 0:
    print('❌ fetch_orders.mjs 失败:')
    print(stderr[-500:])
    sys.exit(1)

# 读现有 orders
with open(USER_ORDERS) as f:
    orders_data = json.load(f)

# 解析输出
added = 0
done_info = {}
with open(OUT_FILE) as f:
    for line in f:
        line = line.strip()
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
        # 去重: (d, amt, type)
        existing = {(o['d'], o.get('amt'), o.get('type')) for o in orders_data[uid]}
        key = (entry['d'], entry['amt'], entry['type'])
        if key not in existing:
            orders_data[uid].append(entry)
            added += 1

print(f'从 API 拉取 {done_info.get("count","?")} 条，新增 {added} 条到 user_orders.json')

# 保存
with open(USER_ORDERS, 'w') as f:
    json.dump(orders_data, f, ensure_ascii=False, separators=(',', ':'))
print(f'✓ user_orders.json 已更新（共 {len(orders_data)} 个用户）')

# 同时更新 ad_users.json 中6/9用户的咨询师字段
print('\n补全 ad_users.json 中投放用户的咨询师字段...')
with open(REPO / 'ad_users.json') as f:
    ad = json.load(f)

updated_cons = 0
for u in ad['users']:
    uid = str(u[0])
    reg_date = u[10]
    if not reg_date or u[9] and u[9] != '未知':
        continue  # 已有咨询师，跳过
    orders = orders_data.get(uid, [])
    first_day_paid = [o for o in orders if o['d'] == reg_date and o.get('amt', 0) > 0 and o.get('c') and o['c'] != '未知']
    first_day_any  = [o for o in orders if o['d'] == reg_date and o.get('c') and o['c'] != '未知']
    best = first_day_paid or first_day_any
    if best:
        u[9] = best[0]['c']
        updated_cons += 1

print(f'补全了 {updated_cons} 个用户的咨询师')
if updated_cons > 0:
    with open(REPO / 'ad_users.json', 'w') as f:
        json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
    print('✓ ad_users.json 已保存')

# 清理临时文件
try:
    os.unlink(OUT_FILE)
except:
    pass

print('\n✅ 补拉完成！')
