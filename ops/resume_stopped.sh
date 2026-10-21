#!/bin/bash
# Resume (SIGCONT) any stopped process (ps state T) in the trees under the given
# root pids, printing one line per resumed pid. On 2026-10-02 ~19:54 a machine-wide
# SIGSTOP froze every service in the tmux services window for ~12h unnoticed.
# Usage: resume_stopped.sh ROOT_PID...
descendants() {
  local p
  for p in $(pgrep -P "$1"); do
    echo "$p"
    descendants "$p"
  done
}

for root in "$@"; do
  for pid in "$root" $(descendants "$root"); do
    stat=$(ps -o stat= -p "$pid" 2>/dev/null) || continue
    if [[ "$stat" == T* ]] && kill -CONT "$pid" 2>/dev/null; then
      echo "$pid $(ps -o command= -p "$pid" | cut -c1-120)"
    fi
  done
done
