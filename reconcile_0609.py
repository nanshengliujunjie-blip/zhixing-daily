#!/usr/bin/env python3
"""
对账修复 2026-06-09 投放首日付费数据。
权威源：MTc4MTA1NjM5ODEwNyMyNTkjeGxzeA==.xlsx 的「真实付费用户统计明细」sheet。
- 清理 user_orders.json 的表头脏数据
- 按 xlsx 逐户重建 9 号付费订单（金额单位 分→元）
- 同步修正 ad_users.json 的 u[3]首日付费 / u[11]付费单数 / u[4]总额 / u[5]订单数
- 补 1 个不在 ad_users 的用户(2025581)
投放聚合(消耗/注册数)仍以表1表2(FALLBACK)为准，本脚本不动。
"""
import openpyxl, json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent
XLSX = '/Users/oulei/Downloads/MTc4MTA1NjM5ODEwNyMyNTkjeGxzeA==.xlsx'
D = '2026-06-09'

# ---- 1. 读 xlsx 真实付费 ----
wb = openpyxl.load_workbook(XLSX, read_only=True)
ws = wb['真实付费用户统计明细']
xlsx_orders = defaultdict(list)   # uid -> [元金额, ...]
for r in ws.iter_rows(min_row=2, values_only=True):
    uid, amt = r[13], r[14]
    if uid and amt is not None:
        xlsx_orders[str(uid)].append(round(amt / 100.0, 2))
paid_uids = set(xlsx_orders)
xlsx_total = round(sum(sum(v) for v in xlsx_orders.values()), 2)
print(f'[xlsx] 付费用户 {len(paid_uids)} 人, 订单 {sum(len(v) for v in xlsx_orders.values())} 笔, 合计 ¥{xlsx_total}')

# ---- 2. 读现有数据 ----
orders = json.load(open(REPO / 'user_orders.json'))
ad = json.load(open(REPO / 'ad_users.json'))
admap = {str(u[0]): u for u in ad['users']}

# ---- 3. 清理脏数据（仅删真正非法的：日期不是 202x-xx-xx 格式）----
import re as _re
DATE_RE = _re.compile(r'^20\d{2}-\d{2}-\d{2}$')
removed = 0
for uid in list(orders):
    before = len(orders[uid])
    orders[uid] = [x for x in orders[uid] if isinstance(x.get('d'), str) and DATE_RE.match(x['d'])]
    removed += before - len(orders[uid])
    if not orders[uid]:
        del orders[uid]
if '用户uid' in orders:
    del orders['用户uid']
print(f'[clean] 清除非法订单记录 {removed} 条')

# ---- 4. 逐户重建 9 号付费 ----
fixed_users = 0
for uid in paid_uids:
    target = round(sum(xlsx_orders[uid]), 2)
    existing = orders.get(uid, [])
    cur_9 = [x for x in existing if x['d'] == D]
    cur_paid = round(sum(x['amt'] for x in cur_9 if x['amt'] > 0), 2)
    if abs(cur_paid - target) < 0.01 and cur_paid > 0:
        continue  # 已正确，保留原始明细
    # 需要修复：确定咨询师 / 性别 / 年龄 / 类型
    cons_cand = [x['c'] for x in cur_9 if x.get('c') and x['c'] != '未知']
    consultant = cons_cand[0] if cons_cand else '知小i'   # AI 微付费默认 知小i
    au = admap.get(uid)
    gender = (cur_9[0].get('gender') if cur_9 else None)
    age = (cur_9[0].get('age') if cur_9 else None)
    if gender is None: gender = au[1] if au else 0
    if age is None: age = au[2] if au else 0
    otype = (cur_9[0].get('type') if cur_9 else None) or '提问'
    # 保留非 9 号记录，9 号按 xlsx 逐单重建
    kept = [x for x in existing if x['d'] != D]
    for amt in xlsx_orders[uid]:
        kept.append({'d': D, 'c': consultant, 'amt': amt, 'type': otype,
                     'gender': gender, 'age': age})
    orders[uid] = kept
    fixed_users += 1
print(f'[orders] 重建 9 号付费用户 {fixed_users} 户（其余已正确，保留原明细）')

json.dump(orders, open(REPO / 'user_orders.json', 'w'), ensure_ascii=False)

# ---- 5. 修正 ad_users.json ----
# 字段: [uid, gender, age, roi_pay_amt, total_amt, order_cnt, q, lm, zx, consultant, reg_date, paid_order_cnt]
added = 0
for uid in paid_uids:
    target = round(sum(xlsx_orders[uid]), 2)
    cnt = len(xlsx_orders[uid])
    if uid in admap:
        u = admap[uid]
        u[3] = target                              # 首日付费
        u[4] = round(max(u[4] or 0, target), 2)    # 总额不小于首日
        u[5] = max(u[5] or 0, cnt)                 # 订单数
        u[11] = cnt if len(u) > 11 else u.append(cnt)  # 付费单数
        if len(u) <= 11: u.append(cnt)
        if u[10] != D: u[10] = D                    # 首日付费 → reg_date 应为 9 号
    else:
        # 不在 ad_users，补一条（知小i / 提问 微付费）
        cons_cand = [x['c'] for x in orders.get(uid, []) if x['d']==D and x.get('c') and x['c']!='未知']
        consultant = cons_cand[0] if cons_cand else '知小i'
        ad['users'].append([int(uid), 0, 0, target, target, cnt, cnt, 0, 0,
                            consultant, D, cnt])
        added += 1
print(f'[ad_users] 修正首日付费 {len(paid_uids)-added} 户, 新增 {added} 户')

json.dump(ad, open(REPO / 'ad_users.json', 'w'), ensure_ascii=False)

# ---- 6. 复核 ----
ad2 = json.load(open(REPO / 'ad_users.json'))
day9 = [u for u in ad2['users'] if u[10] == D]
paid9 = [u for u in day9 if (u[3] or 0) > 0]
print(f'\n[复核] ad_users 9号: 注册名单 {len(day9)} 人, 首日付费 {len(paid9)} 人, '
      f'首充合计 ¥{round(sum(u[3] for u in paid9),2)}')
