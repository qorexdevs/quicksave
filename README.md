# quicksave

[![ci](https://github.com/qorexdevs/quicksave/actions/workflows/ci.yml/badge.svg)](https://github.com/qorexdevs/quicksave/actions/workflows/ci.yml)

F5 for your filesystem. Checkpoint before every risky command, restore even after `rm -rf`.

Coding agents run shell commands you didn't read. Most undo tools only track git or the editor's
own session, so an agent's `rm`, `mv`, or a stray script can wipe files that nothing was watching.
quicksave snapshots the whole working tree into a local content-addressed store, so you can roll
back to any checkpoint - including files that were never committed.

<p align="center"><img src="assets/demo.svg" alt="quicksave demo: an agent runs rm -rf, one restore brings the files back" width="660"></p>

## Quick tour

An agent wipes a source dir and your `.env`, and git never tracked either. One restore brings it all
back ([examples/tour.sh](examples/tour.sh) runs this end to end):

```
$ quicksave init
initialized quicksave in /tmp/demo
$ quicksave save -n pre-agent -m "before the agent runs"
saved 98c66e6a3d2e pre-agent (3 files) before the agent runs

$ rm -rf src .env        # the agent wipes files git never tracked
$ ls -A
.quicksave
README.md

$ quicksave restore pre-agent --clean
backed up current tree as c8aca5f9b067
restored 3 files from pre-agent before the agent runs
$ ls -A && cat src/app.py
.env
.quicksave
README.md
src
def main():
    print("hi")
```

## Install

Latest from git:

```
pip install git+https://github.com/qorexdevs/quicksave
```

Or grab a wheel from the [releases page](https://github.com/qorexdevs/quicksave/releases). For local
hacking, clone and `pip install -e .`.

Needs Python 3.10+.

## Usage

```
quicksave init                 # start tracking this directory
quicksave save -m "before refactor"
quicksave save -n pre-deploy   # tag the snapshot with a name
quicksave save --json          # print the new snapshot's id and file count for a script or hook
quicksave save --dry-run       # preview what a snapshot would capture, nothing written
quicksave list                 # snapshots with file count, size and "2h ago" relative time
quicksave list --absolute      # show full timestamps instead of relative time
quicksave list --pinned        # only the snapshots you pinned out of gc rotation
quicksave list --since 1h      # only snapshots from the last hour (1h, 30m, 7d)
quicksave list --before 7d     # only snapshots older than a week, handy before gc
quicksave list --grep "rm -rf" # only snapshots whose message or name matches
quicksave list --reverse       # newest first, pairs with --limit for the last few
quicksave restore              # roll back to the latest snapshot
quicksave restore 3            # restore by number from the list
quicksave restore a1b2c3       # or by id
quicksave restore pre-deploy   # or by the name you gave it
quicksave restore 3 src/app.py # only pull back one file or directory
quicksave restore 3 --clean    # exact rewind: also delete files added after the snapshot
quicksave restore 3 --dry-run  # preview what restore would write or delete, no changes
quicksave restore 3 --no-backup # skip the safety snapshot of the current tree
quicksave restore 3 --into /tmp/old # pull the snapshot aside, leave the live tree alone
quicksave undo                 # revert the last restore, back to the pre-restore tree
quicksave name 3 good-build    # tag an existing snapshot after the fact (empty name clears it)
quicksave names                # list just the named snapshots, newest first
quicksave status               # what changed in the tree since the last snapshot
quicksave status --short       # one line like '~3 +1 -0' (or 'clean') for a prompt or agent
quicksave status --exit-code   # exit 1 if the tree changed, like 'git diff --exit-code'
quicksave find app.py          # which snapshots still hold a file you lost, newest first
quicksave recover app.py       # just bring it back from the newest snapshot that has it
quicksave recover app.py util.py config.json # several at once, each from its own newest snapshot
quicksave recover app.py --from 3 # pull it from snapshot 3 if the newest copy is already broken
quicksave recover app.py --json # report which snapshot it pulled from and the recovered files
quicksave stats                # store size and how much dedup is saving you
quicksave stats --markdown     # same numbers as a markdown table for a readme or tweet
quicksave list --json          # machine-readable output, same for save, status, stats, log, diff and recover --json
quicksave show 3 src/app.py    # print one file from a snapshot without touching disk
quicksave show src/app.py      # same, from the newest snapshot that still has it
quicksave export backup.tgz 3  # write a snapshot to a tar.gz, live tree untouched
quicksave import backup.tgz    # read a tar archive back into a new snapshot
quicksave export - -z | ssh host 'cd repo && quicksave import -'  # pipe a gzipped checkpoint to another machine
quicksave diff 2 3             # see what changed between two snapshots
quicksave diff 2 3 src/app.py # line-by-line diff of one file between snapshots
quicksave diff 3               # what the live tree changed since snapshot 3 (second side defaults to wt)
quicksave diff 3 wt            # same, spelled out
quicksave diff 3 wt src/app.py # line-by-line diff of one file against the tree
quicksave diff 2 3 --stat      # just the summary line, skip the file list
quicksave diff 2 3 --json      # the changed-file lists as json, add a path for the unified diff
quicksave pin 4                # protect a snapshot, gc --keep won't rotate it away
quicksave unpin 4              # let gc --keep rotate it again
quicksave gc --keep 10         # drop old snapshots and blobs nothing points at, reports space freed
quicksave gc --older-than 7d   # drop snapshots older than a duration (7d, 12h, 30m)
quicksave gc --keep 10 --keep-named  # rotate, but spare named snapshots like pinned ones
quicksave gc 4 pre-deploy      # drop specific snapshots by number, id or name
quicksave gc --keep 10 --json  # report what gc removed as json for a script or hook
quicksave drop 4 7 pre-deploy  # drop one or more snapshots by ref and reclaim their blobs
quicksave verify               # check the store for corrupt or missing blobs
quicksave verify --repair      # drop snapshots that point at corrupt or missing blobs
quicksave save -q -m wip       # -q/--quiet: silence output for scripts and hooks
```

`-q`/`--quiet` works before or after the command and drops the normal output, keeping
only errors (on stderr) and `--json`, so quicksave is quiet when it runs from a script.

Typical flow with an agent:

```
quicksave save -m "pre-agent"
# let the agent run wild
quicksave list                 # see what you can fall back to
quicksave restore 0            # roll back if it broke something
```

`restore` brings back every file that was in the snapshot, so deleting a directory and restoring
gets it back. Pass one or more paths to only restore those (a directory name matches everything
under it). By default it is additive: it won't touch new files you created after the snapshot. Add
`--clean` for an exact rewind that also deletes files the snapshot didn't have, so the tree matches
the checkpoint byte for byte. Not sure what a restore will do? Add `--dry-run` to see the files it
would write (new vs overwritten) and, with `--clean`, the ones it would delete, without touching disk.

Restore snapshots the current tree first, so a restore you didn't mean is itself reversible: pick the
wrong checkpoint and `quicksave undo` puts you back to how the tree looked before. Add `--clean` to
also drop files the restore brought in. The backup is skipped when nothing changed since the last
snapshot, and `--no-backup` turns it off.

Lost a file and not sure which checkpoint still has it? `quicksave find app.py` lists every snapshot
holding a file whose path matches, newest first, with the size of each match and a ready-made restore
line. The query matches an exact path, a directory prefix, or just part of a name, so a bare basename
finds it wherever it lived. A query with glob chars matches that way instead, so `quicksave find '*.py'`
or `quicksave find 'src/**/test_*.py'` work too. `--limit N` keeps only the N newest matches when you
just want the last few.

When you don't care which checkpoint, `quicksave recover app.py` skips that step: it finds the newest
snapshot that still holds the file and restores it in one shot, even if it was deleted several commands
ago and isn't in the latest snapshot. It backs the tree up first (so `undo` reverts it), or `--no-backup`
to skip that. Add `--dry-run` to see which files it would bring back, and from which snapshot, before
it touches anything, or `--into DIR` to write the matches aside into another directory and leave the
live tree alone. Pass several paths - `quicksave recover app.py utils.py config.json` - and each one
resolves to its own newest snapshot while a single pre-restore backup covers the whole batch, so one
`undo` rewinds them all. If the newest copy turns out to be the broken one, `find` lists the candidates
and `recover app.py --from 3` pulls from the snapshot you pick instead of scanning for the newest match.

`save -n <name>` tags a snapshot so you can roll back to it without hunting for its number or id:
`quicksave restore pre-deploy`. Anywhere a command takes a snapshot ref (`restore`, `status`, `show`,
`diff`) the name works too. Names can't be all digits so they never clash with the list numbers, and
if you reuse a name the most recent one wins. The hook saves nameless snapshots as it fires, so when
one turns out to be the good state you can label it afterwards with `quicksave name 4 good-build`,
or pass an empty name to clear one.

You can also point at a snapshot by how recent it is. `latest` is the newest one and `latest~1` (or
just `~1`) is the one before it, counting back, so `quicksave diff ~1 wt` shows what changed since the
previous checkpoint without looking up an id.

`status` compares the working tree to a snapshot (the latest one unless you name another) and shows
what was added, removed or modified since then, so you can see what a checkpoint would pull you back
to before you run it. `diff` does the same between two snapshots, and the ref `wt` stands in for the
live working tree on either side, so `quicksave diff 3 wt` (add a path for a line-by-line view) tells
you exactly what an agent touched since your last checkpoint before you decide to restore.

`show` writes one file's contents from a snapshot straight to stdout, so you can grab a single old
version without overwriting what's on disk: `quicksave show 3 config.py > config.old.py` or pipe it
into `diff`. Drop the snapshot ref and it prints the file from the newest snapshot that still has it,
so `quicksave show config.py` works even after the file was deleted - the read-only peek to `recover`.

`export` packs a whole snapshot into a tar archive without touching the live tree, so you can stash a
known-good checkpoint or move it to another machine: `quicksave export backup.tar.gz pre-deploy`.
A `.gz`/`.tgz` name gives a gzipped archive, anything else a plain tar; pass paths to export only part
of the snapshot. With no ref it exports the latest. Use `-` as the destination to stream a tar to
stdout instead of a file; add `-z`/`--gzip` to compress it, which is the only way to gzip a stream since
there's no filename to infer from: `quicksave export - -z | ssh host 'cd repo && quicksave import -'`.

`import` is the other direction: it reads a tar archive (one made by `export`, or any plain tarball) back
into a fresh snapshot without touching the live tree. Restore it later to materialize the files:
`quicksave import backup.tar.gz --name recovered`. Archives with absolute or `..` paths are rejected.
Use `-` as the source to read from stdin, so you can pipe a checkpoint straight to another machine:
`quicksave export - | ssh host 'cd repo && quicksave import -'`.

## Auto-save before an agent's risky commands

Claude Code can fire a hook before it runs a tool. Point its `PreToolUse` Bash hook at
`quicksave hook` and it will checkpoint the tree right before the agent runs anything destructive
(`rm`, `mv`, `git reset`, `git rm`, `git stash`, `rsync --delete`, `sed -i`, an overwriting `>`, and
friends). Safe commands like `ls` or
`git status` are ignored, and it stays quiet if the directory isn't a quicksave project, so it never
blocks the agent.

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "quicksave hook" }]
      }
    ]
  }
}
```

Or let quicksave write that config for you:

```
quicksave hook install            # Claude Code (.claude/settings.json)
quicksave hook install --tool codex   # Codex (.codex/hooks.json)
```

It merges into an existing config and won't add the hook twice. Codex uses the same hook shape and
also passes `tool_input.command` for Bash, so the one `quicksave hook` handler works for both. Any
other runner with a pre-command hook can call `quicksave hook` the same way as long as it sends the
command on stdin as `{"tool_input": {"command": "..."}}`.

The hook reads the tool payload on stdin, so each save lands as `pre: <command>` in `quicksave
list`. Run `quicksave init` once in the project first. If the tree hasn't changed since the last
snapshot the save is skipped, so firing the hook on every command doesn't pile up identical
checkpoints (use `quicksave save --force` if you want one anyway).

Over a long session the hook can pile up a lot of snapshots. Set `QUICKSAVE_KEEP` to cap the
history to the N most recent, and the hook drops older ones (and their now-unreferenced blobs)
after each save:

```
export QUICKSAVE_KEEP=50
```

If a checkpoint matters, `quicksave pin <ref>` keeps it out of that rotation so a busy hook can't
reap the one good state you wanted to keep. `quicksave unpin <ref>` lets it rotate again, and an
explicit `quicksave gc <ref>` still drops it when you mean it.

## Shell completion

There are a lot of subcommands now, so tab completion helps. `quicksave completion bash|zsh|fish|powershell`
prints a script with no extra dependencies. Source it from your shell rc:

```
# bash, in ~/.bashrc
eval "$(quicksave completion bash)"

# zsh, in ~/.zshrc (after compinit)
eval "$(quicksave completion zsh)"

# fish, in ~/.config/fish/config.fish
quicksave completion fish | source

# powershell, in $PROFILE
quicksave completion powershell | Out-String | Invoke-Expression
```

It completes subcommands at the first word and falls back to file completion after that. The
command list is read from the parser, so it stays in sync as commands are added.

Set `NO_COLOR` to any value and quicksave prints plain text without styling, following the
[NO_COLOR](https://no-color.org) convention.

## How it works

- Files are hashed with SHA-256 and stored once under `.quicksave/objects/` (identical content is
  deduplicated).
- Each `save` writes a manifest in `.quicksave/snapshots/` mapping every path to its hash, size and
  mode.
- Restore just copies the blobs back to their paths.

Caches and vendored deps are skipped by default: `.git`, `node_modules`, `__pycache__`, `venv`,
`.venv`, `dist`, `build` and friends. To skip more, drop a `.quicksaveignore` with gitignore-style
globs (`*.log`, `logs/`, `tmp/`) in the project root; an existing `.gitignore` is read too. Note
`.env` is intentionally not ignored by default, the whole point is to keep it safe.

## Why not just git?

git is great, but for this job it gets in the way:

- It only protects what you `git add` and commit. Untracked files, `.env`, and build output are on
  their own.
- A `git stash` / `git checkout` is itself a destructive operation an agent can run.
- It mixes "I want to publish this" history with "save me from the last 30 seconds" checkpoints.

quicksave is a separate safety net that snapshots everything in one command and never rewrites your
git history.

## Tests

```
pip install -e .
pip install pytest
pytest
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## License

MIT. Made by [qorexdevs](https://github.com/qorexdevs).
