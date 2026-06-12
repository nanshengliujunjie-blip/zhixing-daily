#!/usr/bin/env python3
"""
补充 ad_users.json 中的 gender / age / paid_order_cnt 字段
从 Nexita 重新拉取所有投放用户相关日期的订单，提取 gender 和 age
用法: python3 backfill_profiles.py
"""
import json, subprocess
from pathlib import Path
from datetime import date, timedelta

REPO = Path(__file__).parent
AD_USERS = REPO / 'ad_users.json'
FETCH_ORDERS = REPO / 'fetch_orders.mjs'
OUT_FILE = '/tmp/profiles_out.ndjson'

with open(AD_USERS) as f:
    ad = json.load(f)

# 找出所有投放用户注册日期范围
all_dates = sorted(set(u[10] for u in ad['users'] if u[10]))
from_date = all_dates[0]
to_date   = all_dates[-1]
print(f'投放用户日期范围: {from_date} ~ {to_date}, 共 {len(ad["users"])} 人')

# 构建 uid → 用户 index 映射
uid_to_idx = {str(u[0]): i for i, u in enumerate(ad['users'])}

# 分批拉（防止单次太大，按月拆分）
months = sorted(set(d[:7] for d in all_dates))
uid_gender = {}  # uid → gender (取最新的非0值)
uid_age    = {}  # uid → age   (取最新的非None值)
uid_paid_cnt = {}  # uid → paid order count

print(f'需要拉取的月份: {len(months)} 个')

for m in months:
    # 该月的起止日期
    days = sorted(d for d in all_dates if d.startswith(m))
    mfrom = days[0]
    mto   = days[-1]
    print(f'  拉取 {mfrom} ~ {mto}...')

    proc = subprocess.Popen(
        ['node', str(FETCH_ORDERS), f'--from={mfrom}', f'--to={mto}'],
        stdout=open(OUT_FILE, 'w'),
        stderr=subprocess.PIPE,
        text=True,
        cwd=REPO
    )
    _, stderr = proc.communicate(timeout=600)
    if proc.returncode != 0:
        print(f'    ⚠ 失败: {stderr[-200:]}')
        continue

    # 解析
    with open(OUT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = json.loads(line)
            except:
                continue
            if obj.get('_done'):
                print(f'    拉取 {obj.get("count","?")} 条')
                continue
            uid = obj['uid']
            if uid not in uid_to_idx:
                continue  # 不是投放用户，跳过
            g = obj.get('gender', 0)
            a = obj.get('age')
            amt = obj.get('amt', 0)
            # 更新 gender (取非0值)
            if g != 0:
                uid_gender[uid] = g
            # 更新 age (取非None值)
            if a and a > 0:
                uid_age[uid] = int(a)
            # paid order count
            if amt > 0:
                uid_paid_cnt[uid] = uid_paid_cnt.get(uid, 0) + 1

print(f'\n有 gender 数据: {len(uid_gender)}, 有 age 数据: {len(uid_age)}, 有付费订单: {len(uid_paid_cnt)}')

# 更新 ad_users.json
# 格式: [uid, gender, age, roi_pay_amt, total_amt, order_cnt, q_cnt, lm_cnt, zx_cnt, consultant, reg_date]
# 扩展到 12 个字段: 在末尾加 paid_order_cnt
updated_g = updated_a = updated_p = 0
for u in ad['users']:
    uid = str(u[0])
    # gender
    if uid in uid_gender:
        old_g = u[1] if len(u) > 1 else 0
        if uid_gender[uid] != old_g:
            u[1] = uid_gender[uid]
            updated_g += 1
    # age
    if uid in uid_age:
        old_a = u[2] if len(u) > 2 else None
        if uid_age[uid] != old_a:
            u[2] = uid_age[uid]
            updated_a += 1

print(f'更新 gender: {updated_g}, age: {updated_a}')

with open(AD_USERS, 'w') as f:
    json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
print('✓ ad_users.json 已保存')

import os
try: os.unlink(OUT_FILE)
except: pass
print('\n✅ 完成！')
