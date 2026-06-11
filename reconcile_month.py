#!/usr/bin/env python3
"""
整月(2026-05-10 ~ 06-09)投放首日付费对账。
权威源: MTc4MTA4Mjc5NDQ2NCM1MzkjeGxzeA==.xlsx 「点击归因明细数据」sheet 的「首日付费」事件。
- 仅修正付费数据(u[3]首日付费/u[11]付费单数)，不新增注册用户、不动投放分母。
- 738 个付费 uid 全部已在 ad_users 内；金额单位 分→元。
- user_orders 同步重建付费日订单(逐单按 xlsx)，咨询师取原订单主咨询师，缺则 知小i。
- 不在 xlsx 首日付费名单但订单系统确有首日付费的用户(22个)保持不动。
投放聚合(表1表2 FALLBACK)不动。
"""
import openpyxl, json, re
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent
XLSX = '/Users/oulei/Downloads/MTc4MTA4Mjc5NDQ2NCM1MzkjeGxzeA==.xlsx'
DATE_RE = re.compile(r'^20\d{2}-\d{2}-\d{2}$')

# ---- 1. 解析 xlsx 首日付费 ----
wb = openpyxl.load_workbook(XLSX, read_only=True)
ws = wb['点击归因明细数据']
pay_orders = defaultdict(list)   # uid -> [元金额,...]
pay_day = {}                     # uid -> 付费日(=注册日)
for r in ws.iter_rows(min_row=2, values_only=True):
    if r[3] == '首日付费' and r[17] and r[16]:
        uid = str(r[16]); d = str(r[0])[:10]
        pay_orders[uid].append(round(r[17] / 100.0, 2))
        # 首日付费单日，取最早
        if uid not in pay_day or d < pay_day[uid]:
            pay_day[uid] = d
paid_uids = set(pay_orders)
total = round(sum(sum(v) for v in pay_orders.values()), 2)
print(f'[xlsx] 首日付费 {len(paid_uids)} 人, {sum(len(v) for v in pay_orders.values())} 笔, ¥{total}')

# ---- 2. 读数据 + 清脏 ----
orders = json.load(open(REPO / 'user_orders.json'))
ad = json.load(open(REPO / 'ad_users.json'))
admap = {str(u[0]): u for u in ad['users']}
removed = 0
for uid in list(orders):
    before = len(orders[uid])
    orders[uid] = [x for x in orders[uid] if isinstance(x.get('d'), str) and DATE_RE.match(x['d'])]
    removed += before - len(orders[uid])
    if not orders[uid]: del orders[uid]
orders.pop('用户uid', None)
print(f'[clean] 清除非法记录 {removed} 条')

# ---- 3. 逐户对账 ----
fixed_o = fixed_ad = skipped = 0
for uid in paid_uids:
    if uid not in admap:
        continue  # 全部已在 ad；保险跳过
    reg_day = pay_day[uid]
    target = round(sum(pay_orders[uid]), 2)
    cnt = len(pay_orders[uid])
    existing = orders.get(uid, [])
    cur_day = [x for x in existing if x['d'] == reg_day]
    cur_paid = round(sum(x['amt'] for x in cur_day if x['amt'] > 0), 2)

    # user_orders: 仅当与 xlsx 不一致才重建
    if not (abs(cur_paid - target) < 0.01 and cur_paid > 0):
        cons_cand = [x['c'] for x in cur_day if x.get('c') and x['c'] != '未知']
        consultant = cons_cand[0] if cons_cand else '知小i'
        au = admap[uid]
        gender = (cur_day[0].get('gender') if cur_day else None)
        age = (cur_day[0].get('age') if cur_day else None)
        if gender is None: gender = au[1] if len(au) > 1 else 0
        if age is None: age = au[2] if len(au) > 2 else 0
        otype = (cur_day[0].get('type') if cur_day else None) or '提问'
        kept = [x for x in existing if x['d'] != reg_day]
        for amt in pay_orders[uid]:
            kept.append({'d': reg_day, 'c': consultant, 'amt': amt,
                         'type': otype, 'gender': gender, 'age': age})
        orders[uid] = kept
        fixed_o += 1

    # ad_users: 设首日付费/付费单数
    u = admap[uid]
    if (u[3] or 0) != target or (len(u) > 11 and u[11] != cnt):
        u[3] = target
        u[4] = round(max(u[4] or 0, target), 2)
        u[5] = max(u[5] or 0, cnt)
        if len(u) <= 11: u.append(cnt)
        else: u[11] = cnt
        fixed_ad += 1
    else:
        skipped += 1

print(f'[orders] 重建付费日 {fixed_o} 户  [ad_users] 修正 {fixed_ad} 户  已对 {skipped} 户')

json.dump(orders, open(REPO / 'user_orders.json', 'w'), ensure_ascii=False)
json.dump(ad, open(REPO / 'ad_users.json', 'w'), ensure_ascii=False)

# ---- 4. 复核 ----
ad2 = json.load(open(REPO / 'ad_users.json'))
by = defaultdict(lambda: [0, 0.0])
for u in ad2['users']:
    if u[10] and '2026-05-10' <= u[10] <= '2026-06-09' and (u[3] or 0) > 0:
        by[u[10]][0] += 1; by[u[10]][1] += u[3]
tot_p = sum(v[0] for v in by.values()); tot_a = round(sum(v[1] for v in by.values()), 1)
print(f'\n[复核] 5/10~6/09 首日付费 {tot_p} 人, ¥{tot_a}（含22个订单系统确认的非xlsx首日付费用户）')
