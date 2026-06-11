# quicksave

[![ci](https://github.com/qorexdevs/quicksave/actions/workflows/ci.yml/badge.svg)](https://github.com/qorexdevs/quicksave/actions/workflows/ci.yml)

F5 for your filesystem. Checkpoint before every risky command, restore even after `rm -rf`.

Coding agents run shell commands you didn't read. Most undo tools only track git or the editor's
own session, so an agent's `rm`, `mv`, or a stray script can wipe files that nothing was watching.
quicksave snapshots the whole working tree into a local content-addressed store, so you can roll
back to any checkpoint - including files that were never committed.

## Install

```
pip install -e .
```

Needs Python 3.10+.

## Usage

```
quicksave init                 # start tracking this directory
quicksave save -m "before refactor"
quicksave save -n pre-deploy   # tag the snapshot with a name
quicksave list                 # snapshots with file count, size and total store size on disk
quicksave restore              # roll back to the latest snapshot
quicksave restore 3            # restore by number from the list
quicksave restore a1b2c3       # or by id
quicksave restore pre-deploy   # or by the name you gave it
quicksave restore 3 src/app.py # only pull back one file or directory
quicksave restore 3 --clean    # exact rewind: also delete files added after the snapshot
quicksave restore 3 --dry-run  # preview what restore would write or delete, no changes
quicksave restore 3 --no-backup # skip the safety snapshot of the current tree
quicksave undo                 # revert the last restore, back to the pre-restore tree
quicksave name 3 good-build    # tag an existing snapshot after the fact (empty name clears it)
quicksave status               # what changed in the tree since the last snapshot
quicksave list --json          # machine-readable output, same for status --json
quicksave show 3 src/app.py    # print one file from a snapshot without touching disk
quicksave export backup.tgz 3  # write a snapshot to a tar.gz, live tree untouched
quicksave import backup.tgz    # read a tar archive back into a new snapshot
quicksave export - -z | ssh host 'cd repo && quicksave import -'  # pipe a gzipped checkpoint to another machine
quicksave diff 2 3             # see what changed between two snapshots
quicksave diff 2 3 src/app.py # line-by-line diff of one file between snapshots
quicksave diff 3 wt            # what the live tree changed since snapshot 3
quicksave diff 3 wt src/app.py # line-by-line diff of one file against the tree
quicksave gc --keep 10         # drop old snapshots and blobs nothing points at
quicksave gc 4 pre-deploy      # drop specific snapshots by number, id or name
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

`save -n <name>` tags a snapshot so you can roll back to it without hunting for its number or id:
`quicksave restore pre-deploy`. Anywhere a command takes a snapshot ref (`restore`, `status`, `show`,
`diff`) the name works too. Names can't be all digits so they never clash with the list numbers, and
if you reuse a name the most recent one wins. The hook saves nameless snapshots as it fires, so when
one turns out to be the good state you can label it afterwards with `quicksave name 4 good-build`,
or pass an empty name to clear one.

`status` compares the working tree to a snapshot (the latest one unless you name another) and shows
what was added, removed or modified since then, so you can see what a checkpoint would pull you back
to before you run it. `diff` does the same between two snapshots, and the ref `wt` stands in for the
live working tree on either side, so `quicksave diff 3 wt` (add a path for a line-by-line view) tells
you exactly what an agent touched since your last checkpoint before you decide to restore.

`show` writes one file's contents from a snapshot straight to stdout, so you can grab a single old
version without overwriting what's on disk: `quicksave show 3 config.py > config.old.py` or pipe it
into `diff`.

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
(`rm`, `mv`, `git reset`, `sed -i`, an overwriting `>`, and friends). Safe commands like `ls` or
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

## License

MIT. Made by [qorexdevs](https://github.com/qorexdevs).
