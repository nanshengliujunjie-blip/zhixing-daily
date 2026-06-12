#!/usr/bin/env python3
"""
回填 ad_users.json 中近期注册用户的 gender / age（来自订单记录 fetch_orders）。
幂等：只处理"该日注册用户全部 gender=0"(=尚未回填)的近 N 天，回填后不再重复拉。
由 auto_update.py 调用，也可单独运行：python3 backfill_gender.py [--days=5]
"""
import json, subprocess, os, sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).parent
AD_USERS = REPO / 'ad_users.json'
FETCH_ORDERS = REPO / 'fetch_orders.mjs'

def arg(name, default):
    for a in sys.argv[1:]:
        if a.startswith(f'--{name}='):
            return a.split('=', 1)[1]
    return default

def main():
    days = int(arg('days', '5'))
    today = date.today()

    with open(AD_USERS) as f:
        ad = json.load(f)
    users = ad['users'] if isinstance(ad, dict) else ad

    # 按注册日聚合，找近 days 天里"完全没有 gender"的日期（尚未回填）
    from collections import defaultdict
    by_date = defaultdict(list)
    for u in users:
        if len(u) > 10 and u[10]:
            by_date[u[10]].append(u)

    window = {(today - timedelta(days=i)).isoformat() for i in range(1, days + 1)}
    pending = sorted(d for d in window
                     if d in by_date and not any((x[1] or 0) != 0 for x in by_date[d]))
    if not pending:
        print('[gender] 近期无待回填日期')
        return

    print(f'[gender] 待回填日期: {pending}')
    env = {**os.environ}
    for k in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy','ALL_PROXY','all_proxy'):
        env.pop(k, None)

    # 拉取这些日期的订单（一次范围查询）提取 uid->(gender,age)
    proc = subprocess.run(
        ['node', str(FETCH_ORDERS), f'--from={pending[0]}', f'--to={pending[-1]}'],
        capture_output=True, text=True, timeout=600, cwd=REPO, env=env
    )
    if proc.returncode != 0:
        print(f'[gender] ⚠ fetch_orders 失败: {proc.stderr[-300:]}')
        return

    profile = {}  # uid -> {g, a}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('_done'):
            continue
        uid = str(o['uid'])
        g = o.get('gender', 0)
        a = o.get('age')
        p = profile.setdefault(uid, {'g': 0, 'a': None})
        if g:
            p['g'] = g
        if a and a > 0:
            p['a'] = int(a)

    g_upd = a_upd = 0
    pending_set = set(pending)
    for u in users:
        if len(u) < 11 or u[10] not in pending_set:
            continue
        p = profile.get(str(u[0]))
        if not p:
            continue
        if p['g'] and u[1] != p['g']:
            u[1] = p['g']; g_upd += 1
        if p['a'] and (len(u) < 3 or u[2] != p['a']):
            u[2] = p['a']; a_upd += 1

    if g_upd or a_upd:
        with open(AD_USERS, 'w') as f:
            json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
        print(f'[gender] ✓ 回填 gender {g_upd} / age {a_upd}（{len(pending)} 天）')
    else:
        print('[gender] 无可回填数据（这些天用户均无订单画像）')

if __name__ == '__main__':
    main()
