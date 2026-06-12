#!/bin/bash
# 知星看板+日报 每日自动更新（由 launchd 调用）
# 用法: daily_update.sh [data|full]
#   data : 只更新 投放用户画像/用户概览/投放用户明细（订单+归因+媒体），跳过营销总览  → 早上9:00
#   full : 完整更新（含营销总览 表1+表2 FALLBACK）                                 → 中午12:15
# 日志: ~/zhixing/logs/daily_<mode>.log
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 避免代理干扰 git push / node 请求
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

MODE="${1:-full}"
REPO="$HOME/zhixing"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/daily_${MODE}.log"
mkdir -p "$LOG_DIR"

if [ "$MODE" = "data" ]; then
  export SKIP_FALLBACK=1
fi

cd "$REPO" || exit 1
RUN_LOG="$(mktemp)"
{
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  [$MODE] 运行时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════════════"
  /usr/bin/python3 "$REPO/auto_update.py"
  echo "  退出码: $?"
} > "$RUN_LOG" 2>&1
cat "$RUN_LOG" >> "$LOG"

# ── 会话失效主动提醒（带哨兵，避免每30分钟重复弹窗）──
FLAG="$REPO/.session_alert"
if grep -qE "cookie获取用户信息错误|session 已过期|用户未登录|请重新执行" "$RUN_LOG"; then
  if [ ! -f "$FLAG" ]; then
    /usr/bin/osascript -e 'display notification "Nexita 会话已过期，数据停止更新。请运行 login.mjs 重新登录。" with title "知星数据更新 ⚠️" sound name "Basso"' 2>/dev/null
    touch "$FLAG"
    echo "  ⚠ 已发送会话失效通知" >> "$LOG"
  fi
else
  # 本次正常 → 若之前报过警，提示已恢复并清除哨兵
  if [ -f "$FLAG" ]; then
    /usr/bin/osascript -e 'display notification "Nexita 会话已恢复，数据更新正常。" with title "知星数据更新 ✓"' 2>/dev/null
    rm -f "$FLAG"
  fi
fi
rm -f "$RUN_LOG"
