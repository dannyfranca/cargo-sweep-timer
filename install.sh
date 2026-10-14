#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")" && pwd)
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
agent_dir=$HOME/Library/LaunchAgents
label=com.dannyfranca.cargo-sweep-timer
config_dir=${XDG_CONFIG_HOME:-$HOME/.config}/cargo-sweep-timer

if ! cargo sweep --version >/dev/null 2>&1; then
  echo "cargo-sweep is missing. Install it first: cargo install cargo-sweep" >&2
  exit 1
fi

# Scheduled runs must find the Cargo installation that passed the check above.
service_path=${CARGO_HOME:+$CARGO_HOME/bin:}$PATH

install_systemd() {
  mkdir -p "$unit_dir"
  install -m644 "$repo/systemd/cargo-sweep-timer.service" "$repo/systemd/cargo-sweep-timer.timer" "$unit_dir"

  service_path=${service_path//\\/\\\\}
  service_path=${service_path//\"/\\\"}
  service_path=${service_path//%/%%}
  printf '\nEnvironment="PATH=%s"\n' "$service_path" >>"$unit_dir/cargo-sweep-timer.service"

  systemctl --user daemon-reload
  systemctl --user enable --now cargo-sweep-timer.timer
  systemctl --user list-timers cargo-sweep-timer.timer --no-pager
}

xml_escape() {
  local value=${1//&/"&amp;"}
  value=${value//</"&lt;"}
  value=${value//>/"&gt;"}
  printf '%s' "$value"
}

install_launchd() {
  local plist
  plist=$(<"$repo/launchd/$label.plist")
  plist=${plist//@HOME@/"$(xml_escape "$HOME")"}
  plist=${plist//@PATH@/"$(xml_escape "$service_path")"}
  # launchd does not set XDG_CONFIG_HOME, so pin the config this installer wrote.
  plist=${plist//@CONFIG@/"$(xml_escape "$config_dir/config.env")"}
  mkdir -p "$agent_dir" "$HOME/Library/Logs"
  printf '%s\n' "$plist" >"$agent_dir/$label.plist"

  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$agent_dir/$label.plist"
  echo "scheduled daily at 00:00, logs: $HOME/Library/Logs/cargo-sweep-timer.log"
}

mkdir -p "$bin_dir"
install -m755 "$repo/bin/cargo-sweep-timer" "$bin_dir/cargo-sweep-timer"

if [[ -f $config_dir/config.env ]]; then
  echo "keeping existing config: $config_dir/config.env"
else
  mkdir -p "$config_dir"
  install -m644 "$repo/config.example.env" "$config_dir/config.env"
  echo "created config: $config_dir/config.env"
fi

if [[ $(uname) == Darwin ]]; then
  install_launchd
else
  install_systemd
fi
