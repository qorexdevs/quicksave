import io
import json

from quicksave.cli import main


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
