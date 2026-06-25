# Changelog

All notable changes are listed here. Versions follow [semver](https://semver.org) and the format
loosely follows [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

## [0.9.0] - 2026-06-25

### Added
- `restore --into DIR --dry-run` previews what would land in DIR (created vs overwritten) instead of
  ignoring the flag; the plan and the `--json` output's new `into` field measure against DIR, so
  files already there read as overwritten.
- `diff --numstat` prints added/removed line counts per file as `added<tab>removed<tab>path`, like
  `git diff --numstat`. Binary files show `-` for both counts. Works between two snapshots and
  against the working tree; with `--json` the counts come back as a `files` list.
- `grep -o`/`--only-matching` prints just the matched part of each line, one match per line, so
  repeated matches on a line each print separately. Composes with `-i`, `-F`, `-w`, a path filter
  and `--json` (which carries the fragment in `text`); `--count` and `--name-only` still report
  matching lines and files.

### Fixed
- `grep -o -v` now prints nothing instead of ignoring `-v` and printing matches. `-o` emits only the
  matched text, so on the non-matching lines `-v` selects there is nothing to print, like GNU grep.

## [0.8.0] - 2026-06-25

### Added
- `grep -A`/`-B`/`-C` print context lines around each match, like `grep`. Context lines use a
  `-` separator instead of `:`, overlapping windows merge, and non-adjacent groups are split by a
  `--` divider. `--count`, `--name-only` and `--json` ignore context and report only matches.
- `grep -v`/`--invert-match` shows the lines that do not match the pattern, like `grep -v`.
  Composes with `--count`, `--name-only`, `--json`, `-i`, `-F` and a path filter.
- `grep -w`/`--word` matches whole words only, anchoring the pattern to word boundaries so `foo`
  no longer hits `foobar`. Works with `-F`, `-i`, `--count`, `--name-only` and a path filter.
- `verify --repair --json` now emits the repair result (`dropped`, `corrupt_blobs`, `blobs`,
  `dry_run`) instead of only the rich text, so a hook or CI step can repair the store and read
  what it did. Plain `verify --json` already worked; `--repair` ignored the flag.

## [0.7.0] - 2026-06-23

### Added
- `QUICKSAVE_RISKY` lets you add your own risky-command patterns, one regex per line, appended to the
  builtin list so project footguns like `terraform destroy`, `make clean` or `docker compose down -v`
  also trigger a checkpoint. Invalid regexes are skipped quietly, unset keeps the current behavior.
- `quicksave hook --check '<command>'` prints `risky`/`safe` for a command without running the agent,
  exiting 0 when it would snapshot and 1 otherwise, so you can tune `QUICKSAVE_RISKY` patterns. On a
  hit it also prints the matching pattern after a tab, so you can see exactly what tripped.
- the hook now treats `unlink` and `git worktree remove` as risky, so an agent that deletes a file
  with `unlink` or wipes a linked worktree gets a checkpoint first, the same as `rm` and `git clean`.
- `grep <pattern>` searches a snapshot's file contents for a regex (or a literal with `-F`), the
  read-only counterpart to `find` which only matches paths. Prints `path:line:text`, with `-i` for
  case-insensitive, `-l`/`--name-only` for just the files, `--count` for the match total, `--json`,
  an optional `-r`/`--ref` (default latest), and trailing paths to narrow the search. Binary blobs
  are skipped, so you can locate a line in a checkpoint without restoring it.
- `diff -p --git` emits a `git apply`/`patch -p1` compatible patch: `a/`/`b/` path headers,
  `new file mode`/`deleted file mode` with `/dev/null` for added and removed files, and no color, so
  you can replay the change between two checkpoints elsewhere with `quicksave diff 0 wt -p --git | git apply`.
  Binary-file notes go to stderr so the patch stream stays clean. Plain `-p` keeps its annotated,
  colored output for reading.
- `diff -p`/`--patch` prints a unified diff of every changed file between two snapshots, or a
  snapshot and the working tree, like `git diff`. Until now the whole-tree `diff` only listed paths
  and you had to name a single file to see line changes; now `quicksave diff 0 1 -p` shows the full
  content delta in one go, with binary files noted instead of dumped.
- `diff -p --json` now emits the patch as `{"a","b","files":[{"path","diff"}]}` instead of falling
  back to the path-list json, mirroring the single-file `diff a b path --json`. Binary files come
  through as `"diff": null`.
- `status --name-status` and `diff --name-status` prefix each changed path with `A`, `D` or `M`
  and a tab, like `git diff --name-status`, so a script can tell added/removed/modified apart that
  `--name-only` flattens together, e.g. `quicksave diff 0 wt --name-status | grep '^M'`.
- `log --name-only` prints just the file paths in a snapshot, one per line, no sizes or header,
  matching the `--name-only` flag `status` and `diff` already have. Pipes straight into other
  tools, e.g. `quicksave log v1 --name-only | xargs wc -l`.
- `status --stat` prints only the summary line (`N added, N removed, N modified`), or `clean`,
  matching the `--stat` flag `diff` already has. Works with `--exit-code` too.
- `names --limit N` shows only the N most recent named snapshots, the same way `list` and `find`
  already cap their output. It keeps the newest N regardless of `--reverse`, and like `list` it
  leaves `--json` and `--count` unbounded, printing a `showing N of M` footer when it trims.
- `status --name-only` prints just the changed paths, one per line, no markers and no summary,
  matching the flag `diff` already has. Pipes straight into other tools, e.g.
  `quicksave status --name-only | xargs ruff check`. Works with `--exit-code` too.
- `names --count` prints just the number of named snapshots, nothing else, honoring `--grep`,
  matching the `--count` flag `list` and `find` already have.
- `list --count` prints just the number of matching snapshots, nothing else, the same way
  `find --count` already does. It honors the `--pinned`, `--since`, `--before` and `--grep` filters,
  so `quicksave list --grep wip --count` answers "how many wip checkpoints do I have" in a script.
- shell completions now offer the shared flags (`--json`, `--dry-run`, `--quiet`, `--help`) after a
  subcommand, not just the subcommand name, before falling back to file paths. Covers bash, zsh,
  fish and powershell.
- the auto-save hook now treats `tee` (writing, not `-a`/`--append`) and `git switch` with
  `-f`/`--force`/`--discard-changes` as risky, so a checkpoint lands before either can overwrite a
  file or throw away uncommitted work.
- `check-ignore PATH...` tells you whether a path would be captured or ignored and which rule
  decided it, like `git check-ignore -v`. It reports the source file and line (or `built-in` for the
  baked-in dir names), so when `.env` won't save you can see which `.gitignore` line caught it and
  whether a `!.env` in `.quicksaveignore` overrode it. `--json` and `--exit-code` too.
- `names --grep TEXT` lists only named snapshots whose name contains the text, case-insensitive,
  the same way `list --grep` filters. Handy once you've labeled a lot of checkpoints.
- `names --reverse` shows named snapshots oldest first instead of newest first, mirroring the
  `--reverse` flag `list` and `find` already have.
- ignore rules now honor `!` negation with gitignore-style last-match-wins. `.quicksaveignore` is
  read after `.gitignore` so it can override it - if `.env` is gitignored, `!.env` in
  `.quicksaveignore` keeps quicksave capturing it, which is the whole point of the tool.

## [0.6.0] - 2026-06-21

### Added
- `find --reverse` lists matches oldest first instead of newest, so you can read a file's history
  forward. Mirrors the `--reverse` flag `list` already has.
- `docs/commands.md` - a full per-command reference with every flag and a short example each, plus
  a refs and ignore-rules section. Linked from the README so the usage block stays the quick list.
- `save -m -` reads the snapshot message from stdin, so you can pipe one in
  (`git log -1 --format=%s | quicksave save -m -`) instead of quoting it on the command line.
  The trailing newline is stripped. Mirrors the `-` convention `import` already uses for its source.
- `stats --top N` lists the N snapshots holding the most uniquely-owned bytes (blobs no other
  snapshot references), so you can see what `drop` would actually reclaim. Defaults to 5, `0` hides
  the table, and `--json` includes the same list.
- `gc --keep-within <duration>` spares snapshots newer than the window from `--keep` rotation, so
  `gc --keep 5 --keep-within 2h` trims down to five but never drops a checkpoint from the last two
  hours. Takes the usual `2h`/`30m`/date forms and stacks with `--keep-named` and `--older-than`.
- `restore --json` prints the result instead of the styled line: the ref, how many files came
  back, the removed count and the safety-backup id, so a hook can roll back and then check what
  happened. With `--dry-run --json` it emits the plan (created/overwritten/removed/missing) and
  writes nothing, matching `recover --json`.
- `import --dry-run` previews an archive before it lands: file count, total size, the name it
  would carry and the first paths, without writing any blobs or a snapshot. Handy for peeking at
  a tarball someone handed you before it turns into a checkpoint.
- `@<time>` snapshot refs point at the tree as it was that long ago: `@10m` is the newest
  snapshot from at least ten minutes back, so `quicksave restore @10m` rolls you back without
  hunting for an id. Works anywhere a ref is taken (restore, status, show, diff) and accepts
  durations like `2h`/`7d` or an absolute date.
- `export` stashes the snapshot name in the archive and `import` restores it, so a labeled
  checkpoint keeps its name across the round trip. Pass `--name` on import to override it.
  The name rides under the always-ignored `.quicksave/` prefix, so it never shows up as a file.
- `find` takes more than one path now, the way `recover` does, so `find app.py config.json`
  lists every snapshot holding either, with the matched files merged per snapshot.
- `find -i`/`--ignore-case` matches the path case-insensitively, so `find readme` reaches
  `README.md`. Works for substring, prefix, and glob queries; the default stays case-sensitive.
- `find --since`/`--before` scope the search to a time window, the same way `list` does, so
  `find config.json --since 2h` only lists recent snapshots holding it. Both take a duration
  (`30m`, `7d`) or an absolute date and combine with `--changes`, `--limit` and `--count`.
- `find --changes` collapses snapshots where the matched file's content is the same, so you
  see only the checkpoints where it actually changed - a real history for a file that was
  never in git. The oldest match is always kept since that's where the content first appears.
- `names` lists just the named snapshots, id and name, newest first, with `--json`. Saves
  scanning the full `list` output when you only want to see the labels you've set.
- `status --short` prints a one-line porcelain summary like `~3 +1 -0` (modified/added/removed),
  or `clean`, instead of the per-file list, so a shell prompt or an agent can read drift at a
  glance. `--json` still wins when both are passed, and `--exit-code` works the same.
- `diff --stat` prints only the summary line (`5 added, 2 removed, 3 modified`) and skips the
  per-file list, for a quick "how much changed" check. Ignored in single-file mode.
- `gc --keep-named` spares named snapshots from `--keep` and `--older-than` rotation, the same
  way pinned ones are spared. An explicit `gc <ref>` still drops a named snapshot when you mean it.
- `log` shows the total size next to the file count (`Files: 42 (3.2M)`), so you don't have to
  add the per-file sizes up by hand.

### Fixed
- `log` now prints file sizes like `4.1K` instead of raw `4200 bytes`, matching `list`, `find`
  and `stats`.

### Changed
- the hook now treats `git rm`, `git stash`, `rsync --delete`, and a noclobber-overriding `>|`
  redirect as risky too, so an agent that reaches for one of those gets a checkpoint first. `>>`
  appends and a plain `rsync` without `--delete` are still left alone.

## [0.5.0] - 2026-06-20

batch recover and drop, working-tree diffs, and dry-run previews across save, restore and recover.

### Added
- `recover` takes more than one path at a time, like `drop` already does: each path resolves to its
  own newest snapshot (or the one from `--from`), a single pre-restore backup covers the whole batch
  so one `undo` rewinds them all, and `--json` lists what came back per path under `results`. A path
  that matches nothing is skipped with a note instead of aborting the rest.
- `diff REF` now defaults its second side to the working tree, so `quicksave diff 3` shows what the
  live tree changed since snapshot 3. `diff 3 5` still compares two snapshots.
- `recover --from REF` pulls a file from a snapshot you name instead of the newest one that holds
  a match, for when that newest copy is itself broken. `find` lists the candidates newest first,
  then `recover --from <id>` grabs the one you want; errors if that snapshot has no match.
- `recover --json` prints which snapshot it pulled from and the recovered file paths, so scripts
  can act on the result the way `find --json` and the other `--json` commands already allow. When
  nothing matches it emits an empty result instead of exiting non-zero.
- `drop <ref>...` removes one or more snapshots by id, number or name and reclaims any blobs they
  were the last to reference, for killing bad checkpoints without a `gc --keep` policy. Refuses a
  pinned snapshot unless `--force`; `--dry-run` previews the blob sweep without deleting.
- `--since`/`--before` and `gc --older-than` now also accept an absolute date like `2026-06-01`
  or `2026-06-01T12:00`, not just relative durations. The date is read as the cutoff directly.
- `recover --into DIR` writes the matches into another directory instead of overwriting the live
  tree, so you can inspect a recovered file before clobbering the working copy, the same way
  `restore --into` already works.
- `recover --dry-run` shows which files would come back and from which snapshot without writing
  anything or taking a backup, the same preview `restore --dry-run` already gives.
- `save --dry-run` previews what a snapshot would capture - new, modified and removed files since
  the last snapshot, with a file count and total size - without writing blobs or a manifest. Handy
  for catching build artifacts you forgot to ignore before they land in the store.
- `stats --json` now carries `saved_bytes` and `ratio` so scripts get the dedup numbers straight
  instead of recomputing logical minus disk themselves.

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

[0.7.0]: https://github.com/qorexdevs/quicksave/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/qorexdevs/quicksave/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/qorexdevs/quicksave/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/qorexdevs/quicksave/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/qorexdevs/quicksave/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/qorexdevs/quicksave/releases/tag/v0.2.0
