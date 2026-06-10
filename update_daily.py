#!/usr/bin/env python3
"""
知星日报自动更新脚本
使用方式：关闭 VPN 后在终端运行：
    cd ~/Desktop/知星 && python3 update_daily.py

功能：
  1. 查询 Nexita 获取最新投放数据（表1 + 表2）
  2. 补充已有记录的 ROI3/ROI7/ROI15/ROI30 曲线
  3. 更新 index.html 的 FALLBACK 数组
  4. git commit + push 到 GitHub Pages
"""

import json, re, subprocess, sys, os
from datetime import date, timedelta
from pathlib import Path

# ── 路径配置 ─────────────────────────────────────────────────
SKILL_DIR  = Path.home() / '.claude/skills/zhixing-data-query'
INDEX_HTML = Path(__file__).parent / 'index.html'
REPO_DIR   = Path(__file__).parent
CONFIG     = Path(__file__).parent / '.update_config.json'

# ── 工具函数 ─────────────────────────────────────────────────
def run_sql(sql, timeout=90):
    """通过 query.mjs 执行 SQL，返回 {columns, rows}"""
    r = subprocess.run(
        ['node', 'scripts/query.mjs'],
        input=sql, capture_output=True, text=True,
        cwd=SKILL_DIR, timeout=timeout
    )
    if r.returncode != 0:
        raise RuntimeError(f'SQL 失败:\n{r.stderr[-800:]}')
    return json.loads(r.stdout)

def rows_to_dicts(result):
    cols = result['columns']
    return [dict(zip(cols, row)) for row in result['rows']]

def sv(v):
    """安全转为 float，0 或 null 返回 None"""
    if v is None or str(v).strip() in ('', 'null', 'nan', 'None'): return None
    try:
        f = float(v)
        return None if f == 0 else round(f, 6)
    except: return None

def pct(v):
    s = sv(v)
    return None if s is None else round(s * 100, 4)

# ── Step 1: 发现表名（首次运行 or 强制刷新） ──────────────────
def discover_tables(force=False):
    if not force and CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
        if cfg.get('table1') and cfg.get('table2'):
            print(f'[config] 表1={cfg["table1"]}, 表2={cfg["table2"]}')
            return cfg['table1'], cfg['table2']

    print('[discover] 通过字段名搜索广告归因表...')
    # 表2 特征字段：折后支出金额 + ROI3
    result2 = run_sql("""
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE column_name IN ('折后支出金额','折后支出金额（元）','ROI3','roi3','roi_3d')
        AND table_schema NOT IN ('information_schema','mysql','performance_schema','sys')
        ORDER BY table_schema, table_name
        LIMIT 50
    """)
    # 表1 特征字段：首日进房率 or 首日付费用户数
    result1 = run_sql("""
        SELECT table_schema, table_name, column_name
        FROM information_schema.columns
        WHERE column_name IN ('首日进房率','首日付费用户数','首日进房用户数','enter_room_rate')
        AND table_schema NOT IN ('information_schema','mysql','performance_schema','sys')
        ORDER BY table_schema, table_name
        LIMIT 50
    """)
    tables2 = rows_to_dicts(result2)
    tables1 = rows_to_dicts(result1)
    print(f'[discover] 表2候选: {list({f"{t["table_schema"]}.{t["table_name"]}" for t in tables2})}')
    print(f'[discover] 表1候选: {list({f"{t["table_schema"]}.{t["table_name"]}" for t in tables1})}')

    # 合并用于手动选择
    all_schemas = set()
    for t in tables2 + tables1: all_schemas.add(t['table_schema'])
    result = run_sql(f"""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ({','.join(f"'{s}'" for s in all_schemas) or "'__none__'"})
        ORDER BY table_schema, table_name
        LIMIT 200
    """) if all_schemas else run_sql("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema','mysql','performance_schema','sys')
        ORDER BY table_schema, table_name LIMIT 300
    """)
    tables = rows_to_dicts(result)
    for t in tables:
        print(f'  {t["table_schema"]}.{t["table_name"]}')

    # 打印所有表，带序号
    print(f'\n发现 {len(tables)} 张表：\n')
    for i, t in enumerate(tables):
        print(f'  [{i:3d}] {t["table_schema"]}.{t["table_name"]}')

    print('\n请根据以上列表，输入对应的序号或完整表名（schema.table_name）：')
    print('  表2 = 点击归因-双新设备 (含 ROI/次日留存 等列)')
    print('  表1 = 点击归因新用户首日行为数据 (含 进房/连麦/付费 等列)')
    print()

    def pick_table(label):
        val = input(f'输入 {label} 的序号或表名: ').strip()
        if val.isdigit():
            t = tables[int(val)]
            return f'{t["table_schema"]}.{t["table_name"]}'
        elif '.' in val:
            return val
        else:
            # 模糊匹配
            matches = [f'{t["table_schema"]}.{t["table_name"]}' for t in tables
                       if val.lower() in t['table_name'].lower()]
            if len(matches) == 1:
                print(f'  → 匹配到: {matches[0]}')
                return matches[0]
            elif len(matches) > 1:
                print('  匹配到多个，请选择序号:')
                for i, m in enumerate(matches): print(f'    [{i}] {m}')
                return matches[int(input('序号: '))]
            else:
                raise ValueError(f'找不到包含 "{val}" 的表')

    table2 = pick_table('表2(双新设备)')
    table1 = pick_table('表1(首日行为)')

    # 保存配置
    cfg = {'table1': table1, 'table2': table2}
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f'\n[config] 已保存: {cfg}')
    return table1, table2

# ── Step 2: 查询字段结构（首次运行） ──────────────────────────
def get_columns(table):
    schema, tname = table.split('.')
    result = run_sql(f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='{schema}' AND table_name='{tname}'
        ORDER BY ordinal_position
        LIMIT 100
    """)
    return {r[0]: r[1] for r in result['rows']}

# ── Step 3: 查询数据 ──────────────────────────────────────────
def query_table2(table2, start_date, end_date):
    """
    表2: 双新设备 - 查汇总行
    关键字段: 日(date), 折后支出金额(spend), 净注册设备数(reg),
              新增充值设备数(payCount), 当日充值金额(payAmount),
              ROI3, ROI7, ROI15, ROI30, ROI60, ROI90, ROI120, ROI150, ROI180,
              次日留存率(nextRetention), 新增充值设备次日留存率(pret),
              新增激活设备数(activate)
    """
    # 先探查字段名（可能有中文/英文变体）
    cols = get_columns(table2)
    print(f'[table2] 共 {len(cols)} 个字段')

    # 字段映射（根据实际字段名调整）
    def find_col(candidates):
        for c in candidates:
            if c in cols: return c
        return None

    col_date    = find_col(['日', 'dt', 'date', 'stat_date']) or '日'
    col_spend   = find_col(['折后支出金额', 'cost', 'spend', '折后支出金额（元）']) or '折后支出金额'
    col_reg     = find_col(['净注册设备数', 'reg_cnt', 'register_cnt']) or '净注册设备数'
    col_pay_cnt = find_col(['新增充值设备数', 'pay_cnt', 'charge_cnt']) or '新增充值设备数'
    col_pay_amt = find_col(['当日充值金额', 'charge_amt', 'pay_amount', '当日充值金额（元）']) or '当日充值金额'
    col_act     = find_col(['新增激活设备数', 'activate_cnt', 'act_cnt']) or '新增激活设备数'
    col_ret     = find_col(['次日留存率', 'retention_1d', 'next_day_retention']) or '次日留存率'
    col_pret    = find_col(['新增充值设备次日留存率', 'pay_retention_1d']) or '新增充值设备次日留存率'

    roi_cols = {
        'roi3':   find_col(['ROI3', 'roi_3', 'roi3']),
        'roi7':   find_col(['ROI7', 'roi_7', 'roi7']),
        'roi15':  find_col(['ROI15', 'roi_15', 'roi15']),
        'roi30':  find_col(['ROI30', 'roi_30', 'roi30']),
        'roi60':  find_col(['ROI60', 'roi_60', 'roi60']),
        'roi90':  find_col(['ROI90', 'roi_90', 'roi90']),
        'roi120': find_col(['ROI120', 'roi_120', 'roi120']),
        'roi150': find_col(['ROI150', 'roi_150', 'roi150']),
        'roi180': find_col(['ROI180', 'roi_180', 'roi180']),
    }

    # 过滤条件：只取汇总行（产品=ZHIXING 或 汇总，渠道=汇总）
    # 根据实际情况调整 WHERE 子句
    sql = f"""
        SELECT
            {col_date} as dt,
            SUM(CAST({col_spend} AS DOUBLE)) as spend,
            SUM(CAST({col_reg} AS BIGINT)) as reg,
            SUM(CAST({col_pay_cnt} AS BIGINT)) as payCount,
            SUM(CAST({col_pay_amt} AS DOUBLE)) as payAmount,
            SUM(CAST({col_act} AS BIGINT)) as activate,
            AVG(CAST({col_ret} AS DOUBLE)) as nextRetention,
            AVG(CAST({col_pret} AS DOUBLE)) as pret,
            {', '.join(f'AVG(CAST({v} AS DOUBLE)) as {k}' for k,v in roi_cols.items() if v)}
        FROM {table2}
        WHERE (产品 = 'ZHIXING' OR 产品 = '汇总')
          AND (一级渠道 = '汇总')
          AND (二级渠道 = '汇总')
          AND {col_date} BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY {col_date}
        ORDER BY {col_date}
    """
    print(f'[table2] 查询 {start_date} ~ {end_date}...')
    return rows_to_dicts(run_sql(sql))

def query_table1(table1, start_date, end_date):
    """
    表1: 首日行为 - 查汇总行
    关键字段: 日期(date, int 20260601), 注册用户数, 激活设备数,
              首日ai提问用户数, 首日进房用户数, 首日进房率,
              首日连麦用户数, 首日连麦率, 首日付费用户数, 首日充值金额
    """
    cols = get_columns(table1)
    print(f'[table1] 共 {len(cols)} 个字段')

    def find_col(candidates):
        for c in candidates:
            if c in cols: return c
        return None

    col_date  = find_col(['日期', 'dt', 'date', 'stat_date']) or '日期'
    col_reg   = find_col(['注册用户数', 'reg_cnt']) or '注册用户数'
    col_act   = find_col(['激活设备数', 'act_cnt']) or '激活设备数'
    col_ai    = find_col(['首日ai提问用户数', 'ai_cnt', 'first_day_ai']) or '首日ai提问用户数'
    col_room  = find_col(['首日进房用户数', 'enter_room_cnt']) or '首日进房用户数'
    col_roomr = find_col(['首日进房率', 'enter_room_rate']) or '首日进房率'
    col_mic   = find_col(['首日连麦用户数', 'mic_cnt']) or '首日连麦用户数'
    col_micr  = find_col(['首日连麦率', 'mic_rate']) or '首日连麦率'
    col_pay   = find_col(['首日付费用户数', 'pay_cnt', '首日付费人数']) or '首日付费用户数'
    col_amt   = find_col(['首日充值金额', 'pay_amount', '充值金额']) or '首日充值金额'

    # 日期列可能是 int(20260601) 或 string('2026-06-01')
    # 先尝试 int 格式
    s_int = int(start_date.replace('-', ''))
    e_int = int(end_date.replace('-', ''))

    sql = f"""
        SELECT
            {col_date} as dt,
            SUM(CAST({col_reg} AS BIGINT)) as reg,
            SUM(CAST({col_act} AS BIGINT)) as activate,
            SUM(CAST({col_ai} AS BIGINT)) as ai,
            SUM(CAST({col_room} AS BIGINT)) as enterRoom,
            AVG(CAST({col_roomr} AS DOUBLE)) as enterRoomRate,
            SUM(CAST({col_mic} AS BIGINT)) as mic,
            AVG(CAST({col_micr} AS DOUBLE)) as micRate,
            SUM(CAST({col_pay} AS BIGINT)) as payCount,
            SUM(CAST({col_amt} AS DOUBLE)) as payAmount
        FROM {table1}
        WHERE (cc = '汇总' OR cc IS NULL)
          AND (一级渠道 = '汇总')
          AND (二级渠道 = '汇总')
          AND CAST({col_date} AS BIGINT) BETWEEN {s_int} AND {e_int}
        GROUP BY {col_date}
        ORDER BY {col_date}
    """
    print(f'[table1] 查询 {start_date} ~ {end_date}...')
    return rows_to_dicts(run_sql(sql))

# ── Step 4: 合并数据，生成日报 entry ────────────────────────
def merge_entries(t1_rows, t2_rows):
    """合并表1和表2数据为日报格式"""
    # 表1按日期索引（日期是 int 格式 20260601）
    t1_map = {}
    for r in t1_rows:
        dt = str(r['dt'])
        if len(dt) == 8:  # 20260601
            ds = f'{dt[:4]}-{dt[4:6]}-{dt[6:]}'
        else:
            ds = dt[:10]
        t1_map[ds] = r

    entries = []
    for r2 in t2_rows:
        ds = str(r2['dt'])[:10]
        r1 = t1_map.get(ds, {})

        spend   = sv(r2.get('spend')) or 0
        reg     = int(r1.get('reg') or r2.get('reg') or 0)
        pay     = int(r1.get('payCount') or 0)
        payAmt  = sv(r1.get('payAmount')) or 0
        act     = int(r1.get('activate') or r2.get('activate') or 0)
        ai      = int(r1.get('ai') or 0)
        room    = int(r1.get('enterRoom') or 0)
        mic_n   = int(r1.get('mic') or 0)

        roi0 = round(payAmt / spend * 100, 4) if spend and payAmt else None

        # ROI 曲线：[D0, D3, D7, D15, D30, D60, D90, D120, D150, D180, ...null*6]
        roi_curve = [
            roi0,
            pct(r2.get('roi3')),
            pct(r2.get('roi7')),
            pct(r2.get('roi15')),
            pct(r2.get('roi30')),
            pct(r2.get('roi60')),
            pct(r2.get('roi90')),
            pct(r2.get('roi120')),
            pct(r2.get('roi150')),
            pct(r2.get('roi180')),
            None, None, None, None, None, None,  # D210~D360
        ]

        e = {
            'date':          ds,
            'spend':         round(spend, 2),
            'activate':      act,
            'reg':           reg,
            'regCost':       round(spend / reg, 2) if reg else None,
            'ai':            ai,
            'payCount':      pay,
            'payAmount':     round(payAmt, 2),
            'payCost':       round(spend / pay, 2) if pay else None,
            'payRate':       round(pay / reg * 100, 4) if reg and pay else None,
            'roi':           roi0,
            'enterRoom':     room,
            'enterRoomRate': pct(r1.get('enterRoomRate')),
            'mic':           mic_n,
            'micRate':       pct(r1.get('micRate')),
            'nextRetention': pct(r2.get('nextRetention')),
            'roiCurve':      roi_curve,
            'pret':          pct(r2.get('pret')),
        }
        entries.append(e)
    return entries

# ── Step 5: 更新 index.html ───────────────────────────────────
def update_index(new_entries, roi_updates):
    html = INDEX_HTML.read_text(encoding='utf-8')
    fb_match = re.search(r'const FALLBACK\s*=\s*\[(.*?)\];', html, re.DOTALL)
    existing = json.loads('[' + fb_match.group(1).rstrip(',').rstrip() + ']')

    # 建立 map，保留已有数据
    entry_map = {e['date']: e for e in existing}

    # 应用 ROI 曲线更新（补充已有记录的 D3/D7/D15/D30）
    slot_map = {3: 1, 7: 2, 15: 3, 30: 4, 60: 5, 90: 6, 120: 7, 150: 8, 180: 9}
    for ds, updates in roi_updates.items():
        if ds in entry_map:
            rc = entry_map[ds].get('roiCurve', [None]*16)
            while len(rc) < 16: rc.append(None)
            for days, val in updates.items():
                if val and rc[slot_map[days]] is None:
                    rc[slot_map[days]] = val
            entry_map[ds]['roiCurve'] = rc

    # 添加/覆盖新 entries
    added = updated = 0
    for e in new_entries:
        if e['date'] in entry_map:
            # 只更新 ROI 曲线和 nextRetention（保护已有数据）
            existing_e = entry_map[e['date']]
            rc = existing_e.get('roiCurve', [None]*16)
            new_rc = e['roiCurve']
            for i, v in enumerate(new_rc):
                if v is not None and (i >= len(rc) or rc[i] is None):
                    while len(rc) <= i: rc.append(None)
                    rc[i] = v
            existing_e['roiCurve'] = rc
            if e.get('nextRetention') and not existing_e.get('nextRetention'):
                existing_e['nextRetention'] = e['nextRetention']
            updated += 1
        else:
            entry_map[e['date']] = e
            added += 1

    entries = sorted(entry_map.values(), key=lambda e: e['date'])

    def to_js(v):
        if v is None: return 'null'
        if isinstance(v, bool): return 'true' if v else 'false'
        if isinstance(v, list): return '[' + ','.join(to_js(x) for x in v) + ']'
        if isinstance(v, str): return json.dumps(v)
        if isinstance(v, float):
            s = f'{v:.4f}'.rstrip('0').rstrip('.')
            return s
        return str(v)

    def entry_to_js(e):
        return '{' + ','.join(f'"{k}":{to_js(v)}' for k, v in e.items()) + '}'

    new_fb = ','.join(entry_to_js(e) for e in entries)
    today_str = date.today().strftime('%m%d')
    new_seed = f'v_auto_{today_str}'

    html2 = re.sub(r'(const FALLBACK\s*=\s*\[)(.*?)(\];)',
                   lambda m: m.group(1) + new_fb + m.group(3), html, flags=re.DOTALL)
    html2 = re.sub(r"SEED_VER\s*=\s*'[^']+'", f"SEED_VER='{new_seed}'", html2)

    INDEX_HTML.write_text(html2, encoding='utf-8')
    print(f'[index] 更新完成: 新增 {added} 条，ROI补充 {updated} 条，共 {len(entries)} 条')
    return added, updated

# ── Step 6: Git push ──────────────────────────────────────────
def git_push(added, updated):
    today = date.today().strftime('%Y-%m-%d')
    msg = f'日报自动更新 {today}：新增{added}条，ROI补充{updated}条'
    subprocess.run(['git', 'add', 'index.html'], cwd=REPO_DIR, check=True)
    subprocess.run(['git', 'commit', '-m', msg], cwd=REPO_DIR, check=True)
    subprocess.run(['git', 'push'], cwd=REPO_DIR, check=True)
    print(f'[git] 推送成功: {msg}')

# ── 主流程 ────────────────────────────────────────────────────
def main():
    force_discover = '--discover' in sys.argv
    today = date.today()

    print(f'\n{"="*50}')
    print(f'  知星日报自动更新  {today}')
    print(f'{"="*50}\n')

    # 1. 发现/加载表名
    table1, table2 = discover_tables(force=force_discover)

    # 2. 加载现有 FALLBACK，确定需要查询的日期范围
    html = INDEX_HTML.read_text(encoding='utf-8')
    fb_match = re.search(r'const FALLBACK\s*=\s*\[(.*?)\];', html, re.DOTALL)
    existing = json.loads('[' + fb_match.group(1).rstrip(',').rstrip() + ']')
    existing_dates = {e['date'] for e in existing}

    # 需要新增的日期（最后已有日期+1 到 昨天）
    last_date = max(existing_dates) if existing_dates else '2026-04-08'
    start_new = (date.fromisoformat(last_date) + timedelta(days=1)).isoformat()
    end_new   = (today - timedelta(days=1)).isoformat()  # 昨天（今天数据可能不全）

    # 需要补充 ROI 的日期（最近30天内的已有记录）
    roi_start = (today - timedelta(days=35)).isoformat()

    print(f'[plan] 新日期范围: {start_new} ~ {end_new}')
    print(f'[plan] ROI补充范围: {roi_start} ~ {last_date}')

    # 3. 查询数据
    t2_new  = query_table2(table2, start_new, end_new)
    t1_new  = query_table1(table1, start_new, end_new)
    t2_roi  = query_table2(table2, roi_start, last_date)

    # 4. 生成新 entries
    new_entries = merge_entries(t1_new, t2_new)
    print(f'[data] 获取到 {len(new_entries)} 条新数据')

    # 5. 整理 ROI 更新（已有记录的 D3/D7/D15/D30 补充）
    roi_updates = {}
    slot_days = [3, 7, 15, 30, 60]
    for r2 in t2_roi:
        ds = str(r2['dt'])[:10]
        d = date.fromisoformat(ds)
        updates = {}
        for days in slot_days:
            if (d + timedelta(days=days)) <= today:
                col = f'roi{days}'
                v = pct(r2.get(col))
                if v: updates[days] = v
        if updates:
            roi_updates[ds] = updates

    # 6. 更新 index.html
    added, updated = update_index(new_entries, roi_updates)

    # 7. Git push
    if added > 0 or updated > 0:
        git_push(added, updated)
    else:
        print('[git] 没有变更，跳过 push')

    print(f'\n✅ 完成！访问 https://nanshengliujunjie-blip.github.io/zhixing-daily/')

if __name__ == '__main__':
    main()
