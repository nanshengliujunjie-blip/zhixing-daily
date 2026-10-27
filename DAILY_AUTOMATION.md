# 日报每日自动更新

`daily_automation.py` 统一运行现有抓取脚本、检查完整性并自动提交到 GitHub。
更新范围：营销总览、ROI、用户概览与投放明细、顾问、素材、渠道（信息流/商店）和风控。
每日查询截至北京时间前一天；ROI3/7/15/30 继续按成熟周期计算。

## 已配置的时间

- 每天北京时间 **12:15** 完整更新。
- 每天 12:15 至当天结束，报表未出、下载失败、登录过期或发布失败时，**完成后至少 30 分钟**再重试。
- 调度器每 15 分钟检查一次，更新全部成功后当天停止；下次登录后会检查是否漏更。
- 使用运行锁防止并发，不再另跑旧的轻量更新或只上传补发任务。
- 归因下载失败的日期写入待补拉清单；不会因后续日期成功而遗失缺口。
- 缺失表 1、渠道或风控日期时不记为“全部成功”；已成功更新的板块仍可先发布。

## 使用方法

在仓库目录运行（本机路径：`/Users/oulei/zhixing`）：

```bash
# 安装或恢复定时任务，只需一次
/usr/bin/python3 daily_automation.py install

# 立即完整更新一次
/usr/bin/python3 daily_automation.py run

# 查看上次结果、每个板块检查结果和下次重试时间
/usr/bin/python3 daily_automation.py status

# 仅检查数据完整性与远端提交，不重新拉取数据
/usr/bin/python3 daily_automation.py check
```

日志：`logs/daily_full.log`（历史）、`logs/daily_full_current.log`（当前执行）、
`logs/daily_automation_state.json`（状态）、`logs/attribution_pending.json`（待补归因日期）。

## 运行条件

这是本机定时任务。Mac 需要开机、账户保持登录并联网；关机期间不会运行。
睡眠错过的定时任务会在唤醒后检查。GitHub Token 从 macOS 钥匙串读取，不写入代码。
Nexita 会话有效时无需人工操作；如会话失效，需要重新登录，后续任务会继续重试。

依赖：Python 3.9+、Python 的 openpyxl、Node.js、现有 zhixing-data-query 登录会话及 Playwright。
迁移到其他电脑时需重新配置这些依赖和凭据，然后运行 `install`。
