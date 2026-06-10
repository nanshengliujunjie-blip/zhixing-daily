#!/usr/bin/env python3
"""运行方式：python3 ~/Desktop/知星/run_update.py 表1路径 表2路径"""
import sys, json, re, openpyxl
from datetime import date

if len(sys.argv) < 3:
    print("用法: python3 run_update.py <表1.xlsx> <表2.xlsx>")
    sys.exit(1)

T1, T2 = sys.argv[1], sys.argv[2]
print(f"表1: {T1}\n表2: {T2}\n")

wb1 = openpyxl.load_workbook(T1, data_only=True)
wb2 = openpyxl.load_workbook(T2, data_only=True)
rows1 = list(wb1.active.iter_rows(values_only=True))
rows2 = list(wb2.active.iter_rows(values_only=True))

t1 = {r[0]: r for r in rows1[1:] if r[1]=='汇总' and r[2]=='汇总' and r[3]=='汇总' and isinstance(r[0], int)}
t2 = {r[3]: r for r in rows2[1:] if isinstance(r[3],str) and r[3].startswith('2026') and r[4]=='汇总' and r[5]=='汇总'}

def sv(v):
    if v is None or str(v) in ('nan','None',''): return None
    try: f=float(v); return None if f==0 else round(f*100,4)
    except: return None

ROI_COLS = [29,31,33,35,37,39,41,43,45]

INDEX = '/Users/oulei/Desktop/知星/index.html'
DASHBOARD = '/Users/oulei/Desktop/知星/dashboard.html'
with open(INDEX, encoding='utf-8') as f:
    html = f.read()
fb = re.search(r'const FALLBACK\s*=\s*\[(.*?)\];', html, re.DOTALL)
entries = json.loads('[' + fb.group(1).rstrip(',').rstrip() + ']')
entry_map = {e['date']: e for e in entries}
last_date = max(entry_map.keys())
print(f"现有 {len(entries)} 条，最新: {last_date}")

def make_entry(ds):
    d_int = int(ds.replace('-',''))
    r1 = t1.get(d_int); r2 = t2.get(ds)
    if not r1: return None           # 表1必须有
    # 消耗以表2折后支出为准，表2缺失时才用表1消耗兜底
    spend = round(float(r2[14]),2) if r2 and r2[14] else round(float(r1[4]),2) if r1[4] else 0
    reg = int(r1[6]) if r1[6] else 0
    pay = int(r1[13]) if r1[13] else 0
    payAmt = round(float(r1[15]),2) if r1[15] else 0
    roi0 = round(payAmt/spend*100,4) if spend and payAmt else None
    # 表2有则补ROI曲线，无则全null
    rc = ([roi0] + [sv(r2[c]) for c in ROI_COLS] + [None]*6) if r2 else ([roi0]+[None]*15)
    return {
        "date":ds,"spend":spend,
        "activate":int(r1[5]) if r1[5] else 0,"reg":reg,
        "regCost":round(spend/reg,2) if reg else None,
        "ai":int(r1[7]) if r1[7] else 0,
        "payCount":pay,"payAmount":payAmt,
        "payCost":round(spend/pay,2) if pay else None,
        "payRate":round(pay/reg*100,4) if reg and pay else None,
        "roi":roi0,
        "enterRoom":int(r1[9]) if r1[9] else 0,
        "enterRoomRate":round(float(r1[10])*100,4) if r1[10] and str(r1[10])!='nan' else None,
        "mic":int(r1[11]) if r1[11] else 0,
        "micRate":round(float(r1[12])*100,4) if r1[12] and str(r1[12])!='nan' else None,
        "nextRetention":sv(r2[48]) if r2 else None,
        "roiCurve":rc,
        "pret":sv(r2[67]) if r2 else None,
    }

added = updated = refreshed = 0

# 刷新已有条目：消耗以表2为准，表2缺失时用表1；次留从表2取
for ds, e in entry_map.items():
    d_int = int(ds.replace('-',''))
    r1 = t1.get(d_int)
    r2 = t2.get(ds)
    if not r1: continue
    # 消耗：表2优先
    if r2 and r2[14]:
        new_spend = round(float(r2[14]), 2)
    elif r1[4]:
        new_spend = round(float(r1[4]), 2)
    else:
        continue
    reg = int(r1[6]) if r1[6] else e.get('reg', 0)
    pay = int(r1[13]) if r1[13] else e.get('payCount', 0)
    payAmt = round(float(r1[15]), 2) if r1[15] else e.get('payAmount', 0)
    roi0 = round(payAmt/new_spend*100, 4) if new_spend and payAmt else None
    changed = False
    if new_spend != e.get('spend'):
        e['spend'] = new_spend
        e['regCost'] = round(new_spend/reg, 2) if reg else None
        e['payCost'] = round(new_spend/pay, 2) if pay else None
        e['roi'] = roi0
        rc = e.get('roiCurve', [None]*16)
        while len(rc) < 16: rc.append(None)
        rc[0] = roi0
        e['roiCurve'] = rc
        changed = True
    # 次留：只要表2有就更新
    if r2:
        ret = sv(r2[48])
        if ret != e.get('nextRetention'):
            e['nextRetention'] = ret; changed = True
    if changed:
        e['reg'] = reg; e['payCount'] = pay; e['payAmount'] = payAmt
        e['payRate'] = round(pay/reg*100, 4) if reg and pay else None
        e['activate'] = int(r1[5]) if r1[5] else e.get('activate', 0)
        e['ai'] = int(r1[7]) if r1[7] else e.get('ai', 0)
        e['enterRoom'] = int(r1[9]) if r1[9] else e.get('enterRoom', 0)
        e['enterRoomRate'] = round(float(r1[10])*100, 4) if r1[10] and str(r1[10])!='nan' else e.get('enterRoomRate')
        e['mic'] = int(r1[11]) if r1[11] else e.get('mic', 0)
        e['micRate'] = round(float(r1[12])*100, 4) if r1[12] and str(r1[12])!='nan' else e.get('micRate')
        refreshed += 1
        print(f"  ↺{ds}: spend→{new_spend}, roi→{roi0}")

print(f"已刷新 {refreshed} 条历史消耗/ROI数据")

# 1. 补录历史缺失数据（表1里有但FALLBACK没有的）
all_t1_dates = []
for d_int in sorted(t1.keys()):
    ds = f'{str(d_int)[:4]}-{str(d_int)[4:6]}-{str(d_int)[6:]}'
    all_t1_dates.append(ds)

for ds in all_t1_dates:
    if ds in entry_map: continue   # 已有，跳过
    e = make_entry(ds)
    if e:
        entry_map[ds] = e
        tag = '(含ROI曲线)' if t2.get(ds) else '(仅表1)'
        print(f"  ＋{ds}: spend={e['spend']}, reg={e['reg']}, roi={e['roi']} {tag}")
        added += 1

# 2. 追加最新日期（表2里比last_date新的，make_entry已能处理）
for ds in sorted([k for k in t2 if k > last_date]):
    if ds in entry_map: continue   # 可能已在上面处理过
    e = make_entry(ds)
    if e:
        entry_map[ds] = e
        print(f"  ＋{ds}: spend={e['spend']}, reg={e['reg']}, roi={e['roi']}, ret={e['nextRetention']}")
        added += 1

slot = {29:1,31:2,33:3,35:4,37:5,39:6,41:7,43:8,45:9}
for ds in sorted([k for k in t2 if '2026-01-01' <= k <= last_date]):
    r2 = t2[ds]
    if ds not in entry_map: continue
    e = entry_map[ds]; rc = e.get('roiCurve',[None]*16)
    while len(rc)<16: rc.append(None)
    changed = False
    for col,idx in slot.items():
        v = sv(r2[col])
        if v and rc[idx] is None: rc[idx]=v; changed=True
    # 补次留/pret
    ret = sv(r2[48]); pret = sv(r2[67])
    if ret and not e.get('nextRetention'): e['nextRetention']=ret; changed=True
    if pret and not e.get('pret'): e['pret']=pret; changed=True
    if changed: e['roiCurve']=rc; updated+=1

print(f"\n新增 {added} 条，ROI/次留补充 {updated} 条")

def to_js(v):
    if v is None: return 'null'
    if isinstance(v,bool): return 'true' if v else 'false'
    if isinstance(v,list): return '['+','.join(to_js(x) for x in v)+']'
    if isinstance(v,str): return json.dumps(v)
    if isinstance(v,float): return f'{v:.4f}'.rstrip('0').rstrip('.')
    return str(v)

def ejs(e): return '{'+','.join(f'"{k}":{to_js(v)}' for k,v in e.items())+'}'

entries_out = sorted(entry_map.values(), key=lambda e: e['date'])
new_fb = ','.join(ejs(e) for e in entries_out)
html2 = re.sub(r'(const FALLBACK\s*=\s*\[)(.*?)(\];)', lambda m: m.group(1)+new_fb+m.group(3), html, flags=re.DOTALL)
today_str = date.today().strftime("%m%d")
html2 = re.sub(r"SEED_VER\s*=\s*'[^']+'", f"SEED_VER='v26_jun03_{today_str}'", html2)
with open(INDEX,'w',encoding='utf-8') as f:
    f.write(html2)
print("index.html 已更新")

# 同步更新 dashboard.html 的 FALLBACK
with open(DASHBOARD, encoding='utf-8') as f:
    dash_html = f.read()
dash_html2 = re.sub(r'(const FALLBACK\s*=\s*\[)(.*?)(\];)', lambda m: m.group(1)+new_fb+m.group(3), dash_html, flags=re.DOTALL)
with open(DASHBOARD,'w',encoding='utf-8') as f:
    f.write(dash_html2)
print("dashboard.html 已更新")

# ── 更新 index.html 的 CH_FALLBACK（分渠道数据）──────────────────
def sv_ret(v):
    if v is None or str(v) in ('nan','None',''): return 0
    try:
        f = float(v)
        return round(f*100, 2) if f < 1 else round(f, 2)
    except: return 0
def sv_roi_ch(v):
    if v is None or str(v) in ('nan','None',''): return 0
    try:
        f = float(v)
        return round(f*100, 2) if f < 1 else round(f, 2)
    except: return 0

ch_rows = [r for r in rows2[1:] if r[4]=='ZHIXING' and isinstance(r[5],str) and r[5]!='汇总'
           and r[6]=='汇总' and r[7]=='汇总' and isinstance(r[3],str) and r[3].startswith('2026')]
with open(INDEX, encoding='utf-8') as f:
    idx_html = f.read()
m_ch = re.search(r'const CH_FALLBACK=(\{.*?\});', idx_html)
ch_fallback = json.loads(m_ch.group(1)) if m_ch else {}
last_ch_date = max(ch_fallback.keys()) if ch_fallback else '2000-01-01'
ch_added = 0
for r in ch_rows:
    ds = r[3]
    if ds <= last_ch_date: continue
    ch = r[5]
    d_int = int(ds.replace('-',''))
    r1 = t1.get(d_int)
    spend = round(float(r[14]),2) if r[14] else 0
    reg = int(r[16]) if r[16] else 0
    pay = int(r[19]) if r[19] else 0
    payAmt = round(float(r[22]),2) if r[22] else 0
    entry = {
        'spend': spend, 'reg': reg,
        'regCost': round(spend/reg,2) if reg else 0,
        'roi': sv_roi_ch(r[25]), 'payCount': pay, 'payAmount': payAmt,
        'nextRetention': sv_ret(r[48]),
        'enterRoomRate': round(float(r1[10])*100,2) if r1 and r1[10] and str(r1[10])!='nan' else 0,
        'micRate': round(float(r1[12])*100,2) if r1 and r1[12] and str(r1[12])!='nan' else 0,
    }
    if ds not in ch_fallback: ch_fallback[ds] = {}
    ch_fallback[ds][ch] = entry
    ch_added += 1
new_ch_str = json.dumps(ch_fallback, ensure_ascii=False, separators=(',',':'))
idx_html2 = re.sub(r'const CH_FALLBACK=(\{.*?\});', f'const CH_FALLBACK={new_ch_str};', idx_html)
with open(INDEX,'w',encoding='utf-8') as f:
    f.write(idx_html2)
print(f"CH_FALLBACK 新增 {ch_added} 渠道条目（index.html）")

import subprocess, os, tempfile

# ── 更新 ad_users.json（自动下载归因 Excel + 补录新用户）────────
AD_USERS = '/Users/oulei/Desktop/知星/ad_users.json'
USER_DATA_PATH = '/Users/oulei/Desktop/知星/user_data.json'
FETCH_MJS = '/Users/oulei/Desktop/知星/fetch_attribution.mjs'
USER_ORDERS_PATH = '/Users/oulei/Desktop/知星/user_orders.json'

def load_ad_users():
    with open(AD_USERS) as f: return json.load(f)

def update_ad_users(new_dates):
    """为 new_dates 列表中每个日期下载归因数据并补录 ad_users.json"""
    if not new_dates:
        print("ad_users.json 无需更新")
        return
    if not os.path.exists(FETCH_MJS):
        print(f"⚠ 未找到 {FETCH_MJS}，跳过 ad_users 更新")
        return

    # 加载现有数据
    ad = load_ad_users()
    existing_uids = set(str(u[0]) for u in ad['users'])

    with open(USER_DATA_PATH) as f:
        ud = json.load(f)
    ud_map = {str(u[0]): u for u in (ud['users'] if 'users' in ud else ud)}

    with open(USER_ORDERS_PATH) as f:
        orders_data = json.load(f)

    total_new = 0
    for ds in new_dates:
        print(f"[ad_users] 正在下载 {ds} 归因数据...")
        tmp_xlsx = os.path.join(tempfile.gettempdir(), f'attr_{ds}.xlsx')
        result = subprocess.run(
            ['node', FETCH_MJS, f'--date={ds}', f'--out={tmp_xlsx}'],
            capture_output=True, text=True, timeout=180
        )
        if result.returncode != 0:
            print(f"  ⚠ 归因下载失败: {result.stderr[-200:]}")
            continue

        # 读 Excel，提取新增注册 uid
        try:
            wb = openpyxl.load_workbook(tmp_xlsx, data_only=True)
            rows_xlsx = list(wb.active.iter_rows(values_only=True))
        except Exception as e:
            print(f"  ⚠ 读取 Excel 失败: {e}")
            continue

        new_uids = [str(r[16]) for r in rows_xlsx[1:] if r[3] == '新增注册' and r[16]]
        truly_new = [u for u in new_uids if u not in existing_uids]
        print(f"  {ds}: 新增注册 {len(new_uids)} 人，其中未收录 {len(truly_new)} 人")

        for uid in truly_new:
            uu = ud_map.get(uid)
            gender = uu[2] if uu and len(uu) > 2 else 0
            age    = uu[3] if uu and len(uu) > 3 else None
            orders = orders_data.get(uid, [])
            first_day = [o for o in orders if o['d'] == ds]
            roi_pay_amt = round(sum(o['amt'] for o in first_day), 2)
            total_amt   = round(sum(o['amt'] for o in orders), 2)
            order_cnt   = len(orders)
            q_cnt  = sum(1 for o in orders if o.get('type') == '提问')
            lm_cnt = sum(1 for o in orders if o.get('type') == '连麦')
            zx_cnt = sum(1 for o in orders if o.get('type') == '咨询')
            paid = [o for o in orders if o.get('amt', 0) > 0]
            consultant = paid[0].get('c', '未知') if paid else '未知'
            ad['users'].append([uid, gender, age, roi_pay_amt, total_amt,
                                 order_cnt, q_cnt, lm_cnt, zx_cnt, consultant, ds])
            existing_uids.add(uid)
            total_new += 1

        os.unlink(tmp_xlsx)

    if total_new > 0:
        ad['users'].sort(key=lambda u: u[10] or '')
        with open(AD_USERS, 'w') as f:
            json.dump(ad, f, ensure_ascii=False, separators=(',', ':'))
        print(f"ad_users.json 已更新，新增 {total_new} 人（共 {len(ad['users'])} 人）")
    else:
        print("ad_users.json 无新用户")

# 确定需要更新 ad_users 的日期（新增进 FALLBACK 的日期）
new_ad_dates = sorted(entry_map.keys())[-added:] if added > 0 else []
update_ad_users(new_ad_dates)

# ── Git push ──────────────────────────────────────────────────
subprocess.run(['git','add','index.html','dashboard.html','ad_users.json'], cwd='/Users/oulei/Desktop/知星', check=True)
subprocess.run(['git','commit','-m',f'日报更新 {date.today()}: 新增{added}条 ROI补充{updated}条 (index+dashboard+ad_users同步)'], cwd='/Users/oulei/Desktop/知星', check=True)
subprocess.run(['git','push'], cwd='/Users/oulei/Desktop/知星', check=True)
print("✅ 已推送到 GitHub Pages!")
