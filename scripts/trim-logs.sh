#!/usr/bin/env bash
# Keep Hermes' logs from eating the disk.
#
# The gateway appends to launchd's StandardErrorPath forever and Hermes has no
# rotation of its own. A wedged Slack reconnect loop wrote 442 MB across 6.3
# million identical lines before anyone noticed — and nobody noticed because a
# growing log is invisible until something else breaks.
#
# Trimming in place (truncate + rewrite) rather than renaming: the gateway
# holds these files open, and a rename leaves it writing to an unlinked inode
# that no longer appears anywhere.
set -euo pipefail

logs="${RISTRETTO_LOG_DIR:-$HOME/.hermes/logs}"
# Past this, a log is no longer something a person reads.
max_bytes="${RISTRETTO_LOG_MAX_BYTES:-20971520}"   # 20 MiB
keep_lines="${RISTRETTO_LOG_KEEP_LINES:-5000}"

[ -d "$logs" ] || { echo "trim-logs: no log directory at $logs" >&2; exit 0; }

trimmed=0
for file in "$logs"/*.log; do
  [ -f "$file" ] || continue
  size=$(wc -c < "$file" | tr -d ' ')
  [ "$size" -le "$max_bytes" ] && continue
  tmp="$file.trim.$$"
  # cat back into the original path so the open handle keeps pointing here.
  if tail -n "$keep_lines" "$file" > "$tmp" && cat "$tmp" > "$file"; then
    printf 'trim-logs: %s %sMB -> %sMB\n' \
      "$(basename "$file")" \
      "$(( size / 1048576 ))" \
      "$(( $(wc -c < "$file" | tr -d ' ') / 1048576 ))"
    trimmed=$((trimmed + 1))
  fi
  rm -f "$tmp"
done

[ "$trimmed" -eq 0 ] && echo "trim-logs: nothing over $(( max_bytes / 1048576 ))MB"
exit 0
