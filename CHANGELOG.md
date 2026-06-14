# Changelog

All notable changes are listed here. Versions follow [semver](https://semver.org) and the format
loosely follows [Keep a Changelog](https://keepachangelog.com).

## [0.4.0] - 2026-06-14

shell completion for every common shell, glob matching in `find`, and installs straight from git
or PyPI.

### Added
- `list --before DUR` shows only snapshots older than a duration, the mirror of `--since`. Useful
  for spotting stale snapshots before a `gc`.
- `completion bash|zsh|fish|powershell` prints a tab-completion script with no extra deps. Enable
  it with `eval "$(quicksave completion bash)"` in your shell rc, `quicksave completion fish | source`
  in fish, or `quicksave completion powershell | Out-String | Invoke-Expression` in PowerShell.
- `find` now accepts shell globs, so `find '*.py'` or `find 'src/**/test_*.py'` match by pattern.
  Queries without glob chars keep the old exact/prefix/substring behaviour.
- release workflow builds the sdist and wheel on a published release, attaches them to the release,
  and publishes to PyPI via trusted publishing. install straight from git with
  `pip install git+https://github.com/qorexdevs/quicksave`.

## [0.3.0] - 2026-06-13

Most of this is about finding and bringing back files after they're already gone, plus moving
checkpoints between machines.

### Added
- `find` and `recover` - find which snapshots still hold a file you lost, or just bring it back from
  the newest one that has it, even after `rm`.
- `undo` - revert the last restore back to the pre-restore tree. A restore now snapshots the tree
  first so a wrong one is always undoable.
- `verify` and `verify --repair` - rehash the store to catch corrupt or missing blobs, and drop
  snapshots that reference them.
- `stats` - store size and how much dedup is saving you, with `--markdown` for a shareable table.
- `name` and `pin` / `unpin` - label a snapshot after the fact, and keep one out of `gc` rotation.
- `export` / `import` a snapshot as a tar, gzip with `-z`, and stream through stdin/stdout so you can
  pipe a checkpoint to another machine over ssh.
- `log` to show one snapshot's details, with `--json`.
- relative time in `list` by default, `--absolute` for full timestamps.
- `NO_COLOR` support: set it to any value and output is plain text, per [no-color.org](https://no-color.org).
- ci now runs on macos and windows too, not just linux.

### Changed
- `list` gained `--limit`, `--since`, `--grep`, `--pinned`, `--reverse`.
- `diff` can compare a snapshot against the live working tree and show a line-level diff of one file,
  plus `--json`.
- `restore` got `--dry-run`, `--into` to pull a snapshot aside without touching the live tree, and it
  defaults to the latest snapshot.
- `status --exit-code` for scripts, a global `--quiet`, and `--json` on more commands.
- `gc` can drop specific snapshots by ref or anything older than a duration, and reports the space it
  frees, with `--json`.
- refs can count back from newest with `latest` and `~N`.

### Fixed
- a `.gitignore` negation (`!keep.log`) no longer flips into an ignore rule.
- `-q` / `--quiet` no longer silences later commands in the same process.
- clean error on importing a non-tar file, and timestamps survive an export/import round trip.

## [0.2.0] - 2026-06-09

First tagged release. quicksave keeps a local, content-addressed checkpoint of your working tree so
you can roll back files an agent deleted or overwrote, even ones git never tracked.

### Added
- `init` / `save` / `list` / `restore`. restore is additive by default; `--clean` does an exact
  rewind.
- selective restore of a single file or directory.
- `status` and `diff` to see what changed since a snapshot or between two.
- `show` to print one file from a snapshot to stdout.
- `gc` to drop old snapshots and unreferenced blobs.
- a `PreToolUse` hook (`quicksave hook`) plus `hook install` for Claude Code and Codex, to
  auto-checkpoint before a risky command.

[0.4.0]: https://github.com/qorexdevs/quicksave/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/qorexdevs/quicksave/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qorexdevs/quicksave/releases/tag/v0.2.0
