# Command reference

Every quicksave subcommand, its options, and a short example. The README has the prose; this is the
lookup table. `quicksave --help` and `quicksave <cmd> --help` print the same flags from the parser.

Global flags that work on every command:

- `-q`, `--quiet` - silence normal output, keep only errors (on stderr) and `--json`. Works before or
  after the subcommand.
- `--version` - print the version and exit.
- `NO_COLOR` (env) - set to any value for plain text without styling, per [no-color.org](https://no-color.org).

A snapshot **ref** is anything that names a checkpoint: its number from `list`, its short id, a name
you set, `latest`, `latest~N` / `~N` (count back from newest), or `@<time>` (newest snapshot at least
that long ago, e.g. `@10m`, `@2h`, `@2026-06-01`). See [Refs](#refs) at the bottom.

## init

Start tracking the current directory. Creates `.quicksave/` and is a no-op if it already exists.

```
quicksave init           # track the current directory
quicksave init path/to/dir
```

## save

Snapshot the working tree. Skipped when nothing changed since the last snapshot unless `--force`.

- `-m`, `--message TEXT` - snapshot message, or `-` to read it from stdin.
- `-n`, `--name NAME` - label the snapshot so you can restore it by name. Names can't be all digits.
- `-f`, `--force` - snapshot even if nothing changed.
- `--dry-run` - show what would be captured without writing anything.
- `--json` - print the saved snapshot id and file count.

```
quicksave save -m "before refactor"
quicksave save -n pre-deploy
git log -1 --format=%s | quicksave save -m -
quicksave save --dry-run
```

## list

List snapshots, oldest first, with file count, size and relative time.

- `--limit N` - only the N most recent.
- `--absolute` - full timestamps instead of "2h ago".
- `--pinned` - only pinned snapshots.
- `--since DUR`, `--before DUR` - only snapshots newer / older than a duration (`1h`, `7d`) or date.
- `--grep TEXT` - only snapshots whose message or name contains TEXT.
- `--reverse` - newest first; pairs with `--limit` for the last few.
- `--count` - print only the number of matching snapshots, after the filters above.
- `--json` - machine-readable output.

```
quicksave list
quicksave list --limit 5 --reverse
quicksave list --grep wip --count
quicksave list --since 1h
quicksave list --grep "rm -rf"
```

## names

List just the named snapshots, id and name, newest first.

- `--grep TEXT` - show only names containing the text, case-insensitive.
- `--reverse` - oldest first instead of newest first.
- `--limit N` - show only the N most recent named snapshots; pairs with `--reverse`.
- `--count` - print just the number of matching names, nothing else.
- `--json` - same as a json list.

```
quicksave names --limit 5
```

## stats

Store size and how much dedup is saving you.

- `--top N` - show the N snapshots holding the most uniquely-owned bytes (what `drop` would reclaim).
  Defaults to 5, `0` hides the table.
- `--markdown` - the same numbers as a markdown table to paste into a readme or tweet.
- `--json` - the stats as json, including `saved_bytes` and `ratio`.

```
quicksave stats
quicksave stats --markdown
quicksave stats --top 10
```

## find

Find which snapshots hold a file, newest first. The query matches an exact path, a directory prefix,
part of a name, or a glob (`*.py`, `src/**/test_*.py`). Pass several paths to match any of them.

- `-i`, `--ignore-case` - match the path without regard to case.
- `--since DUR`, `--before DUR` - scope to a time window.
- `--changes` - collapse snapshots where the matched content is the same, so you see only where the
  file actually changed. The oldest match is always kept.
- `--diff` - with `--changes`, print a unified diff between each consecutive change point
  (single-file queries only).
- `--reverse` - oldest match first, to read a file's history forward.
- `--limit N` - only the N newest matches.
- `--count` - print only the number of matching snapshots.
- `--json` - matches as json.

```
quicksave find app.py
quicksave find '*.py' --since 2h
quicksave find -i readme
quicksave find src/app.py --changes --diff
```

## recover

Bring a file back from the newest snapshot that still has it, even if it was deleted several commands
ago and isn't in the latest snapshot. Backs the tree up first so `undo` reverts it. Pass several paths
and each resolves to its own newest snapshot under one pre-restore backup.

- `--from REF` - recover from this snapshot instead of the newest match (for when the newest copy is
  itself broken).
- `--into DIR` - write the matches into DIR instead of overwriting the tree.
- `--dry-run` - show which files would come back, and from which snapshot, without writing.
- `--no-backup` - don't snapshot the current tree first.
- `--json` - print which snapshot was used and the recovered files.

```
quicksave recover app.py
quicksave recover app.py utils.py config.json
quicksave recover app.py --from 3
quicksave recover app.py --into /tmp/old
```

## restore

Restore files from a snapshot (latest by default). Additive: it won't touch new files you created
after the snapshot. Snapshots the current tree first, so a wrong restore is itself undoable.

- `ref` - snapshot id, number or name (default latest).
- `paths...` - only restore these files or directories.
- `--clean` - exact rewind: also delete files the snapshot didn't have.
- `--dry-run` - preview what would be written or deleted, no changes. With `--into` it previews against DIR.
- `--into DIR` - write the snapshot into DIR, leave the live tree alone.
- `--no-backup` - skip the safety snapshot of the current tree.
- `--json` - report the files restored, the removed count and the backup id.

```
quicksave restore
quicksave restore pre-deploy --clean
quicksave restore 3 src/app.py
quicksave restore @10m
```

## undo

Revert the last restore, back to the pre-restore tree.

- `--clean` - also delete files the restore added.
- `--no-backup` - don't snapshot the current tree before undoing.

```
quicksave undo
```

## status

Show what changed in the working tree since a snapshot (latest by default).

- `ref` - snapshot to compare against (default latest).
- `--short` - one line like `~3 +1 -0`, or `clean`.
- `--stat` - only the summary line (`N added, N removed, N modified`), or `clean`.
- `--name-only` - just the changed paths, one per line, no markers and no summary.
- `--name-status` - each path prefixed with `A`/`D`/`M` and a tab, like `git diff --name-status`.
- `--exit-code` - exit 1 if the tree changed, 0 if clean, like `git diff --exit-code`.
- `--json` - the diff as json.

```
quicksave status
quicksave status --short
quicksave status --stat
quicksave status --name-only
quicksave status --name-status
quicksave status --exit-code
```

## check-ignore

Test paths against the ignore rules and show which rule decided each one, like `git check-ignore -v`.
Use it when a file you expected to be saved isn't showing up (or one you wanted skipped is).

- `path...` - one or more paths to test.
- `--exit-code` - exit non-zero unless every listed path is ignored.
- `--json` - print the verdicts as json, with `ignored`, `rule`, `source` and `line` per path.

The `source` is the ignore file the matching rule came from (`.gitignore` or `.quicksaveignore`), or
`built-in` for the baked-in dir names like `node_modules`. Last match wins, and `.quicksaveignore` is
read after `.gitignore`, so a `!.env` there overrides a `.env` ignore upstream.

```
quicksave check-ignore .env build/out.js src/app.py
quicksave check-ignore --json secrets.txt
```

## diff

Show what changed between two snapshots, or a snapshot and the working tree. The ref `wt` stands in
for the live tree on either side. Add a path for a line-by-line diff of one file.

- `a` - first ref, or `wt`.
- `b` - second ref, or `wt` (default).
- `path` - line-by-line diff of just this file.
- `--stat` - only the summary line, skip the file list.
- `--name-only` - just the changed paths, one per line.
- `--name-status` - each path prefixed with `A`/`D`/`M` and a tab, like `git diff --name-status`.
- `--numstat` - added/removed line counts per file as `added<tab>removed<tab>path`, like `git diff --numstat`. Binary files show `-` for both counts. With `--json` the counts come back as a `files` list.
- `-p`, `--patch` - a unified diff of every changed file, like `git diff`. Binary files are noted, not dumped.
- `--git` - with `-p`, emit a `git apply`/`patch -p1` compatible diff: `a/`/`b/` headers, `/dev/null` for added or removed files, and no color. Binary notes go to stderr so the stream stays clean.
- `--json` - the diff as json.

```
quicksave diff 2 3
quicksave diff 3            # tree vs snapshot 3
quicksave diff 2 3 src/app.py
quicksave diff 2 3 --stat
quicksave diff 2 3 -p
quicksave diff 0 wt -p --git | git apply   # replay the change somewhere else
quicksave diff 0 wt --name-status | grep '^M'
quicksave diff 2 3 --numstat
```

## show

Print one file's contents to stdout, from a snapshot or the newest one that has it. Doesn't touch disk.

- `ref` - snapshot id or number, or the file itself for the newest snapshot that has it.
- `path` - file to print (omit to treat ref as the file).
- `-n`, `--number` - number the output lines, like `cat -n`, so a `grep` hit at line N is easy to find.

```
quicksave show 3 src/app.py
quicksave show config.py            # newest snapshot that still has it
quicksave show 3 config.py > config.old.py
quicksave show -n src/app.py        # numbered, to line up with a grep hit
```

## grep

Search a snapshot's file contents for a pattern, the read-only counterpart to `find` (which only
matches paths). Prints `path:line:text` for each match. Binary blobs are skipped.

- `pattern` - regular expression, or a literal string with `-F`.
- `paths...` - limit the search to these paths.
- `-r`, `--ref` - snapshot id, number or name (default latest).
- `-i`, `--ignore-case` - case-insensitive match.
- `-F`, `--fixed` - treat the pattern as a literal, not a regex.
- `-w`, `--word` - match whole words only, so `foo` won't hit `foobar`.
- `-x`, `--line-regexp` - match whole lines only, so the pattern must equal the entire line. When both `-x` and `-w` are passed, `-x` wins.
- `-v`, `--invert-match` - show the lines that do not match the pattern.
- `-A N`, `--after-context` - print N lines of context after each match.
- `-B N`, `--before-context` - print N lines of context before each match.
- `-C N`, `--context` - print N lines of context on both sides.
- `-o`, `--only-matching` - print only the matched part of each line, one match per line.
- `--no-filename` - drop the `path:` prefix so each line is just `line:text`, handy when piping matches on. Affects the default and context output only; `--count`/`-c`/`-l`/`-L`/`--json` ignore it.
- `-m N`, `--max-count` - stop after N matching lines per file, like `grep -m`. `0` is no cap.
- `-l`, `--name-only` - print only the matching file paths.
- `-L`, `--files-without-match` - print only the paths of text files with no match, the complement of `-l`. Can't be combined with `-l`.
- `-c`, `--count-per-file` - print `path:count` of matching lines for each file that matched, sorted by path. Files with no match are left out. Can't be combined with `-l`/`-L`.
- `--count` - print only the number of matching lines.
- `--json` - print matches as json.

Context lines use a `-` separator (`path-line-text`) instead of the `:` of a match, and
non-adjacent groups are split by a `--` divider, like `grep`. Context is ignored by `--count`,
`--count-per-file`, `--name-only`, `--files-without-match` and `--json`, which only report files or matches.

```
quicksave grep TODO
quicksave grep -i "api_key" -r pre-deploy src/
quicksave grep -w -F "a.b.c" --name-only
quicksave grep -x TODO                   # lines that are exactly "TODO", not "TODO: fix later"
quicksave grep -C 2 "def main"
quicksave grep -o "[A-Z]+_[A-Z]+" -r v1   # pull just the env var names out
quicksave grep -m 1 -l TODO               # first file with a TODO, stop early
quicksave grep -L "Copyright" src/        # source files missing the license line
quicksave grep -c TODO                     # which file has the most TODOs
```

## export

Write a snapshot to a tar archive without touching the tree. A `.gz`/`.tgz` name gives a gzipped
archive, anything else a plain tar. Use `-` for stdout.

- `dest` - output path, or `-` for stdout.
- `ref` - snapshot id, number or name (default latest).
- `paths...` - limit the export to these paths.
- `-z`, `--gzip` - gzip the archive, even when streaming to stdout.

```
quicksave export backup.tar.gz pre-deploy
quicksave export - -z | ssh host 'cd repo && quicksave import -'
```

## import

Read a tar archive back into a new snapshot without touching the tree. Archives with absolute or `..`
paths are rejected. Use `-` for stdin.

- `src` - archive to read, or `-` for stdin.
- `-m`, `--message TEXT` - snapshot message.
- `--name NAME` - label for the new snapshot.
- `--dry-run` - show what the archive holds without writing a snapshot.

```
quicksave import backup.tar.gz --name recovered
quicksave import backup.tgz --dry-run
```

## log

Show one snapshot's details: id, name, pinned flag, message, time, and the file list with sizes.

- `ref` - snapshot id, number or name (default latest).
- `--json` - the details as json.
- `--name-only` - just the file paths, one per line, no sizes or header.

```
quicksave log
quicksave log pre-deploy --json
quicksave log v1 --name-only | xargs wc -l
```

## name

Label a snapshot after the fact, or clear its name with an empty value.

```
quicksave name 3 good-build
quicksave name 3               # clear the name
```

## pin / unpin

Protect a snapshot from `gc --keep` rotation, or let it rotate again.

```
quicksave pin 4
quicksave unpin 4
```

## verify

Check the store for corrupt or missing blobs.

- `--repair` - drop snapshots that point at corrupt or missing blobs.
- `--dry-run` - with `--repair`, show what would be dropped without touching the store.
- `--json` - the result as json, for plain verify and `--repair` alike (with `--repair`: `dropped`,
  `corrupt_blobs`, `blobs`, `dry_run`).

```
quicksave verify
quicksave verify --repair --dry-run
quicksave verify --repair --json
```

## gc

Drop old snapshots and blobs nothing points at, and report space freed.

- `refs...` - drop these specific snapshots too.
- `--keep N` - keep only the N most recent.
- `--older-than DUR` - drop snapshots older than a duration or date.
- `--keep-named` - spare named snapshots from rotation, like pinned ones.
- `--keep-within DUR` - spare snapshots newer than the window from `--keep`.
- `--dry-run` - show what would be removed without deleting.
- `--json` - what gc removed as json.

```
quicksave gc --keep 10
quicksave gc --older-than 7d
quicksave gc --keep 5 --keep-within 2h
```

## drop

Drop snapshots by ref and reclaim their blobs.

- `refs...` - one or more snapshot ids, numbers or names.
- `--force` - drop even if pinned.
- `--dry-run` - show what would be removed without deleting.
- `--json` - what drop removed as json.

```
quicksave drop 4 7 pre-deploy
quicksave drop 4 --dry-run
```

## completion

Print a tab-completion script for your shell.

```
eval "$(quicksave completion bash)"            # bash, in ~/.bashrc
eval "$(quicksave completion zsh)"             # zsh, after compinit
quicksave completion fish | source             # fish
quicksave completion powershell | Out-String | Invoke-Expression   # powershell
```

## hook / hook install

`quicksave hook` reads a `PreToolUse` payload on stdin and snapshots before a risky bash command,
staying quiet so it never blocks the agent. `quicksave hook install` writes the config for you.

- `hook install --tool {claude,codex}` - which runner to wire up (default claude).
- `hook --check '<command>'` - print `risky`/`safe` for a command and exit (0 risky, 1 safe),
  without saving. On a hit the matching pattern follows after a tab, so you can
  see what tripped while tuning `QUICKSAVE_RISKY`.
- `hook --check -` - read commands from stdin, one per line, and print a verdict per line
  (`risky\t<pattern>\t<command>` or `safe\t<command>`). Exits 0 if any line is risky, 1 if none
  are, so it composes in scripts. Blank lines are skipped.

```
quicksave hook install
quicksave hook install --tool codex
quicksave hook --check 'rm -rf build'   # risky	\brm\b
quicksave hook --check 'terraform destroy'
cat commands.txt | quicksave hook --check -
```

`QUICKSAVE_KEEP=N` caps the history the hook keeps to the N most recent snapshots, dropping older
ones after each save.

`QUICKSAVE_RISKY` adds your own patterns to the builtin risky list, one regex per line. Use it for
project-specific footguns the defaults don't cover:

```
export QUICKSAVE_RISKY='terraform\s+destroy
make\s+clean
docker\s+compose\s+down\s+-v'
```

Invalid regexes are skipped quietly, and an unset variable keeps the default behavior.

## Refs

Anywhere a command takes a snapshot ref you can use:

- a number from `list` (`3`), or `0` for the oldest in the current view.
- a short id (`a1b2c3`).
- a name you set with `save -n` or `name` (`pre-deploy`). Names can't be all digits, so they never
  clash with the list numbers; if you reuse a name the most recent one wins.
- `latest` for the newest, `latest~N` or `~N` to count back from it.
- `@<time>` for the newest snapshot at least that long ago: `@10m`, `@2h`, `@7d`, or an absolute date
  like `@2026-06-01`.

## Ignoring files

Caches and vendored deps are skipped by default (`.git`, `node_modules`, `__pycache__`, `venv`,
`.venv`, `dist`, `build`). Drop a `.quicksaveignore` with gitignore-style globs in the project root to
skip more; an existing `.gitignore` is read too.

Rules follow gitignore's last-match-wins order, and a leading `!` re-includes a path an earlier rule
ignored. `.quicksaveignore` is read after `.gitignore`, so it can override it. That matters for files
git ignores but you still want to recover: if `.env` is in your `.gitignore`, add `!.env` to
`.quicksaveignore` and quicksave will keep capturing it. As with git, a `!` rule can't re-include a
file whose parent directory is already ignored.
