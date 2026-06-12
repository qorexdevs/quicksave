import hashlib
import io
import json


from quicksave.cli import main

import argparse

from quicksave import store
from quicksave.cli import cmd_list, _relative_time



def test_cli_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")

    main(["init"])
    main(["save", "-m", "wip"])
    main(["list"])
    out = capsys.readouterr().out
    assert "wip" in out

    (tmp_path / "note.md").unlink()
    main(["restore", "0"])
    assert (tmp_path / "note.md").read_text() == "draft"


def test_cli_status_and_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])

    (tmp_path / "junk.txt").write_text("noise")
    main(["status"])
    assert "junk.txt" in capsys.readouterr().out

    main(["restore", "0", "--clean", "--no-backup"])
    assert not (tmp_path / "junk.txt").exists()
    main(["status"])
    assert "clean" in capsys.readouterr().out


def test_restore_backs_up_current_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("v2")
    main(["restore", "0"])
    assert (tmp_path / "note.md").read_text() == "v1"

    # the pre-restore "v2" tree is now its own snapshot, so a wrong restore is undoable
    snaps = list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    assert len(snaps) == 2
    main(["restore"])
    assert (tmp_path / "note.md").read_text() == "v2"


def test_name_command_labels_and_resolves(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["name", "0", "good-build"])
    assert "good-build" in capsys.readouterr().out

    # the name now resolves in list and restore
    main(["list"])
    assert "good-build" in capsys.readouterr().out
    (tmp_path / "a.txt").write_text("v2")
    main(["restore", "good-build", "--no-backup"])
    assert (tmp_path / "a.txt").read_text() == "v1"


def test_undo_reverts_last_restore(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])

    (tmp_path / "note.md").write_text("v2")
    main(["restore", "0"])
    assert (tmp_path / "note.md").read_text() == "v1"

    capsys.readouterr()
    main(["undo"])
    out = capsys.readouterr().out
    assert "undid last restore" in out
    assert (tmp_path / "note.md").read_text() == "v2"


def test_undo_clean_drops_files_the_restore_added(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("keep")
    main(["init"])
    main(["save", "-m", "rich"])

    (tmp_path / "a.txt").unlink()
    main(["restore", "0"])
    assert (tmp_path / "a.txt").exists()

    main(["undo", "--clean"])
    assert not (tmp_path / "a.txt").exists()


def test_undo_without_restore_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])

    try:
        main(["undo"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("undo should exit non-zero with no restore to undo")


def test_restore_no_backup_skips_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("v2")
    main(["restore", "0", "--no-backup"])
    snaps = list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    assert len(snaps) == 1


def test_cli_restore_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("edited")
    main(["restore", "0", "--dry-run"])
    out = capsys.readouterr().out
    assert "note.md" in out
    assert "dry run" in out
    assert (tmp_path / "note.md").read_text() == "edited"


def test_cli_list_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "wip"])
    capsys.readouterr()

    main(["list", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert len(snaps) == 1
    assert snaps[0]["message"] == "wip"
    assert snaps[0]["count"] == 1
    assert snaps[0]["size"] == len("draft")


def test_cli_status_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "b.txt").write_text("new")
    (tmp_path / "a.txt").write_text("v2")
    main(["status", "--json"])
    s = json.loads(capsys.readouterr().out)
    assert s["added"] == ["b.txt"]
    assert s["modified"] == ["a.txt"]


def test_cli_verify_reports_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["verify"])
    assert "ok" in capsys.readouterr().out


def test_cli_verify_repair_drops_broken_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("keep")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("broken")
    main(["save", "-m", "second"])

    broken = hashlib.sha256(b"broken").hexdigest()
    (tmp_path / ".quicksave" / "objects" / broken[:2] / broken[2:]).unlink()
    capsys.readouterr()

    main(["verify", "--repair"])
    assert "dropped" in capsys.readouterr().out
    capsys.readouterr()
    main(["verify"])
    assert "ok" in capsys.readouterr().out


def test_hook_saves_before_risky_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.txt").write_text("keep")
    main(["init"])

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf data.txt"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    main(["hook"])

    snaps = list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    assert len(snaps) == 1
    assert "pre: rm -rf data.txt" in snaps[0].read_text()


def test_hook_does_not_pile_up_dups(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data.txt").write_text("keep")
    main(["init"])

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf nope.txt"}})
    for _ in range(3):
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        main(["hook"])

    # tree never changed, so the second and third firings reuse the first snapshot
    snaps = list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    assert len(snaps) == 1


def test_hook_caps_history_with_keep(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QUICKSAVE_KEEP", "2")
    main(["init"])
    f = tmp_path / "data.txt"
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}})
    for i in range(4):
        f.write_text(str(i))
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        main(["hook"])

    snaps = list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    assert len(snaps) == 2


def test_hook_skips_safe_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["init"])

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    main(["hook"])

    assert not list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))


def test_hook_noop_outside_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    main(["hook"])  # no quicksave project, must not raise


def test_hook_install_claude(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["hook", "install"])

    cfg = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    group = cfg["hooks"]["PreToolUse"][0]
    assert group["matcher"] == "Bash"
    assert group["hooks"][0]["command"] == "quicksave hook"


def test_hook_install_codex_and_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["hook", "install", "--tool", "codex"])
    main(["hook", "install", "--tool", "codex"])
    assert "already wired" in capsys.readouterr().out

    cfg = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    pre = cfg["hooks"]["PreToolUse"]
    assert len(pre) == 1 and len(pre[0]["hooks"]) == 1


def test_hook_install_merges_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    cfg_dir = tmp_path / ".claude"
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text(json.dumps({"model": "opus", "hooks": {}}))
    main(["hook", "install"])

    cfg = json.loads((cfg_dir / "settings.json").read_text())
    assert cfg["model"] == "opus"
    assert cfg["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "quicksave hook"


def test_quiet_silences_save_and_list(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    capsys.readouterr()

    main(["save", "-q", "-m", "wip"])
    main(["-q", "list"])
    assert capsys.readouterr().out == ""

    # --json still works under --quiet so scripts can read it
    main(["list", "-q", "--json"])
    assert json.loads(capsys.readouterr().out)[0]["message"] == "wip"


def test_quiet_keeps_error_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    try:
        main(["-q", "save"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("expected SystemExit")
    assert "not a quicksave project" in capsys.readouterr().err


def test_save_without_init_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    try:
        main(["save"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("expected SystemExit")


def test_log_shows_snapshot_details(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("data")

    main(["init"])
    main(["save", "-m", "first", "-n", "v1"])
    capsys.readouterr()

    main(["log", "v1"])
    out = capsys.readouterr().out
    assert "v1" in out
    assert "first" in out
    assert "a.txt" in out
    assert "sub/b.txt" in out
    assert "Files: 2" in out

    main(["log", "0"])
    assert "v1" in capsys.readouterr().out


def test_log_defaults_to_latest(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    main(["init"])
    main(["save", "-m", "first", "-n", "v1"])
    (tmp_path / "a.txt").write_text("changed")
    main(["save", "-m", "second", "-n", "v2"])
    capsys.readouterr()

    main(["log"])
    out = capsys.readouterr().out
    assert "v2" in out
    assert "second" in out
    assert "v1" not in out


def test_log_json_emits_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    main(["init"])
    main(["save", "-m", "first", "-n", "v1"])
    capsys.readouterr()

    main(["log", "v1", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["id"] and data["name"] == "v1"
    assert data["message"] == "first"
    assert [f["path"] for f in data["files"]] == ["a.txt"]
    assert data["files"][0]["size"] == 5


def test_log_missing_snapshot_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    try:
        main(["log", "nope"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("expected SystemExit")
    assert "not found" in capsys.readouterr().err


def test_list_limit_caps_output(capsys, monkeypatch):
    snaps = [
        {"seq": 1, "id": "a", "name": "", "created_at": 1, "count": 1, "size": 10, "message": ""},
        {"seq": 2, "id": "b", "name": "", "created_at": 2, "count": 1, "size": 10, "message": ""},
        {"seq": 3, "id": "c", "name": "", "created_at": 3, "count": 1, "size": 10, "message": ""},
    ]

    monkeypatch.setattr(store, "find_root", lambda: "/tmp")
    monkeypatch.setattr(store, "list_snapshots", lambda root: snaps)
    monkeypatch.setattr(store, "store_size", lambda root: 123)

    args = argparse.Namespace(json=False, limit=2, absolute=True)
    cmd_list(args)

    out = capsys.readouterr().out

    assert " a " not in out
    assert " b " in out
    assert " c " in out


def test_list_limit_footer(capsys, monkeypatch):
    snaps = [
        {"seq": 1, "id": "a", "name": "", "created_at": 1, "count": 1, "size": 10, "message": ""},
        {"seq": 2, "id": "b", "name": "", "created_at": 2, "count": 1, "size": 10, "message": ""},
        {"seq": 3, "id": "c", "name": "", "created_at": 3, "count": 1, "size": 10, "message": ""},
    ]

    monkeypatch.setattr(store, "find_root", lambda: "/tmp")
    monkeypatch.setattr(store, "list_snapshots", lambda root: snaps)
    monkeypatch.setattr(store, "store_size", lambda root: 999)

    args = argparse.Namespace(json=False, limit=1)
    cmd_list(args)

    out = capsys.readouterr().out.lower()

    assert "showing 1 of 3 snapshots" in out


def test_relative_time():
    now = 1_000_000.0
    assert _relative_time(0, now) == "-"
    assert _relative_time(now - 10, now) == "just now"
    assert _relative_time(now - 120, now) == "2m ago"
    assert _relative_time(now - 7200, now) == "2h ago"
    assert _relative_time(now - 3 * 86400, now) == "3d ago"


def test_list_relative_when(capsys, monkeypatch):
    snaps = [
        {"seq": 1, "id": "a", "name": "", "created_at": 1, "count": 1, "size": 10, "message": ""},
    ]
    monkeypatch.setattr(store, "find_root", lambda: "/tmp")
    monkeypatch.setattr(store, "list_snapshots", lambda root: snaps)
    monkeypatch.setattr(store, "store_size", lambda root: 1)

    args = argparse.Namespace(json=False, limit=None, absolute=False)
    cmd_list(args)

    assert "ago" in capsys.readouterr().out


def test_list_pinned_filters(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "keep me"])
    (tmp_path / "a.txt").write_text("v2")
    main(["save", "-m", "throwaway"])
    main(["pin", "0"])
    capsys.readouterr()

    main(["list", "--pinned", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert len(snaps) == 1
    assert snaps[0]["message"] == "keep me"
    assert snaps[0]["pinned"] is True


def test_list_pinned_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "wip"])
    capsys.readouterr()

    main(["list", "--pinned"])
    assert "no pinned snapshots" in capsys.readouterr().out


def test_cli_export(tmp_path, monkeypatch, capsys):
    import tarfile

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    dest = tmp_path / "snap.tgz"
    main(["export", str(dest)])
    out = capsys.readouterr().out
    assert "exported" in out
    with tarfile.open(dest) as tar:
        assert tar.getnames() == ["a.txt"]
        assert tar.extractfile("a.txt").read() == b"hi"


def test_cli_import_after_export(tmp_path, monkeypatch, capsys):
    import os

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    main(["init"])
    main(["save", "-m", "base"])
    dest = tmp_path / "snap.tgz"
    main(["export", str(dest)])
    capsys.readouterr()

    main(["import", str(dest), "--name", "fromtar"])
    out = capsys.readouterr().out
    assert "imported" in out
    assert "fromtar" in out

    os.remove(tmp_path / "a.txt")
    main(["restore", "fromtar"])
    assert (tmp_path / "a.txt").read_text() == "hi"


def test_diff_file_shows_line_changes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one\ntwo changed\nthree\n")
    main(["save", "-m", "edit"])
    capsys.readouterr()
    main(["diff", "0", "1", "a.txt"])
    out = capsys.readouterr().out
    assert "+two changed" in out
    assert "+three" in out
    assert "-two" in out


def test_diff_file_identical(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("same\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "b.txt").write_text("other\n")
    main(["save", "-m", "two"])
    capsys.readouterr()
    main(["diff", "0", "1", "a.txt"])
    assert "identical" in capsys.readouterr().out


def test_diff_against_working_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one\ntwo edited\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    capsys.readouterr()
    main(["diff", "0", "wt"])
    out = capsys.readouterr().out
    assert "+ new.txt" in out
    assert "~ a.txt" in out
    capsys.readouterr()
    main(["diff", "0", "wt", "a.txt"])
    out = capsys.readouterr().out
    assert "+two edited" in out
    assert "-two" in out


def test_cli_find(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keep.txt").write_text("data")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "keep.txt").unlink()
    capsys.readouterr()

    main(["find", "keep.txt"])
    out = capsys.readouterr().out
    assert "keep.txt" in out
    assert "quicksave restore" in out

    main(["find", "keep.txt", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["files"][0]["path"] == "keep.txt"

    main(["find", "ghost.txt"])
    assert "no snapshot" in capsys.readouterr().out


def test_cli_find_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keep.txt"
    main(["init"])
    for v in ("one", "two", "three"):
        f.write_text(v)
        main(["save", "-m", v])
    capsys.readouterr()

    main(["find", "keep.txt", "--limit", "2", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    assert data[0]["message"] == "three"
    assert data[1]["message"] == "two"


def test_cli_stats(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("same")
    (tmp_path / "b.txt").write_text("same")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["stats"])
    out = capsys.readouterr().out
    assert "snapshots" in out
    assert "dedup" in out

    main(["stats", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["snapshots"] == 1
    assert data["blobs"] == 1

    main(["stats", "--markdown"])
    out = capsys.readouterr().out
    assert "| snapshots | blobs | on disk | dedup |" in out
    assert "| --- | --- | --- | --- |" in out
    assert "| 1 | 1 |" in out
