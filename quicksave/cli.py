import argparse
import json
import sys
from datetime import datetime

from rich.console import Console
from rich.table import Table

from . import __version__, store

console = Console()
err = Console(stderr=True)


def _human_size(n):
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def _root_or_die():
    root = store.find_root()
    if root is None:
        err.print("[red]not a quicksave project[/], run 'quicksave init' first")
        raise SystemExit(1)
    return root


def cmd_init(args):
    root, created = store.init(args.path)
    if created:
        console.print(f"[green]initialized quicksave[/] in {root}")
    else:
        console.print(f"[yellow]already a quicksave project[/]: {root}")


def cmd_save(args):
    root = _root_or_die()
    snap_id, n, created = store.save(root, message=args.message or "", force=args.force,
                                     name=args.name or "")
    if not created:
        if args.name:
            console.print(f"[dim]nothing changed, named {snap_id}[/] [magenta]{args.name}[/]")
        else:
            console.print(f"[dim]nothing changed since {snap_id}, skipped[/]")
        return
    name = f" [magenta]{args.name}[/]" if args.name else ""
    msg = f" [dim]{args.message}[/]" if args.message else ""
    console.print(f"saved [cyan]{snap_id}[/]{name} [dim]({n} files)[/]{msg}")


def cmd_list(args):
    root = _root_or_die()
    snaps = store.list_snapshots(root)
    if args.json:
        print(json.dumps(snaps))
        return
    if not snaps:
        console.print("[dim]no snapshots yet, run 'quicksave save'[/]")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("id", style="cyan")
    table.add_column("name", style="magenta")
    table.add_column("when")
    table.add_column("files", justify="right")
    table.add_column("size", justify="right")
    table.add_column("message")
    for s in snaps:
        when = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M") if s["created_at"] else "-"
        table.add_row(str(s["seq"]), s["id"], s.get("name") or "[dim]-[/]", when,
                      str(s["count"]), _human_size(s.get("size", 0)), s["message"] or "[dim]-[/]")
    console.print(table)
    console.print(f"[dim]{len(snaps)} snapshots, {_human_size(store.store_size(root))} on disk[/]")


def cmd_restore(args):
    root = _root_or_die()
    if args.dry_run:
        cmd_restore_preview(args, root)
        return
    # a restore overwrites the live tree, so snapshot it first - that way a wrong
    # restore is itself reversible. resolve the target before the backup so it
    # doesn't become the new "latest" and shadow a bare 'restore' ref.
    target = store.resolve_id(root, args.ref)
    if not args.no_backup:
        bid, _, made = store.save(root, message=f"before restore of {args.ref or 'latest'}")
        if made:
            console.print(f"[dim]backed up current tree as {bid}[/]")
    n, removed, manifest = store.restore(root, target, args.paths, clean=args.clean)
    ref = args.ref or "latest"
    when = manifest.get("message") or ref
    scope = f" [dim]({', '.join(args.paths)})[/]" if args.paths else ""
    extra = f" [red](removed {removed})[/]" if removed else ""
    console.print(f"restored [cyan]{n}[/] files from [cyan]{ref}[/] [dim]{when}[/]{scope}{extra}")


def cmd_restore_preview(args, root):
    p = store.restore_plan(root, args.ref, args.paths, clean=args.clean)
    ref = args.ref or "latest"
    total = len(p["created"]) + len(p["overwritten"])
    if not total and not p["removed"] and not p["missing"]:
        console.print(f"[dim]nothing to restore from {ref}[/]")
        return
    for path in p["created"]:
        console.print(f"[green]+ {path}[/]")
    for path in p["overwritten"]:
        console.print(f"[yellow]~ {path}[/]")
    for path in p["removed"]:
        console.print(f"[red]- {path}[/]")
    for path in p["missing"]:
        console.print(f"[red]! {path} (blob missing)[/]")
    summary = f"would write {total} ({len(p['created'])} new, {len(p['overwritten'])} overwritten)"
    if p["removed"]:
        summary += f", remove {len(p['removed'])}"
    console.print(f"[dim]{summary} - dry run, nothing touched[/]")


def cmd_undo(args):
    root = _root_or_die()
    backup = store.last_restore_backup(root)
    if backup is None:
        err.print("[yellow]nothing to undo[/], no restore backup found")
        raise SystemExit(1)
    # back up the current tree first, so undo is itself reversible with a restore
    if not args.no_backup:
        bid, _, made = store.save(root, message="before undo")
        if made:
            console.print(f"[dim]backed up current tree as {bid}[/]")
    n, removed, _ = store.restore(root, backup, clean=args.clean)
    extra = f" [red](removed {removed})[/]" if removed else ""
    console.print(f"undid last restore, [cyan]{n}[/] files back to [cyan]{backup}[/]{extra}")


def cmd_status(args):
    root = _root_or_die()
    s = store.status(root, args.ref)
    if args.json:
        print(json.dumps(s))
        return
    label = f"#{s['seq']} {s['id']}"
    if not (s["added"] or s["removed"] or s["modified"]):
        console.print(f"[green]clean[/] [dim]working tree matches snapshot {label}[/]")
        return
    console.print(f"[dim]changes since snapshot {label}:[/]")
    for path in s["added"]:
        console.print(f"[green]+ {path}[/]")
    for path in s["removed"]:
        console.print(f"[red]- {path}[/]")
    for path in s["modified"]:
        console.print(f"[yellow]~ {path}[/]")


def cmd_diff(args):
    root = _root_or_die()
    d = store.diff(root, args.a, args.b)
    if not any(d.values()):
        console.print(f"[dim]no changes between {args.a} and {args.b}[/]")
        return
    for path in d["added"]:
        console.print(f"[green]+ {path}[/]")
    for path in d["removed"]:
        console.print(f"[red]- {path}[/]")
    for path in d["modified"]:
        console.print(f"[yellow]~ {path}[/]")
    console.print(
        f"[dim]{len(d['added'])} added, {len(d['removed'])} removed, "
        f"{len(d['modified'])} modified[/]"
    )


def cmd_show(args):
    root = _root_or_die()
    data = store.show(root, args.ref, args.path)
    with open(1, "wb", closefd=False) as out:
        out.write(data) 

def cmd_log(args):
    root = _root_or_die()

    snap_file = store._find_snapshot(store.store_path(root), args.ref)
    if snap_file is None:
        raise store.QuicksaveError(f"snapshot '{args.ref}' not found")

    manifest = json.loads(snap_file.read_text())
    files = manifest.get("files", {})

    snap_id = snap_file.stem.partition("-")[2]

    when = "-"
    if manifest.get("created_at"):
        when = datetime.fromtimestamp(
            manifest["created_at"]
        ).strftime("%Y-%m-%d %H:%M:%S")

    console.print(f"Snapshot: {snap_id}")
    console.print(f"Name: {manifest.get('name') or '-'}")
    console.print(f"Message: {manifest.get('message') or '-'}")
    console.print(f"Time: {when}")
    console.print(f"Files: {len(files)}")

    console.print("\nFile List:")
    for path, meta in sorted(files.items()):
        console.print(f"{path} ({meta.get('size', 0)} bytes)")


def cmd_gc(args):
    root = _root_or_die()
    r = store.gc(root, keep=args.keep, refs=args.refs, dry_run=args.dry_run)
    tag = " [dim](dry run)[/]" if r["dry_run"] else ""
    if r["pruned"]:
        for name in r["pruned"]:
            console.print(f"[red]- snapshot {name}[/]")
    if not r["pruned"] and not r["blobs"]:
        console.print(f"[green]nothing to collect[/]{tag}")
        return
    console.print(
        f"removed [cyan]{len(r['pruned'])}[/] snapshots, "
        f"[cyan]{r['blobs']}[/] unreferenced blobs{tag}"
    )


def cmd_hook(args):
    # reads a Claude Code PreToolUse payload on stdin and snapshots before a
    # risky bash command. stays quiet and exits 0 so it never blocks the agent.
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return
    cmd = (payload.get("tool_input") or {}).get("command", "")
    if not cmd or not store.looks_risky(cmd):
        return
    root = store.find_root()
    if root is None:
        return
    short = cmd.strip().splitlines()[0][:60]
    snap_id, n, created = store.save(root, message=f"pre: {short}")
    if created:
        print(f"quicksave {snap_id} ({n} files) before: {short}", file=sys.stderr)


def cmd_hook_install(args):
    root = _root_or_die()
    path, changed = store.install_hook(root, args.tool)
    rel = path.relative_to(root).as_posix()
    if changed:
        console.print(f"[green]wired quicksave hook[/] into {rel} ({args.tool})")
    else:
        console.print(f"[yellow]already wired[/] in {rel}")


def build_parser():
    # --quiet lives on a shared parent so it works both before and after the
    # subcommand; SUPPRESS keeps an unset copy from clobbering one that was set.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS,
                        help="silence normal output, only errors and --json still print")

    p = argparse.ArgumentParser(prog="quicksave", description="F5 for your filesystem",
                                parents=[common])
    p.add_argument("--version", action="version", version=f"quicksave {__version__}")
    sub = p.add_subparsers(dest="cmd")

    pi = sub.add_parser("init", help="start tracking the current directory", parents=[common])
    pi.add_argument("path", nargs="?", default=None)
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("save", help="snapshot the working tree", parents=[common])
    ps.add_argument("-m", "--message", default="")
    ps.add_argument("-n", "--name", default="",
                    help="label the snapshot so you can restore it by name later")
    ps.add_argument("-f", "--force", action="store_true",
                    help="snapshot even if nothing changed since the last one")
    ps.set_defaults(func=cmd_save)

    pl = sub.add_parser("list", help="list snapshots", parents=[common])
    pl.add_argument("--json", action="store_true", help="print snapshots as json")
    pl.set_defaults(func=cmd_list)

    pr = sub.add_parser("restore", help="restore files from a snapshot (default latest)", parents=[common])
    pr.add_argument("ref", nargs="?", default=None,
                    help="snapshot id, number or name from 'quicksave list', defaults to latest")
    pr.add_argument("paths", nargs="*", help="only restore these files or directories")
    pr.add_argument("--clean", action="store_true",
                    help="delete files not in the snapshot (exact rewind)")
    pr.add_argument("--dry-run", action="store_true",
                    help="show what restore would change without writing anything")
    pr.add_argument("--no-backup", action="store_true",
                    help="don't snapshot the current tree before restoring")
    pr.set_defaults(func=cmd_restore)

    pu = sub.add_parser("undo", help="revert the last restore, back to the pre-restore tree", parents=[common])
    pu.add_argument("--clean", action="store_true",
                    help="also delete files the restore added (exact rewind)")
    pu.add_argument("--no-backup", action="store_true",
                    help="don't snapshot the current tree before undoing")
    pu.set_defaults(func=cmd_undo)

    pt = sub.add_parser("status", help="show changes since a snapshot (default latest)", parents=[common])
    pt.add_argument("ref", nargs="?", default=None, help="snapshot id or number, defaults to latest")
    pt.add_argument("--json", action="store_true", help="print the diff as json")
    pt.set_defaults(func=cmd_status)

    pd = sub.add_parser("diff", help="show what changed between two snapshots", parents=[common])
    pd.add_argument("a", help="snapshot id or number")
    pd.add_argument("b", help="snapshot id or number")
    pd.set_defaults(func=cmd_diff)

    ph = sub.add_parser("show", help="print a file's contents from a snapshot to stdout", parents=[common])
    ph.add_argument("ref", help="snapshot id or number")
    ph.add_argument("path", help="file to print")
    ph.set_defaults(func=cmd_show) 

    plog = sub.add_parser(
    "log",
    help="show details for one snapshot",
    parents=[common]
    )
    plog.add_argument(
    "ref",
    help="snapshot id, number or name"
    )
    plog.set_defaults(func=cmd_log)

    pg = sub.add_parser("gc", help="drop old snapshots and unreferenced blobs", parents=[common])
    pg.add_argument("refs", nargs="*",
                    help="drop these specific snapshots too (id, number or name)")
    pg.add_argument("--keep", type=int, default=None,
                    help="keep only the N most recent snapshots")
    pg.add_argument("--dry-run", action="store_true",
                    help="show what would be removed without deleting")
    pg.set_defaults(func=cmd_gc)

    phook = sub.add_parser("hook", help="PreToolUse hook: auto-save before a risky bash command", parents=[common])
    phook.set_defaults(func=cmd_hook)
    hsub = phook.add_subparsers(dest="hook_action")
    hin = hsub.add_parser("install", help="wire the hook into an agent runner's config", parents=[common])
    hin.add_argument("--tool", choices=sorted(store.HOOK_TARGETS), default="claude",
                     help="which runner to wire up")
    hin.set_defaults(func=cmd_hook_install)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "quiet", False):
        console.quiet = True
    if not getattr(args, "func", None):
        parser.print_help()
        return
    try:
        args.func(args)
    except store.QuicksaveError as e:
        err.print(f"[red]error:[/] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
