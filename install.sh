#!/usr/bin/env bash
set -euo pipefail

repo=$(cd "$(dirname "$0")" && pwd)
bin_dir=$HOME/.local/bin
unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
config_dir=${XDG_CONFIG_HOME:-$HOME/.config}/cargo-sweep-timer

if ! cargo sweep --version >/dev/null 2>&1; then
  echo "cargo-sweep is missing. Install it first: cargo install cargo-sweep" >&2
  exit 1
fi

install -Dm755 "$repo/bin/cargo-sweep-timer" "$bin_dir/cargo-sweep-timer"
install -Dm644 -t "$unit_dir" "$repo/systemd/cargo-sweep-timer.service" "$repo/systemd/cargo-sweep-timer.timer"

# Scheduled runs must find the Cargo installation that passed the check above.
service_path=${CARGO_HOME:+$CARGO_HOME/bin:}$PATH
service_path=${service_path//\\/\\\\}
service_path=${service_path//\"/\\\"}
service_path=${service_path//%/%%}
printf '\nEnvironment="PATH=%s"\n' "$service_path" >>"$unit_dir/cargo-sweep-timer.service"

if [[ -f $config_dir/config.env ]]; then
  echo "keeping existing config: $config_dir/config.env"
else
  install -Dm644 "$repo/config.example.env" "$config_dir/config.env"
  echo "created config: $config_dir/config.env"
fi

systemctl --user daemon-reload
systemctl --user enable --now cargo-sweep-timer.timer
systemctl --user list-timers cargo-sweep-timer.timer --no-pager
