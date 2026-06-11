#!/bin/bash
# 知星看板+日报 每日自动更新（由 launchd 调用）
# 用法: daily_update.sh [data|full]
#   data : 只更新 投放用户画像/用户概览/投放用户明细（订单+归因+媒体），跳过营销总览  → 早上9:00
#   full : 完整更新（含营销总览 表1+表2 FALLBACK）                                 → 中午12:15
# 日志: ~/Desktop/知星/logs/daily_<mode>.log
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 避免代理干扰 git push / node 请求
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

MODE="${1:-full}"
REPO="$HOME/Desktop/知星"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/daily_${MODE}.log"
mkdir -p "$LOG_DIR"

if [ "$MODE" = "data" ]; then
  export SKIP_FALLBACK=1
fi

cd "$REPO" || exit 1
{
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  [$MODE] 运行时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════════════"
  /usr/bin/python3 "$REPO/auto_update.py"
  echo "  退出码: $?"
} >> "$LOG" 2>&1
