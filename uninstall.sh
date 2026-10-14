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
agent_dir=$HOME/Library/LaunchAgents
label=com.dannyfranca.cargo-sweep-timer
config_dir=${XDG_CONFIG_HOME:-$HOME/.config}/cargo-sweep-timer

uninstall_systemd() {
  systemctl --user disable --now cargo-sweep-timer.timer 2>/dev/null || true
  if ! systemctl --user stop cargo-sweep-timer.service; then
    service_state=$(systemctl --user show cargo-sweep-timer.service --property=ActiveState --value) || exit 1
    if [[ $service_state != inactive && $service_state != failed ]]; then
      echo "could not stop sweep service (state: $service_state)" >&2
      exit 1
    fi
  fi
  rm -f "$unit_dir/cargo-sweep-timer.service" "$unit_dir/cargo-sweep-timer.timer" "$HOME/.local/bin/cargo-sweep-timer"
  systemctl --user daemon-reload
}

uninstall_launchd() {
  local service=gui/$(id -u)/$label
  if ! launchctl bootout "$service" 2>/dev/null && launchctl print "$service" >/dev/null 2>&1; then
    echo "could not unload $service" >&2
    exit 1
  fi
  rm -f "$agent_dir/$label.plist" "$HOME/.local/bin/cargo-sweep-timer"
}

if [[ $(uname) == Darwin ]]; then
  uninstall_launchd
else
  uninstall_systemd
fi

if ((purge)); then
  rm -rf "$config_dir"
  echo "removed config: $config_dir"
else
  echo "kept config: $config_dir (use --purge to remove it)"
fi
