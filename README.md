# cargo-sweep-timer

Cargo does not delete old build artifacts. Each `target` dir grows until the disk is full. Worktrees make this worse, because each worktree has its own `target` dir.

This tool runs [cargo-sweep](https://github.com/holmgr/cargo-sweep) every day from a systemd user timer on Linux, or a launchd agent on macOS. It removes artifacts that were not used for a set number of seconds. It also removes old incremental compile caches, because cargo-sweep does not remove them.

The same `install.sh` and `uninstall.sh` operate on both systems. They find the system with `uname` and select the scheduler:

| | Linux | macOS |
| --- | --- | --- |
| Scheduler | systemd user timer | launchd user agent |
| Schedule files | `~/.config/systemd/user/cargo-sweep-timer.{service,timer}` | `~/Library/LaunchAgents/com.dannyfranca.cargo-sweep-timer.plist` |
| Schedule | Daily at `SWEEP_TIME` (default 10:00), with a random delay of up to 15 minutes | Daily at `SWEEP_TIME` (default 10:00) |
| Missed sweep (computer off) | Runs when the systemd user manager starts, usually at login | Skipped until the next day |
| Logs | `journalctl --user -u cargo-sweep-timer.service` | `~/Library/Logs/cargo-sweep-timer.log` |

The script, the config, and the commands in [Configure](#configure) and [Use on all systems](#use-on-all-systems) are the same on both systems. Instructions for one system only are in [Linux](#linux) and [macOS](#macos).

If you set `XDG_CONFIG_HOME`, `~/.config` in this README means that dir. Set the same value when you run `install.sh` and `uninstall.sh`, because each script finds its files from the value at run time.

- On Linux, the systemd user manager must have the same value. The manager finds the timer units from its own `XDG_CONFIG_HOME`, and the service does not set it for the sweep. If the values are different, the installer cannot enable the timer, or the scheduled sweep cannot find your config.
- On macOS, the installer writes its `XDG_CONFIG_HOME` value into the agent, so the agent finds your config.

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
# Daily sweep time, HH:MM in 24-hour local time. Run ./install.sh again after a change.
SWEEP_TIME=10:00

# Remove artifacts not used for this many seconds: 3600 = 1 hour, 21600 = 6 hours, 86400 = 1 day,
# 604800 = 7 days. SWEEP_MAX_AGE replaces SWEEP_DAYS.
SWEEP_MAX_AGE=86400

# Colon-separated dirs searched for Cargo target dirs at any depth, hidden dirs included.
SWEEP_ROOTS="$HOME/git"

# Colon-separated target dirs that live outside any project (CARGO_TARGET_DIR builds).
SWEEP_TARGET_DIRS="$HOME/.cache/my-shared-target:$HOME/.cache/other-target"
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `SWEEP_TIME` | `10:00` | Daily sweep time, `HH:MM` in 24-hour local time. The installer reads it. |
| `SWEEP_MAX_AGE` | `86400` | Remove artifacts not used for this many seconds. Use whole seconds only: `3600` (1 hour), `21600` (6 hours), `86400` (1 day), `604800` (7 days). |
| `SWEEP_ROOTS` | `~/git` | Dirs to search for Cargo target dirs of any name, at any depth. The search includes hidden dirs such as `.worktrees`. |
| `SWEEP_TARGET_DIRS` | empty | Target dirs outside a project, for example a shared `CARGO_TARGET_DIR`. |
| `DRY_RUN` | `0` | Set to `1` to show what the sweep would remove, without removing it. |

Bash reads the file, so `$HOME` expands. A variable that is already set in the environment overrides the file. To use a different file, set `CARGO_SWEEP_TIMER_CONFIG`. The command stops if this file is missing or the config fails to load.

The installer reads `SWEEP_TIME` from `~/.config/cargo-sweep-timer/config.env` and writes it into the systemd timer or the launchd agent. After you change it, run `./install.sh` again. A value that is set in the environment of `install.sh` overrides the file. If the value is not a valid time, the installer shows a warning and uses 10:00. If the config fails to load, the installer stops before it changes files.

A low `SWEEP_MAX_AGE` value frees more disk space. The cost is that the next build of an old branch compiles its dependencies again.

`SWEEP_MAX_AGE` replaces `SWEEP_DAYS`. If `SWEEP_DAYS` is set in the config or the environment, the command stops before it sweeps. Multiply the old value by `86400`, for example `SWEEP_DAYS=7` becomes `SWEEP_MAX_AGE=604800`.

cargo-sweep uses the last access time of each artifact. Most Linux systems mount disks with `relatime`, which updates the access time at most once a day. With `noatime`, the access time does not change when a file is read. For this reason, a value below `86400` can remove artifacts that builds still use, and the next build compiles them again.

cargo-sweep does not remove the `incremental` dirs of a target dir. These dirs can contain most of the disk space of a target dir. Each subdir of an `incremental` dir is the cache of one crate build variant, for example a test build or a build with different features. If no build uses a variant again, its cache stays. Thus, after each sweep, the command also removes each subdir of an `incremental` dir that was not changed for `SWEEP_MAX_AGE` seconds. Each compile adds a new session dir to the subdir, so the command uses the modification time, not the access time. `noatime` does not have an effect on this removal. The cost is one full compile of that crate at its next build. With `DRY_RUN=1`, the command shows the subdirs, but does not remove them.

The command fails if a configured root is missing, if a dir in it cannot be read or searched, or if a `CACHEDIR.TAG` file in it cannot be read.

In a root, the command sweeps each Cargo target dir. A dir is a Cargo target dir when it contains one of these files:

- `CACHEDIR.TAG` that Cargo wrote. A `CACHEDIR.TAG` from a different tool does not count.
- `.rustc_info.json`. Old Cargo versions wrote this file but no `CACHEDIR.TAG`.

The dir name and the depth do not matter. Thus the command also finds a target dir that a build script or `CARGO_TARGET_DIR` puts in a different place, for example `target/issue-123` or `.build/target`. One sweep of a target dir also cleans the target dirs in it, so the command sweeps only the outermost target dir. This rule applies to all roots and to `SWEEP_TARGET_DIRS` together, thus each target dir gets one sweep only. The search does not go into the `incremental`, `.fingerprint`, `deps`, `build`, and `doc` dirs of a target dir, because they contain most of its files. The command searches a dir with one of these names that is not in a target dir.

The command follows a symlink only when its name is `target` and it points to a dir with a Cargo `CACHEDIR.TAG`.

The command does not load the projects, so a project that needs its own `.cargo/config.toml`, for example for a private registry, is swept too.

## Use on all systems

```sh
cargo-sweep-timer --dry-run              # show what a sweep would remove
cargo-sweep-timer                        # sweep now
SWEEP_MAX_AGE=604800 cargo-sweep-timer   # override one setting for one run
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

The timer runs each day at `SWEEP_TIME`. If the computer is off at that time, the missed sweep runs when your systemd user manager next starts, usually at login. The timer can delay the sweep by up to 15 minutes. To run without a login, enable lingering with `loginctl enable-linger "$USER"`.

To change the time, set `SWEEP_TIME`, then run `./install.sh` again. Refer to [Configure](#configure).

If you changed the time with a systemd drop-in before, the drop-in overrides `SWEEP_TIME`. To remove it, run `systemctl --user revert cargo-sweep-timer.timer`.

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

The installer writes the agent to `~/Library/LaunchAgents/com.dannyfranca.cargo-sweep-timer.plist`, then loads it. launchd does not set `XDG_CONFIG_HOME`, so the installer writes its value into the agent.

### Schedule on macOS

The agent runs each day at `SWEEP_TIME`. If the Mac sleeps at that time, the sweep runs when it wakes. If the Mac is off at that time, launchd skips the sweep until the next day. The agent runs only while you are logged in.

To change the time, set `SWEEP_TIME`, then run `./install.sh` again. Refer to [Configure](#configure).

### Folder access on macOS

macOS blocks access from the agent to the folders that it protects. These folders include:

- `~/Documents`, `~/Desktop`, and `~/Downloads`
- iCloud Drive (`~/Library/Mobile Documents`)
- Removable volumes and network volumes

If a sweep root is in a protected folder, give `/bin/bash` Full Disk Access in System Settings. Or, use a root outside these folders.

### Use on macOS

```sh
launchctl kickstart gui/$(id -u)/com.dannyfranca.cargo-sweep-timer   # sweep now, through launchd
launchctl print gui/$(id -u)/com.dannyfranca.cargo-sweep-timer       # agent state and last exit code
tail -f ~/Library/Logs/cargo-sweep-timer.log                          # logs of the sweeps
```

If the log is larger than 1 MiB when a sweep starts, the sweep clears the log first.

### Uninstall on macOS

The uninstaller unloads the agent. Then it removes the agent and the script. If launchd cannot confirm that the agent is unloaded, the uninstaller keeps the files and exits with an error.

## Test

Run `python3 -m unittest discover -s tests`. The tests need Python 3, Cargo, and cargo-sweep. The systemd unit test also needs systemd-analyze, and it is skipped without it. They use temporary projects and target dirs.
