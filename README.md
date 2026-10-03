# cargo-sweep-timer

Cargo does not delete old build artifacts. Each `target` dir grows until the disk is full. Worktrees make this worse, because each worktree has its own `target` dir.

This tool runs [cargo-sweep](https://github.com/holmgr/cargo-sweep) every day from a systemd user timer. It removes artifacts that were not used for a set number of days.

## Requirements

- Linux with systemd
- Cargo
- cargo-sweep: `cargo install cargo-sweep`. Some distros also have a package, for example `pacman -S cargo-sweep`.

## Install

```sh
git clone https://github.com/dannyfranca/cargo-sweep-timer.git
cd cargo-sweep-timer
./install.sh
```

The installer does these steps:

1. It copies the script to `~/.local/bin/cargo-sweep-timer`.
2. It copies the service and timer units to `~/.config/systemd/user/`.
3. It creates `~/.config/cargo-sweep-timer/config.env` from `config.example.env`. If this file exists, it does not change it.
4. It enables and starts the timer.

The service uses the `PATH` from the install command, with `$CARGO_HOME/bin` added if `CARGO_HOME` is set. If you change the Cargo location, run the installer again.

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

### Schedule

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

## Use

```sh
cargo-sweep-timer --dry-run                        # show what a sweep would remove
cargo-sweep-timer                                  # sweep now
SWEEP_DAYS=7 cargo-sweep-timer                     # override one setting for one run
systemctl --user start cargo-sweep-timer.service   # sweep now, through systemd
systemctl --user list-timers cargo-sweep-timer.timer
journalctl --user -u cargo-sweep-timer.service     # logs of the sweeps
```

## Uninstall

```sh
./uninstall.sh           # keeps your config
./uninstall.sh --purge   # also removes ~/.config/cargo-sweep-timer
```

## Test

Run `python3 -m unittest discover -s tests`. The tests need Python 3, Cargo, cargo-sweep, and systemd-analyze. They use temporary projects and target dirs.
