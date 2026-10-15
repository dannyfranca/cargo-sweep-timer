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

unload_launchd() {
  local service=gui/$(id -u)/$label status=0 attempt
  if launchctl bootout "$service" 2>/dev/null; then
    # bootout can return while a sweep still runs, and bootstrap fails until the job exits.
    for ((attempt = 0; attempt < 50; attempt++)); do
      launchctl print "$service" >/dev/null 2>&1 || return 0
      sleep 0.2
    done
    echo "$service did not stop within 10 s" >&2
    exit 1
  fi
  launchctl print "$service" >/dev/null 2>&1 || status=$?
  # launchctl print exits 113 only when the service is not loaded; any other result leaves its state unknown.
  if ((status != 113)); then
    echo "could not unload $service" >&2
    exit 1
  fi
}

uninstall_launchd() {
  unload_launchd
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
