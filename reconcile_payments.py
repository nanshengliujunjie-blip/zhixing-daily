#!/usr/bin/env python3
"""
捡漏：近期注册用户若"订单系统首日付费" > ad_users 记录的首日付费(u[3])，则补齐。
针对归因 xlsx 漏记的真实大单(如华为连麦)。只升不降——保住 xlsx 抓到的 AI 小额付费。
幂等：补齐后 u[3]==order_sum 不再变。由 auto_update.py 调用；也可单独跑。
用法: python3 reconcile_payments.py [--days=7]

口径(遵守既有规则):
- 付费金额=0 的订单不算付费(只累加 amt>0)。
- 首日 = 订单日期 == 注册日期(u[10])。
- 只在 order_sum > u[3] 时上调 u[3]/u[11]，不下调(避免抹掉 xlsx 的 AI 小额付费)。
"""
import json, sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent
AD_USERS = REPO / 'ad_users.json'
USER_ORDERS = REPO / 'user_orders.json'

def arg(name, default):
    for a in sys.argv[1:]:
        if a.startswith(f'--{name}='):
            return a.split('=', 1)[1]
    return default

def main():
    days = int(arg('days', '7'))
    today = date.today()
    window = {(today - timedelta(days=i)).isoformat() for i in range(0, days + 1)}

    with open(AD_USERS) as f:
        ad = json.load(f)
    users = ad['users'] if isinstance(ad, dict) else ad
    with open(USER_ORDERS) as f:
        uo = json.load(f)

    fixed = []
    for u in users:
        if len(u) < 11 or u[10] not in window:
            continue
        reg = u[10]
        recs = uo.get(str(u[0]), [])
        day_paid = [r for r in recs if r.get('d') == reg and (r.get('amt', 0) or 0) > 0]
        order_sum = round(sum(r.get('amt', 0) for r in day_paid), 2)
        cur = u[3] or 0
        if order_sum > cur + 0.01:
            u[3] = order_sum
            cnt = len(day_paid)
            if len(u) <= 11:
                u.append(cnt)
            else:
                u[11] = max(u[11] or 0, cnt)
            fixed.append((str(u[0]), cur, order_sum, u[12] if len(u) > 12 else ''))

    if fixed:
        with open(AD_USERS, 'w') as f:
            json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
        print(f'[reconcile] ✓ 捡漏 {len(fixed)} 笔（订单系统>记录）:')
        for uid, old, new, media in sorted(fixed, key=lambda x: -x[2])[:10]:
            print(f'    uid={uid} {old}→{new} {media}')
    else:
        print('[reconcile] 近期无漏记付费')

if __name__ == '__main__':
    main()
