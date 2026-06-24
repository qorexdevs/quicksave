import argparse
import json
import os
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


def _relative_time(ts, now=None):
    if not ts:
        return "-"
    secs = (now or datetime.now().timestamp()) - ts
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


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
    if args.message == "-":
        args.message = sys.stdin.read().rstrip("\n")
    if getattr(args, "dry_run", False):
        p = store.save_preview(root)
        if getattr(args, "json", False):
            print(json.dumps(p))
            return
        if p["first"]:
            console.print(f"[dim]first snapshot, would capture {p['files']} files "
                          f"({_human_size(p['size'])})[/]")
            return
        if not p["would_change"]:
            console.print("[dim]nothing changed since the last snapshot, save would be skipped[/]")
            return
        for path in p["added"]:
            console.print(f"[green]+ {path}[/]")
        for path in p["removed"]:
            console.print(f"[red]- {path}[/]")
        for path in p["modified"]:
            console.print(f"[yellow]~ {path}[/]")
        console.print(f"[dim]would capture {p['files']} files ({_human_size(p['size'])}), "
                      "nothing written[/]")
        return
    snap_id, n, created = store.save(root, message=args.message or "", force=args.force,
                                     name=args.name or "")
    if getattr(args, "json", False):
        print(json.dumps({"id": snap_id, "files": n, "created": created,
                          "name": args.name or None, "message": args.message or None}))
        return
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
    pinned_only = getattr(args, "pinned", False)
    if pinned_only:
        snaps = [s for s in snaps if s.get("pinned")]
    since = getattr(args, "since", None)
    if since:
        cutoff = datetime.now().timestamp() - store.parse_duration(since)
        snaps = [s for s in snaps if s["created_at"] and s["created_at"] >= cutoff]
    before = getattr(args, "before", None)
    if before:
        cutoff = datetime.now().timestamp() - store.parse_duration(before)
        snaps = [s for s in snaps if s["created_at"] and s["created_at"] <= cutoff]
    grep = getattr(args, "grep", None)
    if grep:
        needle = grep.lower()
        snaps = [s for s in snaps
                 if needle in (s["message"] or "").lower() or needle in (s.get("name") or "").lower()]
    if getattr(args, "count", False):
        print(len(snaps))
        return
    if args.json:
        print(json.dumps(snaps))
        return
    if not snaps:
        if pinned_only:
            console.print("[dim]no pinned snapshots, pin one with 'quicksave pin <ref>'[/]")
        elif since:
            console.print(f"[dim]no snapshots in the last {since}[/]")
        elif before:
            console.print(f"[dim]no snapshots older than {before}[/]")
        elif grep:
            console.print(f"[dim]no snapshots match '{grep}'[/]")
        else:
            console.print("[dim]no snapshots yet, run 'quicksave save'[/]")
        return
    total_snaps = len(snaps)
    is_capped = False
    if args.limit and args.limit < total_snaps:
        snaps = snaps[-args.limit:]
        is_capped = True
    if getattr(args, "reverse", False):
        snaps = snaps[::-1]
    table = Table(box=None, pad_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("id", style="cyan")
    table.add_column("name", style="magenta")
    table.add_column("when")
    table.add_column("files", justify="right")
    table.add_column("size", justify="right")
    table.add_column("message")
    absolute = getattr(args, "absolute", False)
    now = datetime.now().timestamp()
    for s in snaps:
        if absolute:
            when = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M") if s["created_at"] else "-"
        else:
            when = _relative_time(s["created_at"], now)
        sid = f"{s['id']} [yellow]*[/]" if s.get("pinned") else s["id"]
        table.add_row(str(s["seq"]), sid, s.get("name") or "[dim]-[/]", when,
                      str(s["count"]), _human_size(s.get("size", 0)), s["message"] or "[dim]-[/]")
    console.print(table)
    if is_capped:
        console.print(f"[dim]showing {len(snaps)} of {total_snaps} snapshots, {_human_size(store.store_size(root))} on disk[/]")
    else:
        console.print(f"[dim]{len(snaps)} snapshots, {_human_size(store.store_size(root))} on disk[/]")


def cmd_names(args):
    root = _root_or_die()
    named = [s for s in store.list_snapshots(root) if s.get("name")]
    grep = getattr(args, "grep", None)
    if grep:
        needle = grep.lower()
        named = [s for s in named if needle in s["name"].lower()]
    if getattr(args, "count", False):
        print(len(named))
        return
    if args.json:
        # list_snapshots is oldest first; show newest names first unless --reverse
        ordered = named if getattr(args, "reverse", False) else list(reversed(named))
        print(json.dumps([{"id": s["id"], "name": s["name"]} for s in ordered]))
        return
    if not named:
        if grep:
            console.print(f"[dim]no named snapshots match '{grep}'[/]")
        else:
            console.print("[dim]no named snapshots yet, name one with 'quicksave name <ref> <name>'[/]")
        return
    total = len(named)
    if getattr(args, "limit", None) and args.limit < total:
        named = named[-args.limit:]  # keep the n most recent, named is oldest first
    if not getattr(args, "reverse", False):
        named.reverse()  # show newest names first
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column("id", style="cyan")
    table.add_column("name", style="magenta")
    for s in named:
        table.add_row(s["id"], s["name"])
    console.print(table)
    if len(named) < total:
        console.print(f"[dim]showing {len(named)} of {total} named snapshots[/]")


def cmd_stats(args):
    root = _root_or_die()
    s = store.stats(root, top=args.top)
    if args.json:
        print(json.dumps(s))
        return
    if not s["snapshots"]:
        console.print("[dim]no snapshots yet, run 'quicksave save'[/]")
        return
    saved = s["saved_bytes"]
    ratio = s["ratio"]
    if args.markdown:
        # plain print so it survives a copy-paste into a readme or a tweet
        print("| snapshots | blobs | on disk | dedup |")
        print("| --- | --- | --- | --- |")
        print(f"| {s['snapshots']} | {s['blobs']} | {_human_size(s['disk_bytes'])} | {ratio:.1f}x |")
        if s["top_snapshots"]:
            print()
            print("| id | name | unique |")
            print("| --- | --- | --- |")
            for row in s["top_snapshots"]:
                name = row["name"] or "-"
                print(f"| {row['id']} | {name} | {_human_size(row['unique_bytes'])} |")
        return
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column(justify="right")
    table.add_row("snapshots", str(s["snapshots"]))
    table.add_row("blobs", str(s["blobs"]))
    table.add_row("logical size", _human_size(s["logical_bytes"]))
    table.add_row("on disk", _human_size(s["disk_bytes"]))
    table.add_row("dedup", f"{ratio:.1f}x [dim]({_human_size(saved)} saved)[/]")
    if s["first"]:
        first = datetime.fromtimestamp(s["first"]).strftime("%Y-%m-%d %H:%M")
        last = datetime.fromtimestamp(s["last"]).strftime("%Y-%m-%d %H:%M")
        table.add_row("span", first if first == last else f"{first} -> {last}")
    console.print(table)
    if s["top_snapshots"]:
        console.print()
        top = Table(box=None, pad_edge=False)
        top.add_column("id", style="cyan")
        top.add_column("name", style="magenta")
        top.add_column("unique", justify="right")
        for row in s["top_snapshots"]:
            top.add_row(row["id"], row["name"] or "[dim]-[/]", _human_size(row["unique_bytes"]))
        console.print(top)


def _change_points(snaps):
    # snaps is newest-first. keep only the ones where the matched content differs
    # from the next-older neighbour, so you see when the file actually changed
    # across checkpoints instead of every snapshot that happens to hold it. the
    # oldest match is always kept since it's where the content first shows up.
    out = []
    prev = None
    for s in reversed(snaps):
        sig = frozenset((h["path"], h["sha256"]) for h in s["files"])
        if sig != prev:
            out.append(s)
        prev = sig
    return out[::-1]


def cmd_find(args):
    root = _root_or_die()
    snaps = store.find_file(root, args.path, getattr(args, "ignore_case", False))
    since = getattr(args, "since", None)
    if since:
        cutoff = datetime.now().timestamp() - store.parse_duration(since)
        snaps = [s for s in snaps if s["created_at"] and s["created_at"] >= cutoff]
    before = getattr(args, "before", None)
    if before:
        cutoff = datetime.now().timestamp() - store.parse_duration(before)
        snaps = [s for s in snaps if s["created_at"] and s["created_at"] <= cutoff]
    if getattr(args, "changes", False):
        snaps = _change_points(snaps)
    if args.limit and args.limit < len(snaps):
        snaps = snaps[:args.limit]

    if getattr(args, "reverse", False):
        snaps = snaps[::-1]

    if getattr(args, "count", False):
        print(len(snaps))
        return

    if getattr(args, "diff", False):
        import difflib
        # collect every distinct path matched across all change-point snapshots
        all_paths = {h["path"] for s in snaps for h in s["files"]}
        if len(all_paths) != 1:
            err.print(
                f"[red]--diff requires the query to match exactly one file path[/] "
                f"(matched {len(all_paths)}"
                + (": " + ", ".join(sorted(all_paths)) if all_paths else "") + ")"
            )
            raise SystemExit(1)
        path = next(iter(all_paths))
        # snaps is newest-first; walk oldest-to-newest for the diff sequence
        ordered = list(reversed(snaps))
        prev_lines: list = []
        prev_ts = ""
        now = datetime.now().timestamp()
        for s in ordered:
            lines = _file_text(root, s["id"], path) or []
            ref = s["id"]
            ts = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M") if s["created_at"] else ""
            when = _relative_time(s["created_at"], now)
            label = f"#{s['seq']} [cyan]{ref}[/]"
            if s.get("name"):
                label += f" [magenta]{s['name']}[/]"
            console.print(f"{label} [dim]{when}[/]")
            diff_lines = list(difflib.unified_diff(
                prev_lines, lines,
                fromfile=f"{path}  {prev_ts}",
                tofile=f"{path}  {ts}",
            ))
            if diff_lines:
                for line in diff_lines:
                    line = line.rstrip("\n")
                    if line.startswith("+"):
                        console.print(f"[green]{line}[/]")
                    elif line.startswith("-"):
                        console.print(f"[red]{line}[/]")
                    elif line.startswith("@@"):
                        console.print(f"[cyan]{line}[/]")
                    else:
                        console.print(line)
            else:
                console.print("[dim](no textual change)[/]")
            prev_lines = lines
            prev_ts = ts
        return

    if args.json:
        print(json.dumps(snaps))
        return
    label_q = "', '".join(args.path)
    if not snaps:
        console.print(f"[dim]no snapshot holds a file matching '{label_q}'[/]")
        return
    now = datetime.now().timestamp()
    for s in snaps:
        when = _relative_time(s["created_at"], now)
        label = f"#{s['seq']} [cyan]{s['id']}[/]"
        if s.get("name"):
            label += f" [magenta]{s['name']}[/]"
        console.print(f"{label} [dim]{when}[/]")
        for h in s["files"]:
            console.print(f"  {h['path']} [dim]{_human_size(h['size'])}[/]")
    newest = snaps[0]
    if len(args.path) == 1:
        console.print(f"[dim]restore with 'quicksave restore {newest['id']} {args.path[0]}'[/]")
    else:
        console.print(f"[dim]restore these with 'quicksave recover {' '.join(args.path)}'[/]")


def cmd_recover(args):
    # the panic case: a file got deleted some commands ago and you don't know
    # which snapshot still has it. find the newest one that does and restore it
    # in one shot. takes several paths at once - when an agent wipes a handful of
    # files in one command, each resolves to its own newest snapshot and one
    # pre-restore backup covers the whole batch. --from pins every path to one
    # snapshot instead, for when the newest copies are themselves broken.
    root = _root_or_die()
    as_json = getattr(args, "json", False)
    from_ref = getattr(args, "from_ref", None)
    into = getattr(args, "into", None)
    queries = args.path

    resolved = []
    for q in queries:
        if from_ref is not None:
            m = store.find_file_at(root, from_ref, q)
        else:
            snaps = store.find_file(root, q)
            m = snaps[0] if snaps else None
        resolved.append((q, m))

    if all(m is None for _, m in resolved):
        if as_json:
            print(json.dumps({"paths": queries, "recovered": 0,
                              "results": [{"path": q, "snapshot": None, "recovered": 0, "files": []}
                                          for q in queries]}))
            return
        where = f" in snapshot '{from_ref}'" if from_ref is not None else ""
        names = "', '".join(queries)
        err.print(f"[red]no snapshot holds a file matching '{names}'{where}[/]")
        raise SystemExit(1)

    # one pre-restore backup for the whole batch, before any write. skip it for
    # --into (live tree untouched) and dry-run (nothing written). resolve above
    # happened first so the backup never becomes a recover target.
    backup = None
    if not into and not args.dry_run and not args.no_backup:
        bid, _, made = store.save(root, message=f"before restore of recover '{' '.join(queries)}'")
        if made:
            backup = bid
            if not as_json:
                console.print(f"[dim]backed up current tree as {bid}[/]")

    results = []
    for q, m in resolved:
        if m is None:
            results.append({"path": q, "snapshot": None, "recovered": 0, "files": []})
            if not as_json:
                err.print(f"[yellow]nothing matched '{q}', skipped[/]")
            continue
        paths = [h["path"] for h in m["files"]]
        snap = {"seq": m["seq"], "id": m["id"], "name": m.get("name") or "",
                "created_at": m["created_at"]}
        label = f"#{m['seq']} [cyan]{m['id']}[/]"
        when = _relative_time(m["created_at"])
        if into:
            n, _, _ = store.restore(root, m["id"], paths, dest=into)
            results.append({"path": q, "snapshot": snap, "recovered": n, "files": paths, "into": into})
            if not as_json:
                console.print(f"recovered [cyan]{n}[/] files matching '{q}' from {label} "
                              f"[dim]{when}[/] into [cyan]{into}[/]")
        elif args.dry_run:
            p = store.restore_plan(root, m["id"], paths)
            total = len(p["created"]) + len(p["overwritten"])
            results.append({"path": q, "snapshot": snap, "dry_run": True, "would_recover": total,
                            "created": p["created"], "overwritten": p["overwritten"],
                            "missing": p["missing"]})
            if not as_json:
                for path in p["created"]:
                    console.print(f"[green]+ {path}[/]")
                for path in p["overwritten"]:
                    console.print(f"[yellow]~ {path}[/]")
                for path in p["missing"]:
                    console.print(f"[red]! {path} (blob missing)[/]")
                console.print(f"[dim]would recover {total} matching '{q}' from {label} {when}"
                              f" - dry run, nothing touched[/]")
        else:
            n, _, _ = store.restore(root, m["id"], paths)
            results.append({"path": q, "snapshot": snap, "recovered": n, "files": paths})
            if not as_json:
                console.print(f"recovered [cyan]{n}[/] files matching '{q}' from {label} [dim]{when}[/]")

    if as_json:
        out = {"paths": queries, "results": results}
        if args.dry_run:
            out["would_recover"] = sum(r.get("would_recover", 0) for r in results)
        else:
            out["recovered"] = sum(r.get("recovered", 0) for r in results)
            if not into:
                out["backup"] = backup
        print(json.dumps(out))


def cmd_restore(args):
    root = _root_or_die()
    into = getattr(args, "into", None)
    as_json = getattr(args, "json", False)
    ref = args.ref or "latest"
    if into:
        # pulling a snapshot aside, the live tree is untouched so no backup and
        # no clean. dry-run previews against the tree, which is meaningless here.
        target = store.resolve_id(root, args.ref)
        n, _, _ = store.restore(root, target, args.paths, dest=into)
        if as_json:
            print(json.dumps({"ref": ref, "restored": n, "into": into, "paths": args.paths}))
            return
        scope = f" [dim]({', '.join(args.paths)})[/]" if args.paths else ""
        console.print(f"restored [cyan]{n}[/] files from [cyan]{ref}[/] into [cyan]{into}[/]{scope}")
        return
    if args.dry_run:
        cmd_restore_preview(args, root)
        return
    # a restore overwrites the live tree, so snapshot it first - that way a wrong
    # restore is itself reversible. resolve the target before the backup so it
    # doesn't become the new "latest" and shadow a bare 'restore' ref.
    target = store.resolve_id(root, args.ref)
    backup = None
    if not args.no_backup:
        bid, _, made = store.save(root, message=f"before restore of {args.ref or 'latest'}")
        if made:
            backup = bid
            if not as_json:
                console.print(f"[dim]backed up current tree as {bid}[/]")
    n, removed, manifest = store.restore(root, target, args.paths, clean=args.clean)
    if as_json:
        print(json.dumps({"ref": ref, "restored": n, "removed": removed,
                          "backup": backup, "paths": args.paths}))
        return
    when = manifest.get("message") or ref
    scope = f" [dim]({', '.join(args.paths)})[/]" if args.paths else ""
    extra = f" [red](removed {removed})[/]" if removed else ""
    console.print(f"restored [cyan]{n}[/] files from [cyan]{ref}[/] [dim]{when}[/]{scope}{extra}")


def cmd_restore_preview(args, root):
    p = store.restore_plan(root, args.ref, args.paths, clean=args.clean)
    ref = args.ref or "latest"
    total = len(p["created"]) + len(p["overwritten"])
    if getattr(args, "json", False):
        print(json.dumps({"ref": ref, "dry_run": True, "would_write": total,
                          "created": p["created"], "overwritten": p["overwritten"],
                          "removed": p["removed"], "missing": p["missing"]}))
        return
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


def cmd_check_ignore(args):
    root = _root_or_die()
    results = [store.check_ignore(root, p) for p in args.paths]
    if args.json:
        print(json.dumps(results))
    else:
        for r in results:
            if r["ignored"]:
                where = r["source"] if r["source"] == "built-in" else f"{r['source']}:{r['line']}"
                console.print(f"[red]ignored[/] {r['path']} [dim]({where}: {r['rule']})[/]")
            else:
                console.print(f"[green]kept[/]    {r['path']}")
    # like 'git check-ignore --quiet': non-zero unless every path is ignored
    if args.exit_code and not all(r["ignored"] for r in results):
        raise SystemExit(1)


def cmd_status(args):
    root = _root_or_die()
    s = store.status(root, args.ref)
    dirty = bool(s["added"] or s["removed"] or s["modified"])
    if args.json:
        print(json.dumps(s))
        if args.exit_code and dirty:
            raise SystemExit(1)
        return
    if args.short:
        if dirty:
            print(f"~{len(s['modified'])} +{len(s['added'])} -{len(s['removed'])}")
        else:
            print("clean")
        if args.exit_code and dirty:
            raise SystemExit(1)
        return
    if args.stat:
        if dirty:
            print(
                f"{len(s['added'])} added, {len(s['removed'])} removed, "
                f"{len(s['modified'])} modified"
            )
        else:
            print("clean")
        if args.exit_code and dirty:
            raise SystemExit(1)
        return
    if args.name_only:
        for path in s["added"]:
            print(path)
        for path in s["removed"]:
            print(path)
        for path in s["modified"]:
            print(path)
        if args.exit_code and dirty:
            raise SystemExit(1)
        return
    if args.name_status:
        for path in s["added"]:
            print(f"A\t{path}")
        for path in s["removed"]:
            print(f"D\t{path}")
        for path in s["modified"]:
            print(f"M\t{path}")
        if args.exit_code and dirty:
            raise SystemExit(1)
        return
    label = f"#{s['seq']} {s['id']}"
    if not dirty:
        console.print(f"[green]clean[/] [dim]working tree matches snapshot {label}[/]")
        return
    console.print(f"[dim]changes since snapshot {label}:[/]")
    for path in s["added"]:
        console.print(f"[green]+ {path}[/]")
    for path in s["removed"]:
        console.print(f"[red]- {path}[/]")
    for path in s["modified"]:
        console.print(f"[yellow]~ {path}[/]")
    # like 'git diff --exit-code', so a hook can save only when something changed
    if args.exit_code:
        raise SystemExit(1)


def _file_text(root, ref, path):
    # returns the file as text lines, or None if it isn't there or isn't
    # decodable (binary). callers treat None as "no text side to show".
    # ref "wt" reads the live working tree instead of a snapshot.
    if ref == "wt":
        try:
            data = open(os.path.join(root, path), "rb").read()
        except OSError:
            return None
    else:
        try:
            data = store.show(root, ref, path)
        except store.QuicksaveError:
            return None
    try:
        return data.decode().splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def _patch_entries(root, a, b, paths, git=False):
    # for each changed path, the unified diff oldest side a, newer side b.
    # added/removed/modified all fall out of unified_diff once the missing side
    # is an empty list. binary files have no text on either side, so diff is None.
    # git mode emits a/ b/ headers and /dev/null for the missing side so the
    # output applies with 'git apply' or 'patch -p1'.
    import difflib
    for path in paths:
        ta = _file_text(root, a, path)
        tb = _file_text(root, b, path)
        if ta is None and tb is None:
            yield path, None
            continue
        if git:
            fromfile = "/dev/null" if ta is None else f"a/{path}"
            tofile = "/dev/null" if tb is None else f"b/{path}"
            body = "".join(difflib.unified_diff(ta or [], tb or [],
                                                fromfile=fromfile, tofile=tofile))
            if not body:
                yield path, ""
                continue
            head = f"diff --git a/{path} b/{path}\n"
            if ta is None:
                head += "new file mode 100644\n"
            elif tb is None:
                head += "deleted file mode 100644\n"
            text = head + body
        else:
            text = "".join(difflib.unified_diff(ta or [], tb or [],
                                                fromfile=f"{path}@{a}",
                                                tofile=f"{path}@{b}"))
        yield path, text


def _emit_patch(root, a, b, paths, git=False):
    for path, text in _patch_entries(root, a, b, paths, git=git):
        if text is None:
            # keep the patch stream clean so it pipes into git apply
            (err if git else console).print(f"[dim]Binary file {path} differs[/]")
            continue
        if git:
            for line in text.splitlines():
                print(line)
            continue
        for line in text.splitlines():
            if line.startswith("+"):
                console.print(f"[green]{line}[/]")
            elif line.startswith("-"):
                console.print(f"[red]{line}[/]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{line}[/]")
            else:
                console.print(line)


def _patch_json(root, a, b, paths):
    files = [{"path": path, "diff": text or None}
             for path, text in _patch_entries(root, a, b, paths)]
    print(json.dumps({"a": a, "b": b, "files": files}))


def cmd_diff(args):
    root = _root_or_die()
    if args.path:
        import difflib
        a = _file_text(root, args.a, args.path)
        b = _file_text(root, args.b, args.path)
        if a is None and b is None:
            if args.json:
                print(json.dumps({"path": args.path, "a": args.a, "b": args.b, "diff": None}))
                return
            console.print(f"[dim]{args.path} is in neither {args.a} nor {args.b}, or is binary[/]")
            return
        lines = list(difflib.unified_diff(a or [], b or [],
                                          fromfile=f"{args.path}@{args.a}",
                                          tofile=f"{args.path}@{args.b}"))
        if args.json:
            text = "".join(lines)
            print(json.dumps({"path": args.path, "a": args.a, "b": args.b,
                              "diff": text or None}))
            return
        printed = False
        for line in lines:
            printed = True
            line = line.rstrip("\n")
            if line.startswith("+"):
                console.print(f"[green]{line}[/]")
            elif line.startswith("-"):
                console.print(f"[red]{line}[/]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{line}[/]")
            else:
                console.print(line)
        if not printed:
            console.print(f"[dim]{args.path} is identical in {args.a} and {args.b}[/]")
        return
    if args.a == "wt" or args.b == "wt":
        # one side is the live working tree, reuse status (snapshot vs tree)
        snap = args.b if args.a == "wt" else args.a
        s = store.status(root, snap)
        added, removed = s["added"], s["removed"]
        if args.a == "wt":
            added, removed = removed, added
        if args.json:
            if args.patch:
                _patch_json(root, args.a, args.b, added + removed + s["modified"])
                return
            print(json.dumps({"a": args.a, "b": args.b, "added": added,
                              "removed": removed, "modified": s["modified"]}))
            return
        if not (added or removed or s["modified"]):
            console.print(f"[dim]working tree matches {snap}[/]")
            return
        if args.patch:
            _emit_patch(root, args.a, args.b, added + removed + s["modified"],
                        git=args.git)
            return
        if args.name_only:
            for path in added:
                print(path)
            for path in removed:
                print(path)
            for path in s["modified"]:
                print(path)
            return
        if args.name_status:
            for path in added:
                print(f"A\t{path}")
            for path in removed:
                print(f"D\t{path}")
            for path in s["modified"]:
                print(f"M\t{path}")
            return
        if not args.stat:
            for path in added:
                console.print(f"[green]+ {path}[/]")
            for path in removed:
                console.print(f"[red]- {path}[/]")
            for path in s["modified"]:
                console.print(f"[yellow]~ {path}[/]")
        console.print(
            f"[dim]{len(added)} added, {len(removed)} removed, "
            f"{len(s['modified'])} modified[/]"
        )
        return
    d = store.diff(root, args.a, args.b)
    if args.json:
        if args.patch:
            _patch_json(root, args.a, args.b,
                        d["added"] + d["removed"] + d["modified"])
            return
        print(json.dumps({"a": args.a, "b": args.b, "added": d["added"],
                          "removed": d["removed"], "modified": d["modified"]}))
        return
    if not any(d.values()):
        console.print(f"[dim]no changes between {args.a} and {args.b}[/]")
        return
    if args.patch:
        _emit_patch(root, args.a, args.b, d["added"] + d["removed"] + d["modified"],
                    git=args.git)
        return
    if args.name_only:
        for path in d["added"]:
            print(path)
        for path in d["removed"]:
            print(path)
        for path in d["modified"]:
            print(path)
        return
    if args.name_status:
        for path in d["added"]:
            print(f"A\t{path}")
        for path in d["removed"]:
            print(f"D\t{path}")
        for path in d["modified"]:
            print(f"M\t{path}")
        return
    if not args.stat:
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
    # one positional means just a path: print it from the newest snapshot that
    # still has it. two means an explicit ref then the path.
    if args.path is None:
        ref, path = None, args.ref
    else:
        ref, path = args.ref, args.path
    data = store.show(root, ref, path)
    with open(1, "wb", closefd=False) as out:
        out.write(data)


def cmd_grep(args):
    root = _root_or_die()
    hits = store.grep_snapshot(root, args.ref, args.pattern,
                               ignore_case=args.ignore_case,
                               paths=args.paths or None,
                               fixed=args.fixed,
                               word=args.word)
    if args.count:
        print(sum(1 for _ in hits))
        return
    if args.name_only:
        seen = set()
        for path, _, _ in hits:
            if path not in seen:
                seen.add(path)
                print(path)
        return
    if args.json:
        print(json.dumps([{"path": p, "line": n, "text": t} for p, n, t in hits]))
        return
    for path, n, text in hits:
        console.print(f"[cyan]{path}[/]:[yellow]{n}[/]:{text}")


def cmd_export(args):
    root = _root_or_die()
    ref = args.ref or "latest"
    if args.dest == "-":
        n, _ = store.export_snapshot(root, args.ref, args.dest, args.paths or None,
                                     out=sys.stdout.buffer, gzip=args.gzip)
        err.print(f"exported [cyan]{n}[/] files from [cyan]{ref}[/] to [dim]stdout[/]")
        return
    n, dest = store.export_snapshot(root, args.ref, args.dest, args.paths or None,
                                    gzip=args.gzip)
    console.print(f"exported [cyan]{n}[/] files from [cyan]{ref}[/] to [dim]{dest}[/]")


def cmd_import(args):
    root = _root_or_die()
    fileobj = sys.stdin.buffer if args.src == "-" else None
    label_src = "stdin" if args.src == "-" else args.src
    if args.dry_run:
        r = store.import_archive(root, args.src, args.message, args.name,
                                 fileobj=fileobj, dry_run=True)
        label = f" as [magenta]{r['name']}[/]" if r["name"] else ""
        console.print(
            f"[dim](dry run)[/] [cyan]{r['files']}[/] files, "
            f"[cyan]{_human_size(r['bytes'])}[/] from [dim]{label_src}[/]{label}"
        )
        for p in r["paths"][:10]:
            console.print(f"  [dim]{p}[/]")
        if r["files"] > 10:
            console.print(f"  [dim]... and {r['files'] - 10} more[/]")
        return
    snap_id, n = store.import_archive(root, args.src, args.message, args.name,
                                      fileobj=fileobj)
    label = f" [magenta]{args.name}[/]" if args.name else ""
    console.print(f"imported [cyan]{n}[/] files from [dim]{label_src}[/] as [cyan]{snap_id}[/]{label}")


def cmd_name(args):
    root = _root_or_die()
    snap_id, old = store.set_name(root, args.ref, args.name)
    if not args.name:
        if old:
            console.print(f"cleared name [magenta]{old}[/] from [cyan]{snap_id}[/]")
        else:
            console.print(f"[dim]{snap_id} had no name[/]")
        return
    if old and old != args.name:
        console.print(f"renamed [cyan]{snap_id}[/] [magenta]{old}[/] -> [magenta]{args.name}[/]")
    else:
        console.print(f"named [cyan]{snap_id}[/] [magenta]{args.name}[/]")


def cmd_pin(args):
    root = _root_or_die()
    snap_id, was = store.set_pinned(root, args.ref, True)
    if was:
        console.print(f"[dim]{snap_id} already pinned[/]")
    else:
        console.print(f"[green]pinned[/] [cyan]{snap_id}[/], gc --keep won't drop it")


def cmd_unpin(args):
    root = _root_or_die()
    snap_id, was = store.set_pinned(root, args.ref, False)
    if was:
        console.print(f"unpinned [cyan]{snap_id}[/]")
    else:
        console.print(f"[dim]{snap_id} wasn't pinned[/]")


def cmd_log(args):
    root = _root_or_die()
    s = store.snapshot_detail(root, args.ref)
    if args.json:
        print(json.dumps(s))
        return
    if args.name_only:
        for h in s["files"]:
            print(h["path"])
        return

    when = "-"
    if s["created_at"]:
        when = datetime.fromtimestamp(s["created_at"]).strftime("%Y-%m-%d %H:%M:%S")

    console.print(f"Snapshot: {s['id']}")
    console.print(f"Name: {s['name'] or '-'}")
    console.print(f"Pinned: {'yes' if s['pinned'] else 'no'}")
    console.print(f"Message: {s['message'] or '-'}")
    console.print(f"Time: {when}")
    total = sum(h["size"] for h in s["files"])
    console.print(f"Files: {len(s['files'])} ({_human_size(total)})")

    console.print("\nFile List:")
    for h in s["files"]:
        console.print(f"{h['path']} ({_human_size(h['size'])})")


def cmd_verify(args):
    root = _root_or_die()
    if args.repair:
        r = store.repair(root, dry_run=args.dry_run)
        if args.json:
            print(json.dumps(r))
            return
        tag = " [dim](dry run)[/]" if r["dry_run"] else ""
        if not r["dropped"] and not r["corrupt_blobs"]:
            console.print(f"[green]ok[/] [dim]nothing to repair[/]{tag}")
            return
        for name in r["dropped"]:
            console.print(f"[red]- snapshot {name}[/] (referenced a bad blob)")
        console.print(
            f"dropped [cyan]{len(r['dropped'])}[/] snapshots, "
            f"deleted [cyan]{r['corrupt_blobs']}[/] corrupt blobs, "
            f"swept [cyan]{r['blobs']}[/] orphaned blobs{tag}"
        )
        return
    r = store.verify(root)
    if args.json:
        print(json.dumps(r))
        return
    if r["ok"]:
        console.print(f"[green]ok[/] [dim]{r['blobs']} blobs, all snapshots intact[/]")
        return
    for digest in r["corrupt"]:
        console.print(f"[red]corrupt blob {digest[:12]}[/] (content no longer hashes to its name)")
    for m in r["missing"]:
        console.print(f"[red]missing {m['sha256'][:12]}[/] for {m['path']} [dim](snapshot {m['snapshot']})[/]")
    console.print(
        f"[dim]{r['blobs']} blobs, {len(r['corrupt'])} corrupt, {len(r['missing'])} missing[/]"
    )
    raise SystemExit(1)


def cmd_gc(args):
    root = _root_or_die()
    older = store.parse_duration(args.older_than) if args.older_than else None
    within = store.parse_duration(args.keep_within) if args.keep_within else None
    r = store.gc(root, keep=args.keep, refs=args.refs, dry_run=args.dry_run, older_than=older,
                 keep_named=args.keep_named, keep_within=within)
    if args.json:
        print(json.dumps(r))
        return
    tag = " [dim](dry run)[/]" if r["dry_run"] else ""
    if r["pruned"]:
        for name in r["pruned"]:
            console.print(f"[red]- snapshot {name}[/]")
    if not r["pruned"] and not r["blobs"]:
        console.print(f"[green]nothing to collect[/]{tag}")
        return
    verb = "would free" if r["dry_run"] else "freed"
    console.print(
        f"removed [cyan]{len(r['pruned'])}[/] snapshots, "
        f"[cyan]{r['blobs']}[/] unreferenced blobs, "
        f"{verb} [cyan]{_human_size(r['bytes'])}[/]{tag}"
    )


def cmd_drop(args):
    root = _root_or_die()
    r = store.drop(root, args.refs, force=args.force, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(r))
        return
    tag = " [dim](dry run)[/]" if r["dry_run"] else ""
    verb = "would free" if r["dry_run"] else "freed"
    sids = ", ".join(stem.partition("-")[2] for stem in r["dropped"])
    noun = "snapshot" if len(r["dropped"]) == 1 else "snapshots"
    console.print(
        f"dropped {noun} [cyan]{sids}[/], "
        f"[cyan]{r['blobs']}[/] unreferenced blobs, {verb} [cyan]{_human_size(r['bytes'])}[/]{tag}"
    )


def _env_keep():
    raw = os.environ.get("QUICKSAVE_KEEP")
    if not raw:
        return None
    try:
        keep = int(raw)
    except ValueError:
        return None
    return keep if keep > 0 else None


def cmd_hook(args):
    # reads a Claude Code PreToolUse payload on stdin and snapshots before a
    # risky bash command. stays quiet and exits 0 so it never blocks the agent.
    check = getattr(args, "check", None)
    if check is not None:
        # tune QUICKSAVE_RISKY patterns without an agent: exit 0 on a match,
        # 1 otherwise, so it composes in scripts the way grep does. on a hit the
        # matching pattern rides along after a tab so you can see what tripped.
        hit = store.risky_match(check)
        if hit is not None:
            print(f"risky\t{hit}")
        else:
            print("safe")
            raise SystemExit(1)
        return
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
    # an agent fires this on every risky command, so the store grows without
    # bound. QUICKSAVE_KEEP caps it to the N most recent snapshots if set.
    keep = _env_keep()
    if keep is not None:
        store.gc(root, keep=keep)


_BASH_COMPLETION = """\
_quicksave() {
    local cur cmds
    cur="${COMP_WORDS[COMP_CWORD]}"
    cmds="__CMDS__"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
    elif [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "-q --quiet --json --dry-run --help" -- "$cur") )
    else
        COMPREPLY=( $(compgen -f -- "$cur") )
    fi
}
complete -F _quicksave quicksave
"""

_ZSH_COMPLETION = """\
#compdef quicksave
_quicksave() {
    local -a cmds
    cmds=(__CMDS__)
    if (( CURRENT == 2 )); then
        compadd -- $cmds
    elif [[ $words[CURRENT] == -* ]]; then
        compadd -- -q --quiet --json --dry-run --help
    else
        _files
    fi
}
compdef _quicksave quicksave
"""
_FISH_COMPLETION = """\
complete -c quicksave -f -n __fish_use_subcommand -a "__CMDS__"
complete -c quicksave -l help -l json -l dry-run -l quiet -s q
complete -c quicksave -n 'not __fish_use_subcommand' -F
"""
_PWSH_COMPLETION = """\
Register-ArgumentCompleter -Native -CommandName quicksave -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $cmds = '__CMDS__'.Split(' ')
    # element 0 is 'quicksave' itself, so <= 2 elements means we're on the subcommand
    if ($commandAst.CommandElements.Count -le 2) {
        $cmds | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
    }
    # past the subcommand, offer the common flags when a dash is typed,
    # otherwise return nothing so PowerShell falls back to file paths
    elseif ($wordToComplete -like '-*') {
        '-q', '--quiet', '--json', '--dry-run', '--help' | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
        }
    }
}
"""

def _subcommands():
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    return []


def cmd_completion(args):
    cmds = " ".join(_subcommands())
    scripts = {"bash": _BASH_COMPLETION, "zsh": _ZSH_COMPLETION, "fish": _FISH_COMPLETION,
               "powershell": _PWSH_COMPLETION}
    # plain print so 'eval "$(quicksave completion bash)"' gets a clean script
    print(scripts[args.shell].replace("__CMDS__", cmds), end="")


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
    ps.add_argument("-m", "--message", default="", help="snapshot message, or - to read it from stdin")
    ps.add_argument("-n", "--name", default="",
                    help="label the snapshot so you can restore it by name later")
    ps.add_argument("-f", "--force", action="store_true",
                    help="snapshot even if nothing changed since the last one")
    ps.add_argument("--dry-run", action="store_true",
                    help="show what would be captured without writing a snapshot")
    ps.add_argument("--json", action="store_true", help="print the saved snapshot as json")
    ps.set_defaults(func=cmd_save)

    pl = sub.add_parser("list", help="list snapshots", parents=[common])
    pl.add_argument("--json", action="store_true", help="print snapshots as json")
    pl.add_argument("--limit", type=int, help="show only the n most recent snapshots")
    pl.add_argument("--absolute", action="store_true", help="show full timestamps instead of relative time")
    pl.add_argument("--pinned", action="store_true", help="show only pinned snapshots")
    pl.add_argument("--since", default=None, metavar="DUR",
                    help="show only snapshots newer than a duration (1h, 7d) or date (2026-06-01)")
    pl.add_argument("--before", default=None, metavar="DUR",
                    help="show only snapshots older than a duration (1h, 7d) or date (2026-06-01)")
    pl.add_argument("--grep", default=None, metavar="TEXT",
                    help="show only snapshots whose message or name contains this text")
    pl.add_argument("--reverse", action="store_true", help="show newest first instead of oldest first")
    pl.add_argument("--count", action="store_true",
                    help="print only the number of matching snapshots, nothing else")
    pl.set_defaults(func=cmd_list)

    pnm = sub.add_parser("names", help="list named snapshots, newest first", parents=[common])
    pnm.add_argument("--json", action="store_true", help="print the named snapshots as json")
    pnm.add_argument("--grep", default=None, metavar="TEXT",
                     help="show only named snapshots whose name contains this text")
    pnm.add_argument("--reverse", action="store_true", help="show oldest first instead of newest first")
    pnm.add_argument("--limit", type=int, help="show only the n most recent named snapshots")
    pnm.add_argument("--count", action="store_true",
                     help="print only the number of matching named snapshots, nothing else")
    pnm.set_defaults(func=cmd_names)

    pst = sub.add_parser("stats", help="show store size and how much dedup is saving", parents=[common])
    pst.add_argument("--json", action="store_true", help="print the stats as json")
    pst.add_argument("--markdown", action="store_true", help="print a small markdown table to paste into a readme or tweet")
    pst.add_argument("--top", type=int, default=5, metavar="N",
                     help="show the N snapshots with the most uniquely-owned bytes (0 to hide)")
    pst.set_defaults(func=cmd_stats)

    pf = sub.add_parser("find", help="find which snapshots hold a file, newest first", parents=[common])
    pf.add_argument("path", nargs="+",
                    help="one or more file paths, parts of paths, or globs like '*.py' to search for")
    pf.add_argument("--json", action="store_true", help="print matches as json")
    pf.add_argument("-i", "--ignore-case", action="store_true",
                    help="match the path case-insensitively, so 'readme' finds README.md")
    pf.add_argument("--since", default=None, metavar="DUR",
                    help="only snapshots newer than a duration (1h, 7d) or date (2026-06-01)")
    pf.add_argument("--before", default=None, metavar="DUR",
                    help="only snapshots older than a duration (1h, 7d) or date (2026-06-01)")
    pf.add_argument("--changes", action="store_true",
                    help="show only snapshots where the matched content changed, skipping repeats")
    pf.add_argument("--diff", action="store_true",
                    help="with --changes, print a unified diff between each consecutive change point (single-file queries only)")
    pf.add_argument("--reverse", action="store_true",
                    help="show oldest match first instead of newest, to read a file's history forward")
    pf.add_argument("--limit", type=int, help="show only the n newest matching snapshots")
    pf.add_argument("--count", action="store_true",
                    help="print only the number of matching snapshots, nothing else")
    pf.set_defaults(func=cmd_find)

    prc = sub.add_parser("recover", help="restore files from the newest snapshot that still has them", parents=[common])
    prc.add_argument("path", nargs="+", help="one or more file paths, or parts of one, to bring back")
    prc.add_argument("--from", dest="from_ref", metavar="REF",
                     help="recover from this snapshot instead of the newest one that holds a match")
    prc.add_argument("--dry-run", action="store_true",
                     help="show which files recover would bring back without writing anything")
    prc.add_argument("--no-backup", action="store_true",
                     help="don't snapshot the current tree before recovering")
    prc.add_argument("--into", metavar="DIR",
                     help="write the matches into DIR instead of overwriting the tree")
    prc.add_argument("--json", action="store_true",
                     help="print which snapshot was used and the recovered files as json")
    prc.set_defaults(func=cmd_recover)

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
    pr.add_argument("--into", metavar="DIR",
                    help="write the snapshot into DIR instead of overwriting the tree")
    pr.add_argument("--json", action="store_true", help="print the result as json")
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
    pt.add_argument("--short", action="store_true",
                    help="print a one-line porcelain summary like '~3 +1 -0', or 'clean'")
    pt.add_argument("--stat", action="store_true",
                    help="print only the summary line, like 'diff --stat', or 'clean'")
    pt.add_argument("--name-only", action="store_true",
                    help="print just the changed paths, one per line, no markers and no summary")
    pt.add_argument("--name-status", action="store_true",
                    help="print each path prefixed with A/D/M and a tab, like 'git diff --name-status'")
    pt.add_argument("--exit-code", action="store_true",
                    help="exit 1 if the tree changed, 0 if clean, like 'git diff --exit-code'")
    pt.set_defaults(func=cmd_status)

    pci = sub.add_parser("check-ignore",
                         help="show whether paths would be captured or ignored, and which rule decided",
                         parents=[common])
    pci.add_argument("paths", nargs="+", metavar="path", help="paths to test against the ignore rules")
    pci.add_argument("--json", action="store_true", help="print the verdicts as json")
    pci.add_argument("--exit-code", action="store_true",
                     help="exit non-zero unless every listed path is ignored")
    pci.set_defaults(func=cmd_check_ignore)

    pd = sub.add_parser("diff", help="show what changed between two snapshots, or a snapshot and the working tree", parents=[common])
    pd.add_argument("a", help="snapshot id or number, or 'wt' for the working tree")
    pd.add_argument("b", nargs="?", default="wt",
                    help="snapshot id or number, or 'wt' for the working tree (default)")
    pd.add_argument("path", nargs="?", help="show a line-by-line diff of just this file")
    pd.add_argument("--json", action="store_true", help="print the diff as json")
    pd.add_argument("--stat", action="store_true", help="print only the summary line, skip the file list")
    pd.add_argument("--name-only", action="store_true",
                    help="print just the changed paths, one per line, no markers and no summary")
    pd.add_argument("--name-status", action="store_true",
                    help="print each path prefixed with A/D/M and a tab, like 'git diff --name-status'")
    pd.add_argument("-p", "--patch", action="store_true",
                    help="print a unified diff of every changed file, like 'git diff'")
    pd.add_argument("--git", action="store_true",
                    help="with -p, emit a 'git apply'/'patch -p1' compatible diff (a/ b/ headers, no color)")
    pd.set_defaults(func=cmd_diff)

    ph = sub.add_parser("show", help="print a file's contents to stdout, from a snapshot or the newest one that has it", parents=[common])
    ph.add_argument("ref", help="snapshot id or number, or just the file if you want the newest snapshot that has it")
    ph.add_argument("path", nargs="?", help="file to print (omit to treat ref as the file)")
    ph.set_defaults(func=cmd_show)

    pgr = sub.add_parser("grep", help="search a snapshot's file contents for a pattern", parents=[common])
    pgr.add_argument("pattern", help="regular expression to search for (or a literal with -F)")
    pgr.add_argument("paths", nargs="*", help="limit the search to these paths")
    pgr.add_argument("-r", "--ref", help="snapshot id, number or name (default latest)")
    pgr.add_argument("-i", "--ignore-case", action="store_true", help="case-insensitive match")
    pgr.add_argument("-F", "--fixed", "--fixed-strings", action="store_true",
                     help="treat the pattern as a literal string, not a regex")
    pgr.add_argument("-w", "--word", "--word-regexp", action="store_true",
                     help="match whole words only, so 'foo' won't hit 'foobar'")
    pgr.add_argument("-l", "--name-only", action="store_true", help="print only the matching file paths")
    pgr.add_argument("--count", action="store_true", help="print only the number of matching lines")
    pgr.add_argument("--json", action="store_true", help="print matches as json")
    pgr.set_defaults(func=cmd_grep)

    pe = sub.add_parser("export", help="write a snapshot to a tar archive without touching the tree", parents=[common])
    pe.add_argument("dest", help="output path (.tar.gz/.tgz for gzip, else plain .tar), or - for stdout")
    pe.add_argument("ref", nargs="?", help="snapshot id, number or name (default latest)")
    pe.add_argument("paths", nargs="*", help="limit the export to these paths")
    pe.add_argument("-z", "--gzip", action="store_true", help="gzip the archive, even when streaming to stdout")
    pe.set_defaults(func=cmd_export)

    pi = sub.add_parser("import", help="read a tar archive back into a new snapshot without touching the tree", parents=[common])
    pi.add_argument("src", help="archive to read (.tar/.tar.gz/.tgz), or - for stdin")
    pi.add_argument("-m", "--message", default="", help="snapshot message")
    pi.add_argument("--name", default="", help="label for the new snapshot")
    pi.add_argument("--dry-run", action="store_true",
                    help="show what the archive holds without writing a snapshot")
    pi.set_defaults(func=cmd_import)

    plog = sub.add_parser("log", help="show one snapshot's details (default latest)", parents=[common])
    plog.add_argument("ref", nargs="?", default=None, help="snapshot id, number or name, defaults to latest")
    plog.add_argument("--json", action="store_true", help="print the snapshot details as json")
    plog.add_argument("--name-only", action="store_true", help="print only the file paths, one per line")
    plog.set_defaults(func=cmd_log)

    pn = sub.add_parser("name", help="label a snapshot, or clear its name with an empty value", parents=[common])
    pn.add_argument("ref", help="snapshot id, number or current name")
    pn.add_argument("name", nargs="?", default="", help="new name, omit to clear")
    pn.set_defaults(func=cmd_name)

    pp = sub.add_parser("pin", help="protect a snapshot from gc --keep rotation", parents=[common])
    pp.add_argument("ref", help="snapshot id, number or name")
    pp.set_defaults(func=cmd_pin)

    pup = sub.add_parser("unpin", help="let gc --keep rotate a snapshot again", parents=[common])
    pup.add_argument("ref", help="snapshot id, number or name")
    pup.set_defaults(func=cmd_unpin)

    pv = sub.add_parser("verify", help="check the store for corrupt or missing blobs", parents=[common])
    pv.add_argument("--json", action="store_true", help="print the result as json")
    pv.add_argument("--repair", action="store_true",
                    help="drop snapshots with corrupt or missing blobs")
    pv.add_argument("--dry-run", action="store_true",
                    help="with --repair, show what would be dropped without touching the store")
    pv.set_defaults(func=cmd_verify)

    pg = sub.add_parser("gc", help="drop old snapshots and unreferenced blobs", parents=[common])
    pg.add_argument("refs", nargs="*",
                    help="drop these specific snapshots too (id, number or name)")
    pg.add_argument("--keep", type=int, default=None,
                    help="keep only the N most recent snapshots")
    pg.add_argument("--older-than", default=None, metavar="DUR",
                    help="drop snapshots older than a duration (7d, 12h) or date (2026-06-01)")
    pg.add_argument("--keep-named", action="store_true",
                    help="spare named snapshots from --keep and --older-than rotation, like pinned ones")
    pg.add_argument("--keep-within", default=None, metavar="DUR",
                    help="spare snapshots newer than a duration (2h, 30m) from --keep rotation")
    pg.add_argument("--dry-run", action="store_true",
                    help="show what would be removed without deleting")
    pg.add_argument("--json", action="store_true", help="print what gc removed as json")
    pg.set_defaults(func=cmd_gc)

    pdr = sub.add_parser("drop", help="drop snapshots by ref and reclaim their blobs", parents=[common])
    pdr.add_argument("refs", nargs="+", metavar="ref",
                     help="snapshot id, number or name from 'quicksave list', one or more")
    pdr.add_argument("--force", action="store_true", help="drop even if the snapshot is pinned")
    pdr.add_argument("--dry-run", action="store_true",
                     help="show what would be removed without deleting")
    pdr.add_argument("--json", action="store_true", help="print what drop removed as json")
    pdr.set_defaults(func=cmd_drop)

    pcomp = sub.add_parser("completion", help="print a tab-completion script for your shell", parents=[common])
    pcomp.add_argument("shell", choices=("bash", "zsh", "fish", "powershell"),
                       help="which shell to emit a completion script for")
    pcomp.set_defaults(func=cmd_completion)

    phook = sub.add_parser("hook", help="PreToolUse hook: auto-save before a risky bash command", parents=[common])
    phook.add_argument("--check", metavar="CMD",
                       help="print whether CMD would trigger a snapshot, then exit (0 risky, 1 safe)")
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
    if "NO_COLOR" in os.environ:
        # honor the NO_COLOR convention (https://no-color.org): set to anything = plain text
        global console, err
        console = Console(color_system=None)
        err = Console(stderr=True, color_system=None)
    console.quiet = getattr(args, "quiet", False)
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
