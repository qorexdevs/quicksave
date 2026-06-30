import hashlib
import io
import json
import os
import time

import pytest

from quicksave import store


def test_init_creates_layout(tmp_path):
    root, created = store.init(tmp_path)
    assert created is True
    assert (tmp_path / ".quicksave" / "objects").is_dir()
    assert (tmp_path / ".quicksave" / "snapshots").is_dir()
    # second init is a no-op
    _, created2 = store.init(tmp_path)
    assert created2 is False


def test_looks_risky():
    risky = ["rm -rf build", "mv a b", "git reset --hard", "sed -i 's/a/b/' f",
             "perl -i -pe 's/a/b/' f", "perl -pi.bak -e 's/x/y/g' f", "perl -ni -e '...' f",
             "echo x > config.yml", "git clean -fd", "find . -name '*.tmp' -delete",
             "git rm cached.txt", "git stash", "rsync -a --delete src/ dst/",
             "git checkout .", "git checkout ./src", "git checkout -- file.py",
             "git checkout HEAD -- app.py", "git checkout abc123 -- src/",
             "echo x >| config.yml", "echo x | tee config.yml", "git switch -f main",
             "git switch --discard-changes -", "unlink config.yml",
             "git worktree remove ../wt", "python a.py 2>err.log",
             "make &>build.log", "cmd 1>out.txt", "echo a>b", "ls>out.txt",
             "grep x f>results"]
    safe = ["ls -la", "git status", "cat file >> log.txt", "grep -r foo .",
            "perl -ne 'print' f", "perl -pe 's/a/b/' f", "perl -Ilib script.pl",
            "python -m pytest", "echo hi", "rsync -a src/ dst/", "git stashed",
            "echo x | tee -a log.txt", "git switch feature", "committee notes",
            "git worktree list", "git worktree add ../wt", "python a.py 2>&1",
            "git checkout main", "git checkout feature-branch", "git checkout -b feature",
            "python a.py 2>>err.log", "cat a>>b", "wc -l<in"]
    for c in risky:
        assert store.looks_risky(c), c
    for c in safe:
        assert not store.looks_risky(c), c


def test_looks_risky_custom_patterns(monkeypatch):
    assert not store.looks_risky("terraform destroy -auto-approve")
    monkeypatch.setenv("QUICKSAVE_RISKY", "\n".join([r"terraform\s+destroy", r"make\s+clean"]))
    assert store.looks_risky("terraform destroy -auto-approve")
    assert store.looks_risky("make clean")
    assert not store.looks_risky("terraform plan")


def test_looks_risky_skips_invalid_pattern(monkeypatch):
    # a broken regex must not blow up looks_risky, the valid one still applies
    monkeypatch.setenv("QUICKSAVE_RISKY", "make clean\n[unclosed")
    assert store.looks_risky("make clean")
    assert not store.looks_risky("ls")


def test_save_requires_init(tmp_path):
    with pytest.raises(store.QuicksaveError):
        store.save(tmp_path)


def test_save_and_list(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")

    snap_id, n, created = store.save(tmp_path, message="first")
    assert created is True
    assert n == 2
    snaps = store.list_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0]["id"] == snap_id
    assert snaps[0]["message"] == "first"
    assert snaps[0]["count"] == 2
    assert snaps[0]["size"] == len("hello") + len("world")
    assert store.store_size(tmp_path) == len("hello") + len("world")


def test_store_size_dedups_blobs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    store.save(tmp_path)
    # two files share one blob: snapshot size counts both, disk counts it once
    snaps = store.list_snapshots(tmp_path)
    assert snaps[0]["size"] == 2 * len("same")
    assert store.store_size(tmp_path) == len("same")


def test_ignore_rules(tmp_path):
    store.init(tmp_path)
    (tmp_path / "keep.txt").write_text("x")
    for junk in ["node_modules", "__pycache__", ".venv"]:
        d = tmp_path / junk
        d.mkdir()
        (d / "trash").write_text("nope")
    _, n, _ = store.save(tmp_path)
    assert n == 1


def test_quicksaveignore_patterns(tmp_path):
    store.init(tmp_path)
    (tmp_path / "keep.txt").write_text("x")
    (tmp_path / "secret.log").write_text("nope")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run.txt").write_text("nope")
    (tmp_path / ".quicksaveignore").write_text("*.log\nlogs/\n")
    _, n, _ = store.save(tmp_path)
    # keep.txt and .quicksaveignore itself remain
    assert n == 2


def test_gitignore_is_respected(tmp_path):
    store.init(tmp_path)
    (tmp_path / "main.py").write_text("x")
    (tmp_path / "out.tmp").write_text("nope")
    (tmp_path / ".gitignore").write_text("# build junk\n*.tmp\n")
    files = {p.as_posix() for p in store.iter_files(tmp_path)}
    assert "main.py" in files
    assert ".gitignore" in files
    assert "out.tmp" not in files


def test_negation_line_does_not_ignore(tmp_path):
    store.init(tmp_path)
    (tmp_path / "keep.log").write_text("important")
    (tmp_path / ".gitignore").write_text("!keep.log\n")
    files = {p.as_posix() for p in store.iter_files(tmp_path)}
    # a '!' line must not flip into an ignore rule for the same name
    assert "keep.log" in files


def test_negation_reincludes_gitignored_file(tmp_path):
    store.init(tmp_path)
    (tmp_path / ".env").write_text("API_KEY=secret")
    (tmp_path / "out.tmp").write_text("nope")
    # git ignores .env, but we still want quicksave to capture it
    (tmp_path / ".gitignore").write_text(".env\n*.tmp\n")
    (tmp_path / ".quicksaveignore").write_text("!.env\n")
    files = {p.as_posix() for p in store.iter_files(tmp_path)}
    assert ".env" in files
    assert "out.tmp" not in files


def test_negation_reincludes_glob_match(tmp_path):
    store.init(tmp_path)
    (tmp_path / "debug.log").write_text("noise")
    (tmp_path / "audit.log").write_text("keep me")
    (tmp_path / ".quicksaveignore").write_text("*.log\n!audit.log\n")
    files = {p.as_posix() for p in store.iter_files(tmp_path)}
    assert "audit.log" in files
    assert "debug.log" not in files


def test_check_ignore_reports_rule_and_source(tmp_path):
    store.init(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n*.log\n")
    (tmp_path / ".quicksaveignore").write_text("!.env\n")

    kept = store.check_ignore(tmp_path, "main.py")
    assert kept["ignored"] is False and kept["rule"] is None

    logged = store.check_ignore(tmp_path, "run.log")
    assert logged["ignored"] is True
    assert logged["source"] == ".gitignore" and logged["line"] == 2

    # .quicksaveignore runs last, so '!.env' wins over the .gitignore ignore
    env = store.check_ignore(tmp_path, ".env")
    assert env["ignored"] is False
    assert env["source"] == ".quicksaveignore" and env["negated"] is True

    # built-in dir names report as such and can't be un-ignored
    built = store.check_ignore(tmp_path, "node_modules/pkg/index.js")
    assert built["ignored"] is True and built["source"] == "built-in"


def test_dedup_same_content(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    store.save(tmp_path)
    objects = list((tmp_path / ".quicksave" / "objects").rglob("*"))
    blobs = [p for p in objects if p.is_file()]
    assert len(blobs) == 1


def test_restore_after_delete(tmp_path):
    store.init(tmp_path)
    (tmp_path / "code.py").write_text("print('keep me')")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.txt").write_text("payload")
    snap_id, _, _ = store.save(tmp_path, message="before rm")

    # simulate an agent nuking the tree
    os.remove(tmp_path / "code.py")
    os.remove(tmp_path / "data" / "x.txt")
    assert not (tmp_path / "code.py").exists()

    n, _, _ = store.restore(tmp_path, snap_id)
    assert n == 2
    assert (tmp_path / "code.py").read_text() == "print('keep me')"
    assert (tmp_path / "data" / "x.txt").read_text() == "payload"


def test_restore_single_file(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")
    snap_id, _, _ = store.save(tmp_path)
    os.remove(tmp_path / "a.txt")
    os.remove(tmp_path / "b.txt")

    n, _, _ = store.restore(tmp_path, snap_id, ["a.txt"])
    assert n == 1
    assert (tmp_path / "a.txt").read_text() == "aaa"
    assert not (tmp_path / "b.txt").exists()


def test_restore_directory_prefix(tmp_path):
    store.init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x")
    (tmp_path / "src" / "y.py").write_text("y")
    (tmp_path / "top.txt").write_text("t")
    snap_id, _, _ = store.save(tmp_path)
    os.remove(tmp_path / "src" / "x.py")
    os.remove(tmp_path / "src" / "y.py")
    os.remove(tmp_path / "top.txt")

    n, _, _ = store.restore(tmp_path, snap_id, ["src"])
    assert n == 2
    assert (tmp_path / "src" / "x.py").read_text() == "x"
    assert not (tmp_path / "top.txt").exists()


def test_restore_glob(tmp_path):
    store.init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x")
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "notes.txt").write_text("t")
    snap_id, _, _ = store.save(tmp_path)
    os.remove(tmp_path / "src" / "x.py")
    os.remove(tmp_path / "a.py")
    os.remove(tmp_path / "notes.txt")

    n, _, _ = store.restore(tmp_path, snap_id, ["*.py"])
    assert n == 2
    assert (tmp_path / "a.py").read_text() == "a"
    assert (tmp_path / "src" / "x.py").read_text() == "x"
    assert not (tmp_path / "notes.txt").exists()


def test_restore_no_match_raises(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.restore(tmp_path, "0", ["nope.txt"])


def test_restore_by_number(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("v2")
    store.save(tmp_path)

    store.restore(tmp_path, "0")
    assert (tmp_path / "f.txt").read_text() == "v1"


def test_restore_latest_by_default(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("v2")
    store.save(tmp_path)

    (tmp_path / "f.txt").unlink()
    store.restore(tmp_path)
    assert (tmp_path / "f.txt").read_text() == "v2"


def test_restore_latest_without_snapshots_raises(tmp_path):
    store.init(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.restore(tmp_path)


def test_restore_missing_ref(tmp_path):
    store.init(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.restore(tmp_path, "nope")


def test_show_returns_blob_bytes(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    store.save(tmp_path)
    (tmp_path / "a.txt").write_text("v2")
    store.save(tmp_path)
    assert store.show(tmp_path, "0", "a.txt") == b"v1"
    assert store.show(tmp_path, "1", "a.txt") == b"v2"


def test_show_missing_file_raises(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.show(tmp_path, "0", "nope.txt")


def test_show_without_ref_uses_newest_holder(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    (tmp_path / "b.txt").write_text("keep")
    store.save(tmp_path)
    (tmp_path / "a.txt").write_text("v2")
    store.save(tmp_path)
    # a.txt is gone from the tree and from the latest snapshot, but show with no
    # ref still finds its most recent saved content
    (tmp_path / "a.txt").unlink()
    store.save(tmp_path)
    assert store.show(tmp_path, None, "a.txt") == b"v2"
    with pytest.raises(store.QuicksaveError):
        store.show(tmp_path, None, "never.txt")


def test_export_writes_tar(tmp_path):
    import tarfile

    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    store.save(tmp_path)

    dest = tmp_path / "out.tar.gz"
    n, out = store.export_snapshot(tmp_path, None, dest)
    assert n == 2
    assert out == dest
    with tarfile.open(dest) as tar:
        names = sorted(tar.getnames())
        assert names == ["a.txt", "sub/b.txt"]
        assert tar.extractfile("a.txt").read() == b"hello"


def test_export_respects_paths(tmp_path):
    import tarfile

    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    store.save(tmp_path)

    dest = tmp_path / "out.tar"
    n, _ = store.export_snapshot(tmp_path, None, dest, paths=["a.txt"])
    assert n == 1
    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["a.txt"]


def test_export_missing_blob_raises(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    objects = tmp_path / ".quicksave" / "objects"
    for d in objects.iterdir():
        for f in d.iterdir():
            f.unlink()
    with pytest.raises(store.QuicksaveError):
        store.export_snapshot(tmp_path, None, tmp_path / "out.tar")


def test_import_roundtrips_an_export(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    store.save(tmp_path)

    dest = tmp_path / "out.tar.gz"
    store.export_snapshot(tmp_path, None, dest)

    snap_id, n = store.import_archive(tmp_path, dest, message="from tar", name="restored")
    assert n == 2
    f = store._resolve_snapshot(store.store_path(tmp_path), snap_id)
    m = json.loads(f.read_text())
    assert sorted(m["files"]) == ["a.txt", "sub/b.txt"]
    assert m["name"] == "restored"
    os.remove(tmp_path / "a.txt")
    store.restore(tmp_path, snap_id)
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_import_dry_run_previews_without_writing(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    store.save(tmp_path, name="golden")

    dest = tmp_path / "out.tar"
    store.export_snapshot(tmp_path, None, dest)

    sp = store.store_path(tmp_path)
    snaps_before = sorted((sp / "snapshots").glob("*.json"))
    blobs_before = sum(1 for _ in (sp / "blobs").rglob("*") if _.is_file())

    r = store.import_archive(tmp_path, dest, dry_run=True)
    assert r["dry_run"] is True
    assert r["files"] == 2
    assert r["bytes"] == len("hello") + len("world")
    assert r["name"] == "golden"
    assert r["paths"] == ["a.txt", "sub/b.txt"]

    # nothing landed: no new snapshot manifest, no new blobs
    assert sorted((sp / "snapshots").glob("*.json")) == snaps_before
    assert sum(1 for _ in (sp / "blobs").rglob("*") if _.is_file()) == blobs_before


def test_export_import_keeps_the_name(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    store.save(tmp_path, name="golden")

    dest = tmp_path / "out.tar"
    store.export_snapshot(tmp_path, None, dest)
    snap_id, _ = store.import_archive(tmp_path, dest)

    f = store._resolve_snapshot(store.store_path(tmp_path), snap_id)
    m = json.loads(f.read_text())
    assert m["name"] == "golden"
    # the carried name must not show up as a restorable file
    assert sorted(m["files"]) == ["a.txt"]


def test_import_name_overrides_the_carried_one(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    store.save(tmp_path, name="golden")

    dest = tmp_path / "out.tar"
    store.export_snapshot(tmp_path, None, dest)
    snap_id, _ = store.import_archive(tmp_path, dest, name="override")

    f = store._resolve_snapshot(store.store_path(tmp_path), snap_id)
    m = json.loads(f.read_text())
    assert m["name"] == "override"


def test_import_rejects_path_escape(tmp_path):
    import tarfile

    store.init(tmp_path)
    bad = tmp_path / "evil.tar"
    with tarfile.open(bad, "w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        data = b"x"
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(store.QuicksaveError):
        store.import_archive(tmp_path, bad)


def test_import_empty_archive_raises(tmp_path):
    import tarfile

    store.init(tmp_path)
    empty = tmp_path / "empty.tar"
    with tarfile.open(empty, "w"):
        pass
    with pytest.raises(store.QuicksaveError):
        store.import_archive(tmp_path, empty)


def test_import_not_a_tar_raises(tmp_path):
    store.init(tmp_path)
    bogus = tmp_path / "bogus.tar"
    bogus.write_text("plain text, not a tar")
    with pytest.raises(store.QuicksaveError):
        store.import_archive(tmp_path, bogus)


def test_import_keeps_export_timestamp(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    store.save(tmp_path)
    orig = json.loads(store._snapshot_files(store.store_path(tmp_path))[0].read_text())

    dest = tmp_path / "out.tar"
    store.export_snapshot(tmp_path, None, dest)
    snap_id, _ = store.import_archive(tmp_path, dest)

    f = store._resolve_snapshot(store.store_path(tmp_path), snap_id)
    m = json.loads(f.read_text())
    # export stamps members with the snapshot's created_at, so the round trip
    # keeps the original timestamp instead of the import time
    assert m["created_at"] == int(orig["created_at"])


def test_export_import_roundtrips_through_a_stream(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("world")
    store.save(tmp_path)

    buf = io.BytesIO()
    n, where = store.export_snapshot(tmp_path, None, "-", out=buf)
    assert n == 2
    assert where == "-"

    buf.seek(0)
    snap_id, got = store.import_archive(tmp_path, "-", name="piped", fileobj=buf)
    assert got == 2
    f = store._resolve_snapshot(store.store_path(tmp_path), snap_id)
    m = json.loads(f.read_text())
    assert sorted(m["files"]) == ["a.txt", "sub/b.txt"]
    assert m["name"] == "piped"
    os.remove(tmp_path / "a.txt")
    store.restore(tmp_path, snap_id)
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_gzip_stream_is_compressed_and_roundtrips(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    store.save(tmp_path)

    buf = io.BytesIO()
    store.export_snapshot(tmp_path, None, "-", out=buf, gzip=True)
    assert buf.getvalue()[:2] == b"\x1f\x8b"  # gzip magic

    buf.seek(0)
    snap_id, got = store.import_archive(tmp_path, "-", fileobj=buf)
    assert got == 1
    os.remove(tmp_path / "a.txt")
    store.restore(tmp_path, snap_id)
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_gzip_path_compresses_without_gz_suffix(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    store.save(tmp_path)

    dest = tmp_path / "out.tar"
    store.export_snapshot(tmp_path, None, dest, gzip=True)
    assert dest.read_bytes()[:2] == b"\x1f\x8b"


def test_import_from_stream_rejects_non_tar(tmp_path):
    store.init(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.import_archive(tmp_path, "-", fileobj=io.BytesIO(b"not a tar at all"))


def test_diff_between_snapshots(tmp_path):
    store.init(tmp_path)
    (tmp_path / "keep.txt").write_text("same")
    (tmp_path / "gone.txt").write_text("bye")
    (tmp_path / "edit.txt").write_text("v1")
    store.save(tmp_path)

    os.remove(tmp_path / "gone.txt")
    (tmp_path / "edit.txt").write_text("v2")
    (tmp_path / "new.txt").write_text("hi")
    store.save(tmp_path)

    d = store.diff(tmp_path, "0", "1")
    assert d["added"] == ["new.txt"]
    assert d["removed"] == ["gone.txt"]
    assert d["modified"] == ["edit.txt"]


def test_diff_identical_is_empty(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    store.save(tmp_path, force=True)
    d = store.diff(tmp_path, "0", "1")
    assert d == {"added": [], "removed": [], "modified": []}


def test_save_skips_when_unchanged(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    id0, _, created0 = store.save(tmp_path)
    assert created0 is True
    id1, _, created1 = store.save(tmp_path)
    assert created1 is False
    assert id1 == id0
    assert len(store.list_snapshots(tmp_path)) == 1


def test_save_force_keeps_unchanged_dup(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    _, _, created = store.save(tmp_path, force=True)
    assert created is True
    assert len(store.list_snapshots(tmp_path)) == 2


def test_save_resumes_after_change(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    store.save(tmp_path)  # skipped
    (tmp_path / "a.txt").write_text("y")
    _, _, created = store.save(tmp_path)
    assert created is True
    assert len(store.list_snapshots(tmp_path)) == 2


def test_diff_missing_ref(tmp_path):
    store.init(tmp_path)
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.diff(tmp_path, "0", "nope")


def test_find_snapshot_number_beats_id_prefix(tmp_path):
    # snapshot 0's id starts with "1"; resolving ref "1" must hit seq 1, not it
    store.init(tmp_path)
    snaps = tmp_path / ".quicksave" / "snapshots"
    snaps.joinpath("0000-1aaaaaaaaaaa.json").write_text('{"files": {"old": 1}}')
    snaps.joinpath("0001-bbbbbbbbbbbb.json").write_text('{"files": {"new": 1}}')
    f = store._find_snapshot(store.store_path(tmp_path), "1")
    assert f.stem == "0001-bbbbbbbbbbbb"


def test_relative_refs_count_back_from_newest(tmp_path):
    store.init(tmp_path)
    ids = []
    for v in ("a", "b", "c"):
        (tmp_path / "f.txt").write_text(v)
        sid, _, _ = store.save(tmp_path)
        ids.append(sid)
    assert store.resolve_id(tmp_path, "latest") == ids[-1]
    assert store.resolve_id(tmp_path, "latest~1") == ids[-2]
    assert store.resolve_id(tmp_path, "~2") == ids[-3]


def test_at_ref_picks_tree_as_of_a_time(tmp_path):
    import json
    import time
    store.init(tmp_path)
    ids = []
    for v in ("a", "b", "c"):
        (tmp_path / "f.txt").write_text(v)
        sid, _, _ = store.save(tmp_path)
        ids.append(sid)
    # stamp them at known ages: 3h, 2h, 1h ago
    now = time.time()
    snaps = sorted((store.store_path(tmp_path) / "snapshots").glob("*.json"))
    for f, hours in zip(snaps, (3, 2, 1)):
        m = json.loads(f.read_text())
        m["created_at"] = now - hours * 3600
        f.write_text(json.dumps(m))
    # newest snapshot at or before 90m ago is the 2h-old one
    assert store.resolve_id(tmp_path, "@90m") == ids[1]
    assert store.resolve_id(tmp_path, "@30m") == ids[2]
    # nothing is that old
    with pytest.raises(store.QuicksaveError):
        store.resolve_id(tmp_path, "@5h")


def test_relative_ref_out_of_range(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.resolve_id(tmp_path, "latest~5")


def test_diff_with_relative_refs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("v1")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("v2")
    store.save(tmp_path)
    d = store.diff(tmp_path, "latest~1", "latest")
    assert d["modified"] == ["f.txt"]


def test_status_against_latest(tmp_path):
    store.init(tmp_path)
    (tmp_path / "keep.txt").write_text("same")
    (tmp_path / "gone.txt").write_text("bye")
    (tmp_path / "edit.txt").write_text("v1")
    store.save(tmp_path)

    os.remove(tmp_path / "gone.txt")
    (tmp_path / "edit.txt").write_text("v2")
    (tmp_path / "new.txt").write_text("hi")

    s = store.status(tmp_path)
    assert s["added"] == ["new.txt"]
    assert s["removed"] == ["gone.txt"]
    assert s["modified"] == ["edit.txt"]


def test_status_clean_tree(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    s = store.status(tmp_path)
    assert s == {"seq": 0, "id": s["id"], "added": [], "removed": [], "modified": []}


def test_status_no_snapshots_raises(tmp_path):
    store.init(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.status(tmp_path)


def test_restore_clean_removes_new_files(tmp_path):
    store.init(tmp_path)
    (tmp_path / "code.py").write_text("v1")
    snap_id, _, _ = store.save(tmp_path)

    (tmp_path / "code.py").write_text("garbage from agent")
    (tmp_path / "junk.log").write_text("noise")

    restored, removed, _ = store.restore(tmp_path, snap_id, clean=True)
    assert restored == 1
    assert removed == 1
    assert (tmp_path / "code.py").read_text() == "v1"
    assert not (tmp_path / "junk.log").exists()


def test_restore_clean_scoped_to_paths(tmp_path):
    store.init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    (tmp_path / "top.txt").write_text("t")
    snap_id, _, _ = store.save(tmp_path)

    (tmp_path / "src" / "extra.py").write_text("junk")
    (tmp_path / "other.txt").write_text("leave me")

    _, removed, _ = store.restore(tmp_path, snap_id, ["src"], clean=True)
    assert removed == 1
    assert not (tmp_path / "src" / "extra.py").exists()
    assert (tmp_path / "other.txt").read_text() == "leave me"


def test_restore_clean_prunes_emptied_dirs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "code.py").write_text("v1")
    snap_id, _, _ = store.save(tmp_path)

    # an agent drops a whole subtree the snapshot never had
    (tmp_path / "junk" / "deep").mkdir(parents=True)
    (tmp_path / "junk" / "a.log").write_text("noise")
    (tmp_path / "junk" / "deep" / "b.log").write_text("more")

    _, removed, _ = store.restore(tmp_path, snap_id, clean=True)
    assert removed == 2
    # files gone and the now-empty dirs that held them are gone too
    assert not (tmp_path / "junk").exists()


def test_restore_clean_keeps_dir_with_ignored_file(tmp_path):
    store.init(tmp_path)
    (tmp_path / "code.py").write_text("v1")
    (tmp_path / ".gitignore").write_text("*.log\n")
    snap_id, _, _ = store.save(tmp_path)

    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "tracked.txt").write_text("junk")
    (tmp_path / "logs" / "skip.log").write_text("ignored, stays")

    _, removed, _ = store.restore(tmp_path, snap_id, clean=True)
    assert removed == 1
    # the ignored file was never touched, so its dir survives
    assert (tmp_path / "logs" / "skip.log").exists()
    assert not (tmp_path / "logs" / "tracked.txt").exists()


def test_restore_plan_reports_changes_without_touching_disk(tmp_path):
    store.init(tmp_path)
    (tmp_path / "code.py").write_text("v1")
    (tmp_path / "gone.txt").write_text("gone")
    snap_id, _, _ = store.save(tmp_path)

    (tmp_path / "code.py").write_text("garbage")
    os.remove(tmp_path / "gone.txt")
    (tmp_path / "junk.log").write_text("noise")

    p = store.restore_plan(tmp_path, snap_id, clean=True)
    assert p["created"] == ["gone.txt"]
    assert p["overwritten"] == ["code.py"]
    assert p["removed"] == ["junk.log"]
    # nothing on disk changed
    assert (tmp_path / "code.py").read_text() == "garbage"
    assert (tmp_path / "junk.log").exists()


def test_restore_plan_missing_blob(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    snap_id, _, _ = store.save(tmp_path)
    for obj in (tmp_path / ".quicksave" / "objects").rglob("*"):
        if obj.is_file():
            obj.unlink()

    p = store.restore_plan(tmp_path, snap_id)
    assert p["missing"] == ["a.txt"]


def test_gc_prunes_old_snapshots_and_blobs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")
    (tmp_path / "f.txt").write_text("three")
    store.save(tmp_path, message="s2")

    objects = tmp_path / ".quicksave" / "objects"
    before = sum(1 for _ in store._iter_blobs(objects.parent))
    assert before == 3

    r = store.gc(tmp_path, keep=1)
    assert len(r["pruned"]) == 2
    assert r["blobs"] == 2
    snaps = store.list_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0]["message"] == "s2"
    after = sum(1 for _ in store._iter_blobs(tmp_path / ".quicksave"))
    assert after == 1


def test_gc_drops_a_specific_snapshot(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")
    (tmp_path / "f.txt").write_text("three")
    store.save(tmp_path, message="s2")

    r = store.gc(tmp_path, refs=["1"])
    assert len(r["pruned"]) == 1
    msgs = [s["message"] for s in store.list_snapshots(tmp_path)]
    assert msgs == ["s0", "s2"]
    assert r["blobs"] == 1


def test_drop_removes_one_snapshot_and_its_blobs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")
    (tmp_path / "f.txt").write_text("three")
    store.save(tmp_path, message="s2")

    r = store.drop(tmp_path, "1")
    assert r["blobs"] == 1
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["s0", "s2"]


def test_drop_removes_several_snapshots_at_once(tmp_path):
    store.init(tmp_path)
    for text in ("one", "two", "three", "four"):
        (tmp_path / "f.txt").write_text(text)
        store.save(tmp_path, message=text)

    r = store.drop(tmp_path, ["1", "2"])
    assert r["blobs"] == 2
    assert len(r["dropped"]) == 2
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["one", "four"]


def test_drop_dedupes_repeated_refs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path, message="a")
    (tmp_path / "f.txt").write_text("b")
    store.save(tmp_path, message="b")

    r = store.drop(tmp_path, ["0", "0"])
    assert len(r["dropped"]) == 1
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["b"]


def test_drop_dry_run_keeps_everything(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("b")
    store.save(tmp_path)

    before = store.store_size(tmp_path)
    r = store.drop(tmp_path, "0", dry_run=True)
    assert r["blobs"] == 1 and r["bytes"] > 0
    assert len(store.list_snapshots(tmp_path)) == 2
    assert store.store_size(tmp_path) == before


def test_drop_refuses_pinned_without_force(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    store.set_pinned(tmp_path, "0", True)
    with pytest.raises(store.QuicksaveError):
        store.drop(tmp_path, "0")
    store.drop(tmp_path, "0", force=True)
    assert store.list_snapshots(tmp_path) == []


def test_drop_unknown_ref_raises(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.drop(tmp_path, "nope")


def test_gc_unknown_ref_raises(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    with pytest.raises(store.QuicksaveError):
        store.gc(tmp_path, refs=["nope"])


def test_gc_dry_run_keeps_everything(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("b")
    store.save(tmp_path)

    r = store.gc(tmp_path, keep=1, dry_run=True)
    assert len(r["pruned"]) == 1
    assert r["blobs"] == 1
    assert len(store.list_snapshots(tmp_path)) == 2


def test_gc_reports_freed_bytes(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("x" * 4096)
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("y" * 8192)
    store.save(tmp_path, message="s1")

    before = store.store_size(tmp_path)
    r = store.gc(tmp_path, keep=1)
    assert r["bytes"] > 0
    assert before - store.store_size(tmp_path) == r["bytes"]


def test_gc_dry_run_freed_bytes_keeps_blobs(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a" * 2048)
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("b" * 2048)
    store.save(tmp_path)

    before = store.store_size(tmp_path)
    r = store.gc(tmp_path, keep=1, dry_run=True)
    assert r["bytes"] > 0
    assert store.store_size(tmp_path) == before


def test_gc_keep_spares_pinned(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")
    (tmp_path / "f.txt").write_text("three")
    store.save(tmp_path, message="s2")

    snap_id, was = store.set_pinned(tmp_path, "0", True)
    assert was is False

    r = store.gc(tmp_path, keep=1)
    msgs = [s["message"] for s in store.list_snapshots(tmp_path)]
    assert msgs == ["s0", "s2"]
    assert "s0" not in [p for p in r["pruned"]]


def _age_snapshot(tmp_path, seq, seconds):
    # rewrite a snapshot's created_at so it looks `seconds` old, for gc --older-than
    for f in store._snapshot_files(store.store_path(tmp_path)):
        m = json.loads(f.read_text())
        if int(f.stem.partition("-")[0]) == seq:
            m["created_at"] = time.time() - seconds
            f.write_text(json.dumps(m))
            return
    raise AssertionError(f"snapshot {seq} not found")


def test_gc_older_than_drops_aged_snapshots(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")

    _age_snapshot(tmp_path, 0, 8 * 86400)
    r = store.gc(tmp_path, older_than=store.parse_duration("7d"))
    msgs = [s["message"] for s in store.list_snapshots(tmp_path)]
    assert msgs == ["s1"]
    assert r["pruned"] and r["blobs"] == 1


def test_gc_keep_within_spares_recent(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")

    _age_snapshot(tmp_path, 0, 3 * 3600)
    r = store.gc(tmp_path, keep=1, keep_within=store.parse_duration("1h"))
    msgs = [s["message"] for s in store.list_snapshots(tmp_path)]
    assert msgs == ["s1"]
    assert len(r["pruned"]) == 1


def test_gc_keep_within_keeps_all_inside_window(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path, message="s1")

    r = store.gc(tmp_path, keep=1, keep_within=store.parse_duration("1h"))
    assert r["pruned"] == []
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["s0", "s1"]


def test_gc_older_than_spares_pinned(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path, message="s0")
    store.set_pinned(tmp_path, "0", True)
    _age_snapshot(tmp_path, 0, 30 * 86400)

    r = store.gc(tmp_path, older_than=store.parse_duration("1d"))
    assert r["pruned"] == []
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["s0"]


def test_parse_duration_forms():
    assert store.parse_duration("90s") == 90
    assert store.parse_duration("30m") == 1800
    assert store.parse_duration("12h") == 43200
    assert store.parse_duration("7d") == 604800
    assert store.parse_duration("2w") == 1209600
    assert store.parse_duration("3600") == 3600
    with pytest.raises(store.QuicksaveError):
        store.parse_duration("soon")


def test_parse_duration_absolute_date():
    from datetime import datetime

    past = "2020-01-01"
    ago = store.parse_duration(past)
    expected = time.time() - datetime.fromisoformat(past).timestamp()
    assert abs(ago - expected) < 5
    # a date and a duration both resolve to "seconds ago", date is much larger
    assert store.parse_duration("2020-01-01T12:00") > store.parse_duration("1h")


def test_pin_shows_in_list_and_unpin_clears(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path)
    store.set_pinned(tmp_path, "0", True)
    assert store.list_snapshots(tmp_path)[0]["pinned"] is True

    _, was = store.set_pinned(tmp_path, "0", False)
    assert was is True
    assert store.list_snapshots(tmp_path)[0]["pinned"] is False


def test_pinned_still_drops_on_explicit_ref(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("a")
    store.save(tmp_path, message="s0")
    (tmp_path / "f.txt").write_text("b")
    store.save(tmp_path, message="s1")
    store.set_pinned(tmp_path, "0", True)

    store.gc(tmp_path, refs=["0"])
    msgs = [s["message"] for s in store.list_snapshots(tmp_path)]
    assert msgs == ["s1"]


def test_verify_clean_store(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("two")
    store.save(tmp_path)

    r = store.verify(tmp_path)
    assert r["ok"]
    assert r["blobs"] == 2
    assert r["corrupt"] == []
    assert r["missing"] == []


def test_verify_detects_corrupt_blob(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello")
    store.save(tmp_path)

    obj, digest = next(store._iter_blobs(tmp_path / ".quicksave"))
    obj.write_bytes(b"tampered")

    r = store.verify(tmp_path)
    assert not r["ok"]
    assert r["corrupt"] == [digest]


def test_verify_detects_missing_blob(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello")
    store.save(tmp_path)

    obj, _ = next(store._iter_blobs(tmp_path / ".quicksave"))
    obj.unlink()

    r = store.verify(tmp_path)
    assert not r["ok"]
    assert len(r["missing"]) == 1
    assert r["missing"][0]["path"] == "f.txt"


def test_repair_clean_store_is_noop(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("one")
    store.save(tmp_path)

    r = store.repair(tmp_path)
    assert r["dropped"] == []
    assert r["corrupt_blobs"] == 0
    assert r["blobs"] == 0


def test_repair_drops_snapshot_with_missing_blob(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("keep")
    store.save(tmp_path)
    (tmp_path / "f.txt").write_text("broken")
    store.save(tmp_path)

    # nuke the blob the second snapshot needs, leaving the first one intact
    broken = hashlib.sha256(b"broken").hexdigest()
    objects = tmp_path / ".quicksave" / "objects"
    (objects / broken[:2] / broken[2:]).unlink()

    r = store.repair(tmp_path)
    assert len(r["dropped"]) == 1
    assert store.verify(tmp_path)["ok"]
    assert len(store.list_snapshots(tmp_path)) == 1


def test_repair_dry_run_touches_nothing(tmp_path):
    store.init(tmp_path)
    (tmp_path / "f.txt").write_text("hello")
    store.save(tmp_path)
    obj, _ = next(store._iter_blobs(tmp_path / ".quicksave"))
    obj.unlink()

    r = store.repair(tmp_path, dry_run=True)
    assert len(r["dropped"]) == 1
    assert r["dry_run"]
    # snapshot manifest still on disk after a dry run
    assert len(store.list_snapshots(tmp_path)) == 1


def test_save_with_name_and_restore_by_name(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    store.save(tmp_path, name="before-refactor")
    (tmp_path / "a.txt").write_text("v2")
    store.save(tmp_path, message="second")

    snaps = store.list_snapshots(tmp_path)
    assert snaps[0]["name"] == "before-refactor"
    assert snaps[1]["name"] == ""

    store.restore(tmp_path, "before-refactor")
    assert (tmp_path / "a.txt").read_text() == "v1"


def test_numeric_name_rejected(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    with pytest.raises(store.QuicksaveError):
        store.save(tmp_path, name="42")


def test_name_lands_on_unchanged_snapshot(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path)
    # nothing changed, but the name should still attach to the existing snapshot
    _, _, created = store.save(tmp_path, name="keep")
    assert created is False
    assert store.list_snapshots(tmp_path)[0]["name"] == "keep"
    assert store._find_snapshot(store.store_path(tmp_path), "keep") is not None


def test_set_name_labels_existing_snapshot(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    snap_id, _, _ = store.save(tmp_path)
    rid, old = store.set_name(tmp_path, "0", "good-state")
    assert rid == snap_id
    assert old == ""
    assert store.list_snapshots(tmp_path)[0]["name"] == "good-state"
    # resolvable by the new name, and renaming reports the previous one
    _, prev = store.set_name(tmp_path, "good-state", "better")
    assert prev == "good-state"
    assert store._find_snapshot(store.store_path(tmp_path), "better") is not None


def test_set_name_clears_and_rejects_digits(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    store.save(tmp_path, name="tmp")
    _, old = store.set_name(tmp_path, "0", "")
    assert old == "tmp"
    assert store.list_snapshots(tmp_path)[0]["name"] == ""
    with pytest.raises(store.QuicksaveError):
        store.set_name(tmp_path, "0", "42")


def test_reused_name_resolves_to_latest(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    store.save(tmp_path, name="checkpoint")
    (tmp_path / "a.txt").write_text("v2")
    store.save(tmp_path, name="checkpoint")
    f = store._find_snapshot(store.store_path(tmp_path), "checkpoint")
    assert f.stem.startswith("0001-")


def test_find_file_lists_matching_snapshots_newest_first(tmp_path):
    store.init(tmp_path)
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "foo.py").write_text("v1")
    store.save(tmp_path, message="first")
    (sub / "foo.py").write_text("v2")
    store.save(tmp_path, message="second")

    hits = store.find_file(tmp_path, "foo.py")
    assert len(hits) == 2
    assert hits[0]["seq"] == 1 and hits[0]["message"] == "second"
    assert hits[1]["seq"] == 0
    assert hits[0]["files"][0]["path"] == "src/foo.py"


def test_find_file_matches_directory_prefix_and_missing(tmp_path):
    store.init(tmp_path)
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    store.save(tmp_path)

    by_dir = store.find_file(tmp_path, "src")
    assert by_dir[0]["files"][0]["path"] == "src/a.txt"
    assert store.find_file(tmp_path, "nope.txt") == []


def test_stats_counts_and_dedup(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    store.save(tmp_path, message="first")
    (tmp_path / "c.txt").write_text("other")
    store.save(tmp_path, message="second")

    s = store.stats(tmp_path)
    assert s["snapshots"] == 2
    # "same" dedups to one blob, "c.txt" adds another -> 2 unique blobs
    assert s["blobs"] == 2
    # logical counts every file in every snapshot, disk counts each blob once
    assert s["logical_bytes"] > s["disk_bytes"]
    assert s["disk_bytes"] == store.store_size(tmp_path)
    assert s["saved_bytes"] == s["logical_bytes"] - s["disk_bytes"]
    assert s["ratio"] == s["logical_bytes"] / s["disk_bytes"]
    assert s["first"] <= s["last"]


def test_stats_top_snapshots_unique_bytes(tmp_path):
    store.init(tmp_path)
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    store.save(tmp_path, message="first", name="base")
    (tmp_path / "c.txt").write_text("other")
    store.save(tmp_path, message="second", name="extra")

    s = store.stats(tmp_path, top=5)
    by_name = {r["name"]: r for r in s["top_snapshots"]}
    assert by_name["base"]["unique_bytes"] == 0
    assert by_name["extra"]["unique_bytes"] == len("other")
    assert s["top_snapshots"][0]["name"] == "extra"
    assert s["top_snapshots"][0]["unique_bytes"] >= s["top_snapshots"][1]["unique_bytes"]

    one = store.stats(tmp_path, top=1)
    assert len(one["top_snapshots"]) == 1
    assert one["top_snapshots"][0]["name"] == "extra"

    assert store.stats(tmp_path, top=0)["top_snapshots"] == []
    assert store.stats(tmp_path, top=-1)["top_snapshots"] == []

    root = tmp_path / "tie"
    root.mkdir()
    store.init(root)
    for text in ("one", "two", "three"):
        (root / "f.txt").write_text(text)
        store.save(root, message=text)
    tied = store.stats(root, top=3)["top_snapshots"]
    assert len(tied) == 3
    assert tied[0]["seq"] > tied[1]["seq"] > tied[2]["seq"]


def test_stats_ratio_when_empty(tmp_path):
    store.init(tmp_path)
    s = store.stats(tmp_path)
    assert s["disk_bytes"] == 0
    assert s["saved_bytes"] == 0
    assert s["ratio"] == 1.0


def test_stats_requires_init(tmp_path):
    with pytest.raises(store.QuicksaveError):
        store.stats(tmp_path)
