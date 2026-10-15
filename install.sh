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
  install -m644 "$repo/systemd/cargo-sweep-timer.service" "$unit_dir"
  local timer
  timer=$(<"$repo/systemd/cargo-sweep-timer.timer")
  printf '%s\n' "${timer//@TIME@/$sweep_time}" >"$unit_dir/cargo-sweep-timer.timer"

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

install_launchd() {
  local plist
  plist=$(<"$repo/launchd/$label.plist")
  plist=${plist//@HOME@/"$(xml_escape "$HOME")"}
  plist=${plist//@PATH@/"$(xml_escape "$service_path")"}
  # launchd does not set XDG_CONFIG_HOME, so pin the one this installer used.
  plist=${plist//@CONFIG_HOME@/"$(xml_escape "${XDG_CONFIG_HOME:-$HOME/.config}")"}
  plist=${plist//@HOUR@/$sweep_hour}
  plist=${plist//@MINUTE@/$sweep_minute}
  mkdir -p "$agent_dir" "$HOME/Library/Logs"
  printf '%s\n' "$plist" >"$agent_dir/$label.plist"
  launchctl bootstrap "gui/$(id -u)" "$agent_dir/$label.plist"
  echo "scheduled daily at $sweep_time, logs: $HOME/Library/Logs/cargo-sweep-timer.log"
}

platform=$(uname)

# systemd and launchd cannot read the config, so the installer copies the time into them.
# It loads the config the way the sweep does, so a config that would stop the sweep stops
# the install before it changes anything. A new process keeps set -e active in the config.
config=$config_dir/config.env
[[ -f $config ]] || config=$repo/config.example.env
if ! config_time=$(bash -euo pipefail -c 'source "$1" >/dev/null; printf "%s" "${SWEEP_TIME:-}"' bash "$config"); then
  echo "could not load config: $config" >&2
  exit 1
fi
sweep_time=${SWEEP_TIME-$config_time}
sweep_time=${sweep_time:-10:00}
if ! [[ $sweep_time =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "SWEEP_TIME must be HH:MM in 24-hour time, got: $sweep_time. Using 10:00." >&2
  sweep_time=10:00
fi
sweep_hour=$((10#${sweep_time%:*}))
sweep_minute=$((10#${sweep_time#*:}))
printf -v sweep_time '%02d:%02d' "$sweep_hour" "$sweep_minute"

# A loaded agent keeps its old schedule, so stop before the files change under it.
if [[ $platform == Darwin ]]; then
  unload_launchd
fi

mkdir -p "$bin_dir"
install -m755 "$repo/bin/cargo-sweep-timer" "$bin_dir/cargo-sweep-timer"

if [[ -f $config_dir/config.env ]]; then
  echo "keeping existing config: $config_dir/config.env"
else
  mkdir -p "$config_dir"
  install -m644 "$repo/config.example.env" "$config_dir/config.env"
  echo "created config: $config_dir/config.env"
fi

if [[ $platform == Darwin ]]; then
  install_launchd
else
  install_systemd
fi
