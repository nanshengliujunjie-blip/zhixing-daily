#!/bin/bash
# 知星看板+日报 每日自动更新（由 launchd 在每天 12:15 调用）
# 表2约中午12点更新，故定在12:15之后跑。
# 日志: ~/Desktop/知星/logs/daily_update.log
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# 避免代理干扰 git push / node 请求
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

REPO="$HOME/Desktop/知星"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/daily_update.log"
mkdir -p "$LOG_DIR"

cd "$REPO" || exit 1
{
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "  运行时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════════════════════════════"
  /usr/bin/python3 "$REPO/auto_update.py"
  echo "  退出码: $?"
} >> "$LOG" 2>&1
