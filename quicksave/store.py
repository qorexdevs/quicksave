import fnmatch
import hashlib
import io
import json
import os
import re
import tarfile
import time
from datetime import datetime
from pathlib import Path

STORE_DIR = ".quicksave"

# extra ignore patterns are read from these, gitignore-style globs
IGNORE_FILES = (".quicksaveignore", ".gitignore")

# dirs we never want in a snapshot: vcs metadata, caches, vendored deps, envs
DEFAULT_IGNORE = {
    ".git", ".hg", ".svn",
    STORE_DIR,
    "node_modules", "bower_components",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "venv", ".venv", "env", "virtualenv",
    "dist", "build", ".next", ".cache",
    ".idea", ".vscode", ".DS_Store",
}


class QuicksaveError(Exception):
    pass


def store_path(root):
    return Path(root) / STORE_DIR


def find_root(start=None):
    cur = Path(start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / STORE_DIR).is_dir():
            return p
    return None


def init(path=None):
    root = Path(path or Path.cwd()).resolve()
    store = store_path(root)
    if store.is_dir():
        return root, False
    (store / "objects").mkdir(parents=True)
    (store / "snapshots").mkdir(parents=True)
    return root, True


def load_patterns(root):
    # gitignore-style globs, comments and blanks dropped, no full gitignore semantics
    pats = []
    for name in IGNORE_FILES:
        f = Path(root) / name
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # no full gitignore semantics here, so a negation can't re-include an
            # already-ignored path. stripping the '!' would flip it into an ignore
            # rule, the opposite of what was meant, so skip the line instead.
            if line.startswith("!"):
                continue
            pats.append(line.rstrip("/"))
    return pats


def _matches(relpath, patterns):
    parts = relpath.split("/")
    base = parts[-1]
    for pat in patterns:
        if not pat:
            continue
        if fnmatch.fnmatch(relpath, pat) or fnmatch.fnmatch(base, pat):
            return True
        # a bare name like "logs" ignores it at any depth
        if "/" not in pat and any(fnmatch.fnmatch(seg, pat) for seg in parts):
            return True
        # a path like "build/out" ignores everything under it
        if relpath == pat or relpath.startswith(pat + "/"):
            return True
    return False


def iter_files(root, ignore=DEFAULT_IGNORE, patterns=None):
    root = Path(root)
    if patterns is None:
        patterns = load_patterns(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        kept = []
        for d in dirnames:
            if d in ignore:
                continue
            rel = d if str(rel_dir) == "." else (rel_dir / d).as_posix()
            if patterns and _matches(rel, patterns):
                continue
            kept.append(d)
        # prune ignored dirs so os.walk does not descend into them
        dirnames[:] = kept
        for name in filenames:
            if name in ignore:
                continue
            rel = Path(name) if str(rel_dir) == "." else rel_dir / name
            if patterns and _matches(rel.as_posix(), patterns):
                continue
            yield rel


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _write_blob(store, data):
    digest = _sha256(data)
    obj = store / "objects" / digest[:2] / digest[2:]
    if not obj.exists():
        obj.parent.mkdir(parents=True, exist_ok=True)
        tmp = obj.with_name(obj.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(obj)
    return digest


def _snapshot_files(store):
    d = Path(store) / "snapshots"
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


def save(root, message="", ignore=DEFAULT_IGNORE, force=False, name=""):
    root = Path(root)
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")
    if name and name.isdigit():
        raise QuicksaveError("snapshot name can't be all digits, it would clash with list numbers")

    files = {}
    for rel in iter_files(root, ignore):
        full = root / rel
        try:
            data = full.read_bytes()
        except OSError:
            continue
        digest = _write_blob(store, data)
        files[rel.as_posix()] = {
            "sha256": digest,
            "size": len(data),
            "mode": full.stat().st_mode & 0o777,
        }

    # nothing changed since the last snapshot: skip the dup so the hook firing on
    # every command doesn't pile up identical manifests. blobs already existed.
    snaps = _snapshot_files(store)
    if snaps and not force and json.loads(snaps[-1].read_text())["files"] == files:
        last = snaps[-1]
        m = json.loads(last.read_text())
        _, _, snap_id = last.stem.partition("-")
        # nothing to snapshot, but let a name still land on the existing one
        if name and m.get("name") != name:
            m["name"] = name
            last.write_text(json.dumps(m, indent=2))
        return snap_id, len(files), False

    manifest = {"message": message, "name": name, "created_at": time.time(), "files": files}
    body = json.dumps(manifest, sort_keys=True).encode()
    snap_id = _sha256(body)[:12]
    name = f"{len(snaps):04d}-{snap_id}.json"
    (store / "snapshots" / name).write_text(json.dumps(manifest, indent=2))
    return snap_id, len(files), True


def save_preview(root, ignore=DEFAULT_IGNORE):
    # what 'save' would capture, without writing any blobs or a manifest
    root = Path(root)
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")
    cur = {}
    total = 0
    for rel in iter_files(root, ignore):
        try:
            data = (root / rel).read_bytes()
        except OSError:
            continue
        cur[rel.as_posix()] = _sha256(data)
        total += len(data)
    snaps = _snapshot_files(store)
    snap = ({p: m["sha256"] for p, m in json.loads(snaps[-1].read_text())["files"].items()}
            if snaps else {})
    added = sorted(set(cur) - set(snap))
    removed = sorted(set(snap) - set(cur))
    modified = sorted(p for p in set(cur) & set(snap) if cur[p] != snap[p])
    return {
        "files": len(cur),
        "size": total,
        "added": added,
        "removed": removed,
        "modified": modified,
        "first": not snaps,
        "would_change": not snaps or bool(added or removed or modified),
    }


def set_name(root, ref, name):
    if name and name.isdigit():
        raise QuicksaveError("snapshot name can't be all digits, it would clash with list numbers")
    store = store_path(root)
    f = _resolve_snapshot(store, ref)
    m = json.loads(f.read_text())
    old = m.get("name", "")
    if name:
        m["name"] = name
    else:
        m.pop("name", None)
    f.write_text(json.dumps(m, indent=2))
    return f.stem.partition("-")[2], old


def set_pinned(root, ref, pinned):
    store = store_path(root)
    f = _resolve_snapshot(store, ref)
    m = json.loads(f.read_text())
    was = m.get("pinned", False)
    if pinned:
        m["pinned"] = True
    else:
        m.pop("pinned", None)
    f.write_text(json.dumps(m, indent=2))
    return f.stem.partition("-")[2], was


def list_snapshots(root):
    store = store_path(root)
    out = []
    for f in _snapshot_files(store):
        seq, _, snap_id = f.stem.partition("-")
        m = json.loads(f.read_text())
        files = m.get("files", {})
        out.append({
            "seq": int(seq),
            "id": snap_id,
            "name": m.get("name", ""),
            "message": m.get("message", ""),
            "created_at": m.get("created_at", 0),
            "count": len(files),
            "size": sum(meta.get("size", 0) for meta in files.values()),
            "pinned": m.get("pinned", False),
        })
    return out


def snapshot_detail(root, ref):
    # everything 'log' needs about one snapshot, resolved through the same ref
    # rules as the rest of the store so cli doesn't reach into the manifest itself.
    store = store_path(root)
    f = _resolve_snapshot(store, ref)
    m = json.loads(f.read_text())
    files = m.get("files", {})
    return {
        "seq": int(f.stem.partition("-")[0]),
        "id": f.stem.partition("-")[2],
        "name": m.get("name", ""),
        "message": m.get("message", ""),
        "pinned": m.get("pinned", False),
        "created_at": m.get("created_at", 0),
        "files": [
            {"path": p, "size": meta.get("size", 0), "sha256": meta.get("sha256", "")}
            for p, meta in sorted(files.items())
        ],
    }


def store_size(root):
    # bytes on disk in the object store: dedup means this is usually far less
    # than the sum of snapshot sizes, since unchanged files share one blob
    total = 0
    for obj, _ in _iter_blobs(store_path(root)):
        try:
            total += obj.stat().st_size
        except OSError:
            continue
    return total


def stats(root):
    # store health and how much dedup is buying you: logical size is what naive
    # copies of every snapshot would cost, disk is what content-addressed storage
    # actually uses, so logical/disk is the dedup ratio.
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")
    snaps = _snapshot_files(store)
    logical = 0
    times = []
    for f in snaps:
        m = json.loads(f.read_text())
        if m.get("created_at"):
            times.append(m["created_at"])
        for meta in m.get("files", {}).values():
            logical += meta.get("size", 0)
    blobs = 0
    disk = 0
    for obj, _ in _iter_blobs(store):
        blobs += 1
        try:
            disk += obj.stat().st_size
        except OSError:
            continue
    return {
        "snapshots": len(snaps),
        "blobs": blobs,
        "logical_bytes": logical,
        "disk_bytes": disk,
        "first": min(times) if times else 0,
        "last": max(times) if times else 0,
    }


def _relative_ref(ref):
    # 'latest' is the newest snapshot, 'latest~2' or '~2' steps back from it.
    # returns how many to count back from the end, or None when not relative.
    if ref == "latest":
        return 0
    for prefix in ("latest~", "~"):
        if ref.startswith(prefix):
            n = ref[len(prefix):]
            if n.isdigit():
                return int(n)
    return None


def _find_snapshot(store, ref):
    ref = str(ref)
    files = _snapshot_files(store)
    # relative refs count back from the newest, so 'latest~1' is the one before it
    back = _relative_ref(ref)
    if back is not None:
        return files[-1 - back] if 0 <= back < len(files) else None
    # a bare number is a sequence from 'list'; resolve it before any id-prefix
    # match so an id that happens to start with that digit can't shadow it
    for f in files:
        seq, _, _ = f.stem.partition("-")
        if f.stem == ref or (ref.isdigit() and int(seq) == int(ref)):
            return f
    # exact snapshot name, latest one wins if a name was reused
    for f in reversed(files):
        if json.loads(f.read_text()).get("name") == ref:
            return f
    for f in files:
        _, _, snap_id = f.stem.partition("-")
        if snap_id.startswith(ref):
            return f
    return None


def diff(root, ref_a, ref_b):
    store = store_path(root)
    fa = _find_snapshot(store, ref_a)
    if fa is None:
        raise QuicksaveError(f"snapshot '{ref_a}' not found")
    fb = _find_snapshot(store, ref_b)
    if fb is None:
        raise QuicksaveError(f"snapshot '{ref_b}' not found")

    a = json.loads(fa.read_text())["files"]
    b = json.loads(fb.read_text())["files"]
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    modified = sorted(p for p in set(a) & set(b) if a[p]["sha256"] != b[p]["sha256"])
    return {"added": added, "removed": removed, "modified": modified}


def find_file(root, query):
    # which snapshots hold a file matching `query` - the "I deleted foo.py, where
    # can I get it back" lookup. matches on exact path, a directory prefix, or the
    # query as a substring of the relpath so a bare basename finds src/foo.py.
    # if the query has glob chars (* ? [) we match relpaths with a shell glob
    # instead, so 'quicksave find *.py' or 'src/**/test_*.py' work.
    store = store_path(root)
    q = Path(query).as_posix()
    glob = any(c in query for c in "*?[")
    out = []
    for f in reversed(_snapshot_files(store)):
        seq, _, snap_id = f.stem.partition("-")
        m = json.loads(f.read_text())
        hits = []
        for rel, meta in m.get("files", {}).items():
            if glob:
                match = fnmatch.fnmatch(rel, q) or fnmatch.fnmatch(rel, "*/" + q)
            else:
                match = rel == q or rel.startswith(q.rstrip("/") + "/") or q in rel
            if match:
                hits.append({"path": rel, "size": meta.get("size", 0),
                             "sha256": meta.get("sha256", "")})
        if hits:
            out.append({
                "seq": int(seq),
                "id": snap_id,
                "name": m.get("name", ""),
                "message": m.get("message", ""),
                "created_at": m.get("created_at", 0),
                "files": sorted(hits, key=lambda h: h["path"]),
            })
    return out


def status(root, ref=None, ignore=DEFAULT_IGNORE):
    store = store_path(root)
    snaps = _snapshot_files(store)
    if not snaps:
        raise QuicksaveError("no snapshots yet, run 'quicksave save' first")
    f = snaps[-1] if ref is None else _find_snapshot(store, ref)
    if f is None:
        raise QuicksaveError(f"snapshot '{ref}' not found")

    snap = {p: m["sha256"] for p, m in json.loads(f.read_text())["files"].items()}
    cur = {}
    for rel in iter_files(root, ignore):
        try:
            cur[rel.as_posix()] = _sha256((Path(root) / rel).read_bytes())
        except OSError:
            continue

    seq, _, snap_id = f.stem.partition("-")
    return {
        "seq": int(seq),
        "id": snap_id,
        "added": sorted(set(cur) - set(snap)),
        "removed": sorted(set(snap) - set(cur)),
        "modified": sorted(p for p in set(cur) & set(snap) if cur[p] != snap[p]),
    }


def _referenced_blobs(snap_files):
    refs = set()
    for f in snap_files:
        for meta in json.loads(f.read_text())["files"].values():
            refs.add(meta["sha256"])
    return refs


def _iter_blobs(store):
    objects = Path(store) / "objects"
    if not objects.is_dir():
        return
    for shard in objects.iterdir():
        if not shard.is_dir():
            continue
        for obj in shard.iterdir():
            if obj.name.endswith(".tmp"):
                continue
            yield obj, shard.name + obj.name


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text):
    # "7d", "12h", "30m", "90s", "2w" -> seconds. plain digits mean seconds.
    # an absolute date ("2026-06-01", "2026-06-01T12:00") is read as seconds-ago
    # relative to now, so the same now - parse_duration(x) cutoff still works.
    m = re.fullmatch(r"\s*(\d+)\s*([smhdw]?)\s*", text or "", re.IGNORECASE)
    if m:
        return int(m.group(1)) * _DURATION_UNITS[(m.group(2) or "s").lower()]
    try:
        when = datetime.fromisoformat((text or "").strip())
    except ValueError:
        raise QuicksaveError(f"bad duration '{text}', use forms like 7d, 12h or a date like 2026-06-01")
    return time.time() - when.timestamp()


def gc(root, keep=None, refs=None, dry_run=False, older_than=None):
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")

    snaps = _snapshot_files(store)
    drop = list(snaps[: len(snaps) - keep]) if keep is not None and keep < len(snaps) else []
    if older_than is not None:
        cutoff = time.time() - older_than
        old = [f for f in snaps if json.loads(f.read_text()).get("created_at", 0) < cutoff]
        drop = drop + [f for f in old if f not in drop]
    # pinned snapshots survive --keep rotation; an explicit ref still drops them.
    drop = [f for f in drop if not json.loads(f.read_text()).get("pinned", False)]
    for ref in refs or []:
        f = _find_snapshot(store, ref)
        if f is None:
            raise QuicksaveError(f"snapshot '{ref}' not found")
        if f not in drop:
            drop.append(f)
    survivors = [f for f in snaps if f not in drop]

    pruned = []
    for f in drop:
        pruned.append(f.stem)
        if not dry_run:
            f.unlink()

    refs = _referenced_blobs(survivors)
    removed = 0
    freed = 0
    for obj, digest in list(_iter_blobs(store)):
        if digest in refs:
            continue
        removed += 1
        try:
            freed += obj.stat().st_size
        except OSError:
            pass
        if not dry_run:
            obj.unlink()
            shard = obj.parent
            try:
                shard.rmdir()
            except OSError:
                pass
    return {"pruned": pruned, "blobs": removed, "bytes": freed, "dry_run": dry_run}


def drop(root, ref, force=False, dry_run=False):
    # drop one specific snapshot you know you don't want, e.g. a checkpoint that
    # grabbed a build dir before you fixed the ignore file. gc prunes by policy,
    # this targets a single ref and then sweeps the blobs it was the last to hold.
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")
    f = _resolve_snapshot(store, ref)
    if json.loads(f.read_text()).get("pinned", False) and not force:
        raise QuicksaveError(f"snapshot '{ref}' is pinned, pass --force to drop it")

    survivors = [s for s in _snapshot_files(store) if s != f]
    if not dry_run:
        f.unlink()
    refs = _referenced_blobs(survivors)
    removed = 0
    freed = 0
    for obj, digest in list(_iter_blobs(store)):
        if digest in refs:
            continue
        removed += 1
        try:
            freed += obj.stat().st_size
        except OSError:
            pass
        if not dry_run:
            obj.unlink()
            try:
                obj.parent.rmdir()
            except OSError:
                pass
    return {"dropped": f.stem, "blobs": removed, "bytes": freed, "dry_run": dry_run}


def verify(root):
    # a backup store is only worth trusting if it isn't quietly rotting. check
    # two things: every blob still hashes to its own name (no bit-flips on disk),
    # and every file a snapshot points at actually has its blob.
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")

    blobs = 0
    corrupt = []
    on_disk = set()
    for obj, digest in _iter_blobs(store):
        blobs += 1
        on_disk.add(digest)
        if _sha256(obj.read_bytes()) != digest:
            corrupt.append(digest)

    missing = []
    for f in _snapshot_files(store):
        snap_id = f.stem.partition("-")[2]
        for relpath, meta in json.loads(f.read_text())["files"].items():
            if meta["sha256"] not in on_disk:
                missing.append({"snapshot": snap_id, "path": relpath, "sha256": meta["sha256"]})

    return {
        "blobs": blobs,
        "corrupt": sorted(set(corrupt)),
        "missing": missing,
        "ok": not corrupt and not missing,
    }


def repair(root, dry_run=False):
    # a snapshot is only as good as the blobs it points at. if verify finds any
    # corrupt or missing, the snapshots that reference them can't restore cleanly.
    # drop those snapshots (and delete the corrupt blobs) so the rest of the store
    # is trustworthy again, then sweep the orphaned blobs.
    store = store_path(root)
    state = verify(root)
    bad = set(state["corrupt"]) | {m["sha256"] for m in state["missing"]}
    if not bad:
        return {"dropped": [], "corrupt_blobs": 0, "blobs": 0, "dry_run": dry_run}

    corrupt_removed = 0
    for digest in state["corrupt"]:
        obj = store / "objects" / digest[:2] / digest[2:]
        corrupt_removed += 1
        if not dry_run:
            obj.unlink(missing_ok=True)

    snaps = _snapshot_files(store)
    survivors, dropped = [], []
    for f in snaps:
        shas = {m["sha256"] for m in json.loads(f.read_text())["files"].values()}
        if shas & bad:
            dropped.append(f.stem)
            if not dry_run:
                f.unlink()
        else:
            survivors.append(f)

    refs = _referenced_blobs(survivors)
    removed = 0
    for obj, digest in list(_iter_blobs(store)):
        if digest in refs:
            continue
        removed += 1
        if not dry_run:
            obj.unlink()
            try:
                obj.parent.rmdir()
            except OSError:
                pass
    return {"dropped": dropped, "corrupt_blobs": corrupt_removed, "blobs": removed, "dry_run": dry_run}


def show(root, ref, path):
    store = store_path(root)
    rel = Path(path).as_posix()
    if ref is None:
        # peek at a lost file without writing it: walk newest-first and take the
        # first snapshot that still has this exact path. the read-only sibling of
        # recover, so 'show config.env' works even after the file was deleted.
        for f in reversed(_snapshot_files(store)):
            files = json.loads(f.read_text())["files"]
            if rel in files:
                meta = files[rel]
                break
        else:
            raise QuicksaveError(f"no snapshot holds '{path}'")
    else:
        f = _find_snapshot(store, ref)
        if f is None:
            raise QuicksaveError(f"snapshot '{ref}' not found")
        files = json.loads(f.read_text())["files"]
        meta = files.get(rel)
        if meta is None:
            raise QuicksaveError(f"'{path}' not in snapshot '{ref}'")
    obj = store / "objects" / meta["sha256"][:2] / meta["sha256"][2:]
    if not obj.exists():
        raise QuicksaveError(f"missing blob {meta['sha256']} for {rel}")
    return obj.read_bytes()


def export_snapshot(root, ref, dest, paths=None, out=None, gzip=False):
    # materialize a snapshot into a tar archive without touching the live tree.
    # gzip when dest ends in .gz/.tgz or gzip is set, plain tar otherwise. handy
    # for archiving a known-good checkpoint or moving it to another machine. pass
    # out to stream a tar into an open binary file (e.g. stdout) instead of a path.
    store = store_path(root)
    f = _resolve_snapshot(store, ref)
    manifest = json.loads(f.read_text())
    files, _ = _selected_files(manifest, paths, ref)
    if not files:
        raise QuicksaveError("nothing to export")

    if out is not None:
        with tarfile.open(fileobj=out, mode="w|gz" if gzip else "w|") as tar:
            written = _add_to_tar(tar, store, manifest, files)
        return written, "-"

    dest = Path(dest)
    mode = "w:gz" if gzip or dest.suffix in (".gz", ".tgz") else "w"
    with tarfile.open(dest, mode) as tar:
        written = _add_to_tar(tar, store, manifest, files)
    return written, dest


def _add_to_tar(tar, store, manifest, files):
    written = 0
    for relpath, meta in sorted(files.items()):
        obj = store / "objects" / meta["sha256"][:2] / meta["sha256"][2:]
        if not obj.exists():
            raise QuicksaveError(f"missing blob {meta['sha256']} for {relpath}")
        data = obj.read_bytes()
        info = tarfile.TarInfo(relpath)
        info.size = len(data)
        info.mode = meta.get("mode", 0o644) & 0o777
        if manifest.get("created_at"):
            info.mtime = int(manifest["created_at"])
        tar.addfile(info, io.BytesIO(data))
        written += 1
    return written


def _open_archive(src):
    # tarfile auto-detects gzip/plain; src is a path or a seekable binary stream
    if isinstance(src, (str, Path)):
        return tarfile.open(src)
    return tarfile.open(fileobj=src)


def import_archive(root, src, message="", name="", fileobj=None):
    # turn a tar archive (from 'export' or any plain tarball) into a fresh
    # snapshot: every regular file becomes a blob and lands in a new manifest,
    # without touching the live tree. restore it later to materialize the files.
    # pass fileobj to read the archive from an open binary stream (e.g. stdin).
    root = Path(root)
    store = store_path(root)
    if not store.is_dir():
        raise QuicksaveError("not a quicksave project, run 'quicksave init' first")
    if name and name.isdigit():
        raise QuicksaveError("snapshot name can't be all digits, it would clash with list numbers")
    if fileobj is not None:
        # buffer the stream so tarfile can seek for compression detection
        src = io.BytesIO(fileobj.read())
    else:
        src = Path(src)
        if not src.is_file():
            raise QuicksaveError(f"archive '{src}' not found")

    files = {}
    newest = 0
    try:
        with _open_archive(src) as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                rel = member.name[2:] if member.name.startswith("./") else member.name
                if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                    raise QuicksaveError(f"unsafe path in archive: {member.name}")
                f = tar.extractfile(member)
                if f is None:
                    continue
                data = f.read()
                digest = _write_blob(store, data)
                files[Path(rel).as_posix()] = {
                    "sha256": digest,
                    "size": len(data),
                    "mode": member.mode & 0o777 or 0o644,
                }
                newest = max(newest, member.mtime)
    except tarfile.TarError as e:
        label = "stdin" if fileobj is not None else src
        raise QuicksaveError(f"can't read '{label}' as a tar archive: {e}")
    if not files:
        raise QuicksaveError("no files in archive")

    snaps = _snapshot_files(store)
    # export stamps members with the snapshot's created_at, so the newest mtime
    # carries the original timestamp through an export/import round trip
    manifest = {"message": message, "name": name, "created_at": newest or time.time(), "files": files}
    body = json.dumps(manifest, sort_keys=True).encode()
    snap_id = _sha256(body)[:12]
    fname = f"{len(snaps):04d}-{snap_id}.json"
    (store / "snapshots" / fname).write_text(json.dumps(manifest, indent=2))
    return snap_id, len(files)


# commands worth a checkpoint before an agent runs them: deletes, overwrites,
# in-place edits and history rewrites. not exhaustive, just the usual footguns.
_RISKY = [
    r"\brm\b",
    r"\bmv\b",
    r"\bdd\b",
    r"\bshred\b",
    r"\btruncate\b",
    r"\bmkfs\.\w+",
    r"\bsed\b[^|]*\s-i",
    r"\bgit\s+reset\b",
    r"\bgit\s+checkout\s+--",
    r"\bgit\s+clean\b",
    r"\bgit\s+restore\b",
    r"\bfind\b.*\s-delete\b",
    r"(?:^|\s)>(?!>)\s*\S",
]
_RISKY_RE = [re.compile(p) for p in _RISKY]


def looks_risky(command):
    return any(r.search(command) for r in _RISKY_RE)


# where each runner keeps its hook config. both Claude Code and Codex nest the
# same {"hooks": {"PreToolUse": [...]}} shape and pass tool_input.command, so
# one 'quicksave hook' handler serves both.
HOOK_TARGETS = {
    "claude": Path(".claude") / "settings.json",
    "codex": Path(".codex") / "hooks.json",
}
HOOK_COMMAND = "quicksave hook"


def install_hook(root, tool):
    rel = HOOK_TARGETS[tool]
    path = Path(root) / rel
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise QuicksaveError(f"{rel.as_posix()} is not valid json, leaving it alone")

    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for group in pre:
        if group.get("matcher") == "Bash":
            handlers = group.setdefault("hooks", [])
            if any(h.get("command") == HOOK_COMMAND for h in handlers):
                return path, False
            handlers.append({"type": "command", "command": HOOK_COMMAND})
            break
    else:
        pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": HOOK_COMMAND}]})

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path, True


def _path_selected(relpath, paths):
    for p in paths:
        if relpath == p or relpath.startswith(p.rstrip("/") + "/"):
            return True
    return False


def resolve_id(root, ref):
    f = _resolve_snapshot(store_path(root), ref)
    return f.stem.partition("-")[2]


RESTORE_BACKUP_PREFIX = "before restore of "


def last_restore_backup(root):
    # the most recent snapshot 'restore' took of the live tree before overwriting
    # it. undo rewinds to this, so a wrong restore can be reverted by name.
    store = store_path(root)
    for f in reversed(_snapshot_files(store)):
        if json.loads(f.read_text()).get("message", "").startswith(RESTORE_BACKUP_PREFIX):
            return f.stem.partition("-")[2]
    return None


def _resolve_snapshot(store, ref):
    if ref is None:
        snaps = _snapshot_files(store)
        if not snaps:
            raise QuicksaveError("no snapshots yet, run 'quicksave save' first")
        return snaps[-1]
    f = _find_snapshot(store, ref)
    if f is None:
        raise QuicksaveError(f"snapshot '{ref}' not found")
    return f


def _selected_files(manifest, paths, ref):
    files = manifest["files"]
    wanted = [Path(p).as_posix() for p in paths] if paths else None
    if wanted:
        files = {rel: meta for rel, meta in files.items() if _path_selected(rel, wanted)}
        if not files:
            raise QuicksaveError(f"no files matching {', '.join(paths)} in snapshot '{ref}'")
    return files, wanted


def restore_plan(root, ref=None, paths=None, clean=False, ignore=DEFAULT_IGNORE):
    # what restore would do, without touching disk
    root = Path(root)
    store = store_path(root)
    f = _resolve_snapshot(store, ref)
    manifest = json.loads(f.read_text())
    files, wanted = _selected_files(manifest, paths, ref)

    created, overwritten, missing = [], [], []
    for relpath, meta in files.items():
        obj = store / "objects" / meta["sha256"][:2] / meta["sha256"][2:]
        if not obj.exists():
            missing.append(relpath)
        elif (root / relpath).exists():
            overwritten.append(relpath)
        else:
            created.append(relpath)

    removed = []
    if clean:
        keep = set(files)
        for rel in iter_files(root, ignore):
            relp = rel.as_posix()
            if relp in keep:
                continue
            if wanted and not _path_selected(relp, wanted):
                continue
            removed.append(relp)

    return {
        "id": f.stem.partition("-")[2],
        "message": manifest.get("message", ""),
        "created": sorted(created),
        "overwritten": sorted(overwritten),
        "removed": sorted(removed),
        "missing": sorted(missing),
    }


def restore(root, ref=None, paths=None, clean=False, ignore=DEFAULT_IGNORE, dest=None):
    root = Path(root)
    store = store_path(root)
    # dest pulls a snapshot aside into another directory without touching the
    # live tree. clean only makes sense against the tree, so it stays off here.
    base = Path(dest) if dest else root
    f = _resolve_snapshot(store, ref)
    manifest = json.loads(f.read_text())
    files, wanted = _selected_files(manifest, paths, ref)

    restored = 0
    for relpath, meta in files.items():
        digest = meta["sha256"]
        obj = store / "objects" / digest[:2] / digest[2:]
        if not obj.exists():
            raise QuicksaveError(f"missing blob {digest} for {relpath}")
        target = base / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(obj.read_bytes())
        try:
            os.chmod(target, meta["mode"])
        except OSError:
            pass
        restored += 1

    removed = 0
    if clean and dest is None:
        keep = set(files)
        for rel in iter_files(root, ignore):
            relp = rel.as_posix()
            if relp in keep:
                continue
            if wanted and not _path_selected(relp, wanted):
                continue
            try:
                (root / relp).unlink()
                removed += 1
            except OSError:
                pass
    return restored, removed, manifest
