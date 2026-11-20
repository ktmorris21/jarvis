#!/usr/bin/env bash
# Explicitly voice-confirmed, detached update. No arbitrary user-supplied arguments.
set -Eeuo pipefail
export PATH=/usr/local/bin:/usr/bin:/bin
REPO=/home/shadowfax/jarvis
LOCK=/tmp/jarvis-voice-update.lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[UPDATE] Another update is running"
  exit 1
fi
cd "$REPO"
echo "[UPDATE] Starting at $(date -u +%FT%TZ)"
if [[ "$(git branch --show-current)" != main ]]; then
  echo "[UPDATE] Refusing: expected main branch"
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "[UPDATE] Refusing: dirty working tree"
  exit 1
fi
before=$(git rev-parse HEAD)
git fetch --quiet origin main
# Never rewind or merge divergent histories.
git merge-base --is-ancestor "$before" origin/main || {
  echo "[UPDATE] Refusing: local main diverged from origin/main"
  exit 1
}
git merge --ff-only origin/main
after=$(git rev-parse HEAD)
echo "[UPDATE] Revision: $before -> $after"
if [[ "$after" == "$before" ]]; then
  echo "[UPDATE] Already up to date"
  exit 0
fi
# Fail before changing running services if required permissions are absent.
sudo -n -l /usr/bin/systemctl restart jarvis-bridge@shadowfax.service >/dev/null
sudo -n -l /usr/bin/systemctl restart jarvis-agents-voice.service >/dev/null
echo "[UPDATE] Restarting ROS bridge, then voice"
sudo -n /usr/bin/systemctl restart jarvis-bridge@shadowfax.service
sudo -n /usr/bin/systemctl restart jarvis-agents-voice.service
echo "[UPDATE] Complete at $(date -u +%FT%TZ)"
