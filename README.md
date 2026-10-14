# cargo-sweep-timer

Cargo does not delete old build artifacts. Each `target` dir grows until the disk is full. Worktrees make this worse, because each worktree has its own `target` dir.

This tool runs [cargo-sweep](https://github.com/holmgr/cargo-sweep) every day from a systemd user timer on Linux, or a launchd agent on macOS. It removes artifacts that were not used for a set number of days.

The same `install.sh` and `uninstall.sh` operate on both systems. They find the system with `uname` and select the scheduler:

| | Linux | macOS |
| --- | --- | --- |
| Scheduler | systemd user timer | launchd user agent |
| Schedule files | `~/.config/systemd/user/cargo-sweep-timer.{service,timer}` | `~/Library/LaunchAgents/com.dannyfranca.cargo-sweep-timer.plist` |
| Default schedule | Daily at 00:00, with a random delay of up to 15 minutes | Daily at 00:00 |
| Missed sweep (computer off) | Runs when the systemd user manager starts, usually at login | Skipped until the next day |
| Logs | `journalctl --user -u cargo-sweep-timer.service` | `~/Library/Logs/cargo-sweep-timer.log` |

The script, the config, and the commands in [Configure](#configure) and [Use on all systems](#use-on-all-systems) are the same on both systems. Instructions for one system only are in [Linux](#linux) and [macOS](#macos).

If you set `XDG_CONFIG_HOME`, `~/.config` in this README means that dir. Set the same value when you run `install.sh` and `uninstall.sh`, because each script finds its files from the value at run time.

- On Linux, the systemd user manager must have the same value. The manager finds the timer units from its own `XDG_CONFIG_HOME`, and the service does not set it for the sweep. If the values are different, the installer cannot enable the timer, or the scheduled sweep cannot find your config.
- On macOS, the agent always reads the config file that the installer created.

## Requirements

- Linux with systemd, or macOS
- Cargo
- cargo-sweep: `cargo install cargo-sweep`. Some distros also have a package, for example `pacman -S cargo-sweep`.

## Install

```sh
git clone https://github.com/dannyfranca/cargo-sweep-timer.git
cd cargo-sweep-timer
./install.sh
```

On all systems, the installer does these steps:

1. It copies the script to `~/.local/bin/cargo-sweep-timer`.
2. It creates `~/.config/cargo-sweep-timer/config.env` from `config.example.env`. If this file exists, it does not change it.
3. It installs the scheduler for your system. Refer to [Install on Linux](#install-on-linux) or [Install on macOS](#install-on-macos).

The scheduled job uses the `PATH` from the install command, with `$CARGO_HOME/bin` added if `CARGO_HOME` is set. If you change the Cargo location, run the installer again.

To update, pull the repo and run `./install.sh` again.

## Configure

Edit `~/.config/cargo-sweep-timer/config.env`:

```sh
# Remove artifacts not used for this many days.
SWEEP_DAYS=1

# Colon-separated dirs searched for Cargo projects at any depth, hidden dirs included.
SWEEP_ROOTS="$HOME/git"

# Colon-separated target dirs that live outside any project (CARGO_TARGET_DIR builds).
SWEEP_TARGET_DIRS="$HOME/.cache/my-shared-target:$HOME/.cache/other-target"
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `SWEEP_DAYS` | `1` | Remove artifacts not used for this many days. |
| `SWEEP_ROOTS` | `~/git` | Dirs to search for Cargo projects. The search includes hidden dirs such as `.worktrees`. |
| `SWEEP_TARGET_DIRS` | empty | Target dirs outside a project, for example a shared `CARGO_TARGET_DIR`. |
| `DRY_RUN` | `0` | Set to `1` to show what the sweep would remove, without removing it. |

Bash reads the file, so `$HOME` expands. A variable that is already set in the environment overrides the file. To use a different file, set `CARGO_SWEEP_TIMER_CONFIG`. The command stops if this file is missing or the config fails to load.

A low `SWEEP_DAYS` value frees more disk space. The cost is that the next build of an old branch compiles its dependencies again.

The command fails if a configured root is missing or cannot be read or searched. Cargo-sweep 0.8.0 can still skip nested dirs that it cannot read, or projects whose Cargo metadata fails to load. It does not report these search errors, so a successful run does not confirm that it found every project.

## Use on all systems

```sh
cargo-sweep-timer --dry-run      # show what a sweep would remove
cargo-sweep-timer                # sweep now
SWEEP_DAYS=7 cargo-sweep-timer   # override one setting for one run
```

If `~/.local/bin` is not in your `PATH`, use `~/.local/bin/cargo-sweep-timer`. macOS does not add this dir to `PATH` by default.

## Uninstall

```sh
./uninstall.sh           # keeps your config
./uninstall.sh --purge   # also removes ~/.config/cargo-sweep-timer
```

To find what the uninstaller does on your system, refer to [Uninstall on Linux](#uninstall-on-linux) or [Uninstall on macOS](#uninstall-on-macos).

## Linux

### Install on Linux

The installer copies the service and timer units to `~/.config/systemd/user/`, then enables and starts the timer.

### Schedule on Linux

The timer runs once each day. If the computer is off at that time, the missed sweep runs when your systemd user manager next starts, usually at login. The timer can delay the sweep by up to 15 minutes. To run without a login, enable lingering with `loginctl enable-linger "$USER"`.

To change the schedule, use a systemd drop-in:

```sh
systemctl --user edit cargo-sweep-timer.timer
```

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 11:30:00
```

The empty `OnCalendar=` line removes the default schedule. Without it, systemd keeps both schedules.

### Use on Linux

```sh
systemctl --user start cargo-sweep-timer.service      # sweep now, through systemd
systemctl --user list-timers cargo-sweep-timer.timer  # next and last sweep
journalctl --user -u cargo-sweep-timer.service        # logs of the sweeps
```

### Uninstall on Linux

The uninstaller disables the timer and stops the sweep service. Then it removes the units and the script. If the sweep service continues to run, the uninstaller keeps the files and exits with an error.

## macOS

### Install on macOS

The installer writes the agent to `~/Library/LaunchAgents/com.dannyfranca.cargo-sweep-timer.plist`, then loads it. launchd does not set `XDG_CONFIG_HOME`, so the agent always reads the config file that the installer created.

### Schedule on macOS

The agent runs each day at 00:00. If the Mac sleeps at that time, the sweep runs when it wakes. If the Mac is off at that time, launchd skips the sweep until the next day. The agent runs only while you are logged in.

To change the schedule, edit `StartCalendarInterval` in `launchd/com.dannyfranca.cargo-sweep-timer.plist`, then run `./install.sh` again.

### Folder access on macOS

If a sweep root is in `~/Documents`, `~/Desktop`, or `~/Downloads`, macOS blocks access from the agent. Give `/bin/bash` Full Disk Access in System Settings, or use a root outside these dirs.

### Use on macOS

```sh
launchctl kickstart gui/$(id -u)/com.dannyfranca.cargo-sweep-timer   # sweep now, through launchd
launchctl print gui/$(id -u)/com.dannyfranca.cargo-sweep-timer       # agent state and last exit code
tail -f ~/Library/Logs/cargo-sweep-timer.log                          # logs of the sweeps
```

### Uninstall on macOS

The uninstaller unloads the agent. Then it removes the agent and the script. If launchd cannot confirm that the agent is unloaded, the uninstaller keeps the files and exits with an error.

## Test

Run `python3 -m unittest discover -s tests`. The tests need Python 3, Cargo, and cargo-sweep. The systemd unit test also needs systemd-analyze, and it is skipped without it. They use temporary projects and target dirs.
