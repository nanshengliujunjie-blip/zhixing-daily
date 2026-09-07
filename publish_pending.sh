#!/bin/bash
# 补发已经提交、但因临时网络或 GitHub 认证问题未发布的日报看板。
# 不生成数据、不提交工作区改动，只同步并推送现有提交。
set -u

export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy

REPO="$HOME/zhixing"
LOG_DIR="$REPO/logs"
LOG="$LOG_DIR/publish_retry.log"
mkdir -p "$LOG_DIR"

cd "$REPO" || exit 1
{
  echo ""
  echo "════════════════════════════════════════════════════════"
  echo "[publish-retry] $(date '+%Y-%m-%d %H:%M:%S')"

  # 无本地提交时无需发起网络请求。
  if [ "$(git rev-list --count origin/main..main 2>/dev/null || echo 0)" = "0" ]; then
    echo "已与 origin/main 同步，无需补发。"
    exit 0
  fi

  if ! GIT_TERMINAL_PROMPT=0 git pull --rebase --autostash origin main; then
    echo "同步远端失败，等待下次补发。"
    exit 1
  fi

  if GIT_TERMINAL_PROMPT=0 git push origin main; then
    echo "补发成功。"
  else
    echo "推送失败，等待下次补发。"
    exit 1
  fi
} >> "$LOG" 2>&1
