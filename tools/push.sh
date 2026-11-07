#!/usr/bin/env bash
# 一键推送到 GitHub。
#
#   GITHUB_TOKEN=github_pat_xxx bash tools/push.sh
#
# 也可以先 export，或者交互式粘贴（不回显、不落盘）。
# token 只在本次命令的 remote URL 里出现，不会写进 .git/config。

set -euo pipefail
cd "$(dirname "$0")/.."

REPO="${REPO:-zhu2526/zhu2526}"
BRANCH="${BRANCH:-main}"

if [ -z "${GITHUB_TOKEN:-}" ]; then
  printf "粘贴 GitHub token（输入不回显）: "
  read -rs GITHUB_TOKEN
  echo
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "没有 token，退出。" >&2
  exit 1
fi

# 走本机代理（如果设置了的话）
PROXY_ARG=()
if [ -n "${HTTPS_PROXY:-}" ]; then
  PROXY_ARG=(-c "http.proxy=${HTTPS_PROXY}")
fi

echo "→ 推到 ${REPO} (${BRANCH})"
git -c credential.helper= "${PROXY_ARG[@]}" push \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" \
  "HEAD:refs/heads/${BRANCH}"

# 顺手把 origin 配好，下次直接 git push
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${REPO}.git"

echo "√ 完成：https://github.com/${REPO}"
