#!/usr/bin/env bash
set -euo pipefail

purge=0
for arg in "$@"; do
  case $arg in
    --purge) purge=1 ;;
    *) echo "Usage: uninstall.sh [--purge]" >&2; exit 2 ;;
  esac
done

unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
config_dir=${XDG_CONFIG_HOME:-$HOME/.config}/cargo-sweep-timer

systemctl --user disable --now cargo-sweep-timer.timer 2>/dev/null || true
systemctl --user stop cargo-sweep-timer.service 2>/dev/null || true
rm -f "$unit_dir/cargo-sweep-timer.service" "$unit_dir/cargo-sweep-timer.timer" "$HOME/.local/bin/cargo-sweep-timer"
systemctl --user daemon-reload

if ((purge)); then
  rm -rf "$config_dir"
  echo "removed config: $config_dir"
else
  echo "kept config: $config_dir (use --purge to remove it)"
fi
