import hashlib
import io
import json
import time


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


def test_recover_pulls_a_file_from_the_newest_snapshot_that_had_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keep.txt").write_text("stay")
    (tmp_path / "gone.txt").write_text("important")
    main(["init"])
    main(["save", "-m", "with file"])

    # delete it and snapshot the tree without it a couple of times
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "keep.txt").write_text("changed")
    main(["save", "-m", "after delete"])

    # tree is dirty now, so recover's pre-restore backup is a real snapshot
    (tmp_path / "keep.txt").write_text("dirty")
    capsys.readouterr()

    main(["recover", "gone.txt"])
    assert (tmp_path / "gone.txt").read_text() == "important"
    assert "recovered" in capsys.readouterr().out
    # the pre-recover tree is backed up, so undo --clean rewinds the recovery
    main(["undo", "--clean"])
    assert not (tmp_path / "gone.txt").exists()


def test_recover_from_picks_an_older_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.txt").write_text("good")
    main(["init"])
    main(["save", "-m", "good copy"])
    # the file gets clobbered, then a later snapshot captures the bad version
    (tmp_path / "gone.txt").write_text("broken")
    main(["save", "-m", "bad copy"])
    (tmp_path / "gone.txt").unlink()
    main(["save", "-m", "after delete"])
    capsys.readouterr()

    # a bare recover grabs the newest copy that has it, which is the broken one
    main(["recover", "gone.txt", "--from", "0", "--no-backup"])
    assert (tmp_path / "gone.txt").read_text() == "good"
    assert "recovered" in capsys.readouterr().out


def test_recover_from_no_match_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "b.txt").write_text("v1")
    main(["save", "-m", "with b"])

    # b.txt isn't in snapshot 0, so --from 0 has nothing to recover
    try:
        main(["recover", "b.txt", "--from", "0"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("recover --from should exit non-zero when the ref has no match")


def test_recover_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.txt").write_text("important")
    main(["init"])
    main(["save", "-m", "with file"])
    (tmp_path / "gone.txt").unlink()
    main(["save", "-m", "after delete"])
    n_snaps = len(store.list_snapshots(tmp_path))
    capsys.readouterr()

    main(["recover", "gone.txt", "--dry-run"])
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "gone.txt" in out
    # nothing brought back and no backup snapshot taken
    assert not (tmp_path / "gone.txt").exists()
    assert len(store.list_snapshots(tmp_path)) == n_snaps


def test_recover_into_pulls_aside_without_touching_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.txt").write_text("important")
    main(["init"])
    main(["save", "-m", "with file"])
    (tmp_path / "gone.txt").unlink()
    main(["save", "-m", "after delete"])
    n_snaps = len(store.list_snapshots(tmp_path))
    capsys.readouterr()

    out_dir = tmp_path / "aside"
    main(["recover", "gone.txt", "--into", str(out_dir)])

    # the match lands in out_dir, the live tree and snapshot count stay as they were
    assert (out_dir / "gone.txt").read_text() == "important"
    assert not (tmp_path / "gone.txt").exists()
    assert len(store.list_snapshots(tmp_path)) == n_snaps
    assert "recovered" in capsys.readouterr().out


def test_recover_no_match_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])

    try:
        main(["recover", "nope.txt"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("recover should exit non-zero when nothing matches")


def test_recover_json_reports_snapshot_and_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gone.txt").write_text("important")
    main(["init"])
    main(["save", "-m", "with file"])
    (tmp_path / "gone.txt").unlink()
    main(["save", "-m", "after delete"])
    capsys.readouterr()

    main(["recover", "gone.txt", "--json"])
    r = json.loads(capsys.readouterr().out)
    assert r["recovered"] == 1
    res = r["results"][0]
    assert res["files"] == ["gone.txt"]
    assert res["snapshot"]["id"]
    assert (tmp_path / "gone.txt").read_text() == "important"

    # no match emits an empty result instead of erroring out
    capsys.readouterr()
    main(["recover", "nope.txt", "--json"])
    r = json.loads(capsys.readouterr().out)
    assert r["results"][0]["snapshot"] is None
    assert r["recovered"] == 0


def test_recover_takes_more_than_one_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("app")
    (tmp_path / "util.py").write_text("util")
    main(["init"])
    main(["save", "-m", "both here"])
    # util.py lives on in a later snapshot, app.py only in the first one
    (tmp_path / "app.py").unlink()
    main(["save", "-m", "app gone"])
    (tmp_path / "util.py").unlink()
    main(["save", "-m", "util gone"])
    # something untracked in the tree so the pre-restore backup is a real snapshot
    (tmp_path / "scratch.txt").write_text("wip")
    capsys.readouterr()

    main(["recover", "app.py", "util.py", "--json"])
    r = json.loads(capsys.readouterr().out)
    assert r["recovered"] == 2
    assert {res["path"] for res in r["results"]} == {"app.py", "util.py"}
    assert (tmp_path / "app.py").read_text() == "app"
    assert (tmp_path / "util.py").read_text() == "util"
    # one shared pre-restore backup for the whole batch, so undo rewinds it all
    main(["undo", "--clean"])
    assert not (tmp_path / "app.py").exists()
    assert not (tmp_path / "util.py").exists()


def test_recover_keeps_going_when_one_path_misses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "real.txt").write_text("here")
    main(["init"])
    main(["save", "-m", "with file"])
    (tmp_path / "real.txt").unlink()
    main(["save", "-m", "after delete"])
    capsys.readouterr()

    main(["recover", "real.txt", "nope.txt", "--json"])
    r = json.loads(capsys.readouterr().out)
    assert r["recovered"] == 1
    by_path = {res["path"]: res for res in r["results"]}
    assert by_path["real.txt"]["snapshot"]["id"]
    assert by_path["nope.txt"]["snapshot"] is None
    assert (tmp_path / "real.txt").read_text() == "here"


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


def test_names_lists_only_named_snapshots_newest_first(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base", "-n", "first"])
    (tmp_path / "a.txt").write_text("v2")
    main(["save", "-m", "mid"])  # no name
    (tmp_path / "a.txt").write_text("v3")
    main(["save", "-m", "top", "-n", "second"])
    capsys.readouterr()

    main(["names", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert [r["name"] for r in rows] == ["second", "first"]

    main(["names"])
    out = capsys.readouterr().out
    assert "second" in out and "first" in out


def test_names_empty_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["names"])
    assert "no named snapshots yet" in capsys.readouterr().out


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


def test_restore_into_leaves_tree_untouched(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("v2")
    out_dir = tmp_path / "recovered"
    main(["restore", "0", "--into", str(out_dir)])

    # the snapshot lands in out_dir, the live tree and snapshot count stay as they were
    assert (out_dir / "note.md").read_text() == "v1"
    assert (tmp_path / "note.md").read_text() == "v2"
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


def test_restore_json_reports_result(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("v2")
    main(["restore", "0", "--json"])
    res = json.loads(capsys.readouterr().out)
    assert res["ref"] == "0"
    assert res["restored"] == 1
    assert res["backup"]  # pre-restore tree was snapshotted
    assert (tmp_path / "note.md").read_text() == "v1"


def test_restore_dry_run_json_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    (tmp_path / "note.md").write_text("edited")
    main(["restore", "0", "--dry-run", "--json"])
    res = json.loads(capsys.readouterr().out)
    assert res["dry_run"] is True
    assert res["overwritten"] == ["note.md"]
    assert res["would_write"] == 1
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


def test_cli_save_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    capsys.readouterr()

    main(["save", "-m", "wip", "-n", "pre", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["created"] is True
    assert out["files"] == 1
    assert out["name"] == "pre"
    assert out["message"] == "wip"
    assert len(out["id"]) > 0

    # nothing changed: still valid json, created False, and quiet doesn't swallow it
    main(["save", "-q", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["created"] is False


def test_save_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one")
    main(["init"])
    main(["save", "-m", "first"])
    (tmp_path / "a.txt").write_text("changed")
    (tmp_path / "b.txt").write_text("new")
    capsys.readouterr()

    main(["save", "--dry-run", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["would_change"] is True
    assert out["added"] == ["b.txt"]
    assert out["modified"] == ["a.txt"]

    # the snapshot count didn't move
    main(["list", "--json"])
    assert len(json.loads(capsys.readouterr().out)) == 1

    # clean tree: dry run reports no change
    main(["save", "-m", "second"])
    capsys.readouterr()
    main(["save", "--dry-run"])
    assert "nothing changed" in capsys.readouterr().out


def test_cli_gc_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("v1")
    main(["init"])
    main(["save", "-m", "one"])
    note.write_text("v2")
    main(["save", "-m", "two"])
    capsys.readouterr()

    main(["gc", "--keep", "1", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is False
    assert len(out["pruned"]) == 1
    assert out["blobs"] >= 1
    assert out["bytes"] >= 0


def test_cli_gc_keep_named_spares_labels(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("v1")
    main(["init"])
    main(["save", "-m", "one"])
    main(["name", "0", "milestone"])
    note.write_text("v2")
    main(["save", "-m", "two"])
    note.write_text("v3")
    main(["save", "-m", "three"])
    capsys.readouterr()

    main(["gc", "--keep", "1", "--keep-named", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert len(out["pruned"]) == 1
    left = [(s["name"], s["message"]) for s in store.list_snapshots(tmp_path)]
    assert left == [("milestone", "one"), ("", "three")]


def test_cli_drop_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("v1")
    main(["init"])
    main(["save", "-m", "one"])
    note.write_text("v2")
    main(["save", "-m", "two"])
    capsys.readouterr()

    main(["drop", "0", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is False
    assert out["blobs"] == 1
    assert [s["message"] for s in store.list_snapshots(tmp_path)] == ["two"]


def test_cli_list_since_filters_old_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "old"])
    (tmp_path / "note.md").write_text("draft 2")
    main(["save", "-m", "fresh"])
    capsys.readouterr()

    snap_files = sorted((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    oldest = json.loads(snap_files[0].read_text())
    oldest["created_at"] = time.time() - 3 * 3600
    snap_files[0].write_text(json.dumps(oldest))

    main(["list", "--since", "1h", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in snaps] == ["fresh"]

    main(["list", "--since", "5h", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert {s["message"] for s in snaps} == {"old", "fresh"}


def test_cli_list_before_filters_recent_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "old"])
    (tmp_path / "note.md").write_text("draft 2")
    main(["save", "-m", "fresh"])
    capsys.readouterr()

    snap_files = sorted((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    oldest = json.loads(snap_files[0].read_text())
    oldest["created_at"] = time.time() - 3 * 3600
    snap_files[0].write_text(json.dumps(oldest))

    main(["list", "--before", "1h", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in snaps] == ["old"]

    main(["list", "--before", "5h", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert snaps == []


def test_cli_list_grep_filters_by_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "pre: rm -rf build"])
    (tmp_path / "note.md").write_text("draft 2")
    main(["save", "-m", "wip layout"])
    capsys.readouterr()

    main(["list", "--grep", "rm -rf", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in snaps] == ["pre: rm -rf build"]

    main(["list", "--grep", "LAYOUT", "--json"])
    snaps = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in snaps] == ["wip layout"]

    main(["list", "--grep", "nothing"])
    assert "no snapshots match 'nothing'" in capsys.readouterr().out


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


def test_cli_status_short(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    (tmp_path / "gone.txt").write_text("bye")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["status", "--short"])
    assert capsys.readouterr().out.strip() == "clean"

    (tmp_path / "a.txt").write_text("v2")
    (tmp_path / "b.txt").write_text("new")
    (tmp_path / "gone.txt").unlink()
    main(["status", "--short"])
    assert capsys.readouterr().out.strip() == "~1 +1 -1"


def test_cli_status_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("v1")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    # clean tree exits 0
    main(["status", "--exit-code"])

    (tmp_path / "a.txt").write_text("v2")
    try:
        main(["status", "--exit-code"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("dirty tree should exit 1")
    capsys.readouterr()

    # --json honours the exit code too
    try:
        main(["status", "--json", "--exit-code"])
    except SystemExit as e:
        assert e.code == 1
    else:
        raise AssertionError("dirty --json should exit 1")
    assert json.loads(capsys.readouterr().out)["modified"] == ["a.txt"]


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
    assert "Files: 2 (9B)" in out

    main(["log", "0"])
    assert "v1" in capsys.readouterr().out


def test_log_renders_human_sizes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    main(["init"])
    main(["save", "-m", "first", "-n", "v1"])
    capsys.readouterr()

    main(["log", "v1"])
    out = capsys.readouterr().out
    assert "a.txt (5B)" in out
    assert "bytes" not in out


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


def test_list_reverse_shows_newest_first(capsys, monkeypatch):
    snaps = [
        {"seq": 1, "id": "a", "name": "", "created_at": 1, "count": 1, "size": 10, "message": ""},
        {"seq": 2, "id": "b", "name": "", "created_at": 2, "count": 1, "size": 10, "message": ""},
        {"seq": 3, "id": "c", "name": "", "created_at": 3, "count": 1, "size": 10, "message": ""},
    ]

    monkeypatch.setattr(store, "find_root", lambda: "/tmp")
    monkeypatch.setattr(store, "list_snapshots", lambda root: snaps)
    monkeypatch.setattr(store, "store_size", lambda root: 123)

    args = argparse.Namespace(json=False, limit=None, absolute=True, reverse=True)
    cmd_list(args)

    out = capsys.readouterr().out
    assert out.index(" c ") < out.index(" b ") < out.index(" a ")


def test_list_reverse_with_limit_keeps_newest(capsys, monkeypatch):
    snaps = [
        {"seq": 1, "id": "a", "name": "", "created_at": 1, "count": 1, "size": 10, "message": ""},
        {"seq": 2, "id": "b", "name": "", "created_at": 2, "count": 1, "size": 10, "message": ""},
        {"seq": 3, "id": "c", "name": "", "created_at": 3, "count": 1, "size": 10, "message": ""},
    ]

    monkeypatch.setattr(store, "find_root", lambda: "/tmp")
    monkeypatch.setattr(store, "list_snapshots", lambda root: snaps)
    monkeypatch.setattr(store, "store_size", lambda root: 123)

    args = argparse.Namespace(json=False, limit=2, absolute=True, reverse=True)
    cmd_list(args)

    out = capsys.readouterr().out
    assert " a " not in out
    assert out.index(" c ") < out.index(" b ")


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


def test_cli_import_dry_run_previews(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hi")
    main(["init"])
    main(["save", "-m", "base", "--name", "golden"])
    dest = tmp_path / "snap.tgz"
    main(["export", str(dest)])
    n_snaps = len(list((tmp_path / ".quicksave" / "snapshots").glob("*.json")))
    capsys.readouterr()

    main(["import", str(dest), "--dry-run"])
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "golden" in out
    assert "a.txt" in out
    # preview must not add a snapshot
    assert len(list((tmp_path / ".quicksave" / "snapshots").glob("*.json"))) == n_snaps


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


def test_diff_defaults_second_side_to_working_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one\ntwo edited\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    capsys.readouterr()
    main(["diff", "0"])
    out = capsys.readouterr().out
    assert "+ new.txt" in out
    assert "~ a.txt" in out


def test_diff_json_between_snapshots(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "drop.txt").write_text("gone\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("two\n")
    (tmp_path / "drop.txt").unlink()
    (tmp_path / "new.txt").write_text("fresh\n")
    main(["save", "-m", "edit"])
    capsys.readouterr()
    main(["diff", "0", "1", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["added"] == ["new.txt"]
    assert d["removed"] == ["drop.txt"]
    assert d["modified"] == ["a.txt"]


def test_diff_stat_skips_the_file_list(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("two\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    main(["save", "-m", "edit"])
    capsys.readouterr()
    main(["diff", "0", "1", "--stat"])
    out = capsys.readouterr().out
    assert "1 added, 0 removed, 1 modified" in out
    assert "new.txt" not in out
    assert "a.txt" not in out


def test_diff_name_only_between_snapshots(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    (tmp_path / "drop.txt").write_text("gone\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("two\n")
    (tmp_path / "drop.txt").unlink()
    (tmp_path / "new.txt").write_text("fresh\n")
    main(["save", "-m", "edit"])
    capsys.readouterr()
    main(["diff", "0", "1", "--name-only"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert set(lines) == {"new.txt", "drop.txt", "a.txt"}
    assert "+" not in out
    assert "-" not in out
    assert "~" not in out
    assert "added" not in out


def test_diff_name_only_against_working_tree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one\ntwo edited\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    capsys.readouterr()
    main(["diff", "0", "wt", "--name-only"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert set(lines) == {"new.txt", "a.txt"}
    assert "+" not in out
    assert "~" not in out


def test_diff_name_only_no_changes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()
    main(["diff", "0", "wt", "--name-only"])
    out = capsys.readouterr().out.strip()
    assert "working tree matches" in out


def test_diff_json_against_working_tree(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one edited\n")
    (tmp_path / "new.txt").write_text("fresh\n")
    capsys.readouterr()
    main(["diff", "0", "wt", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["added"] == ["new.txt"]
    assert d["modified"] == ["a.txt"]


def test_diff_json_file(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    main(["init"])
    main(["save", "-m", "base"])
    (tmp_path / "a.txt").write_text("one\ntwo changed\n")
    main(["save", "-m", "edit"])
    capsys.readouterr()
    main(["diff", "0", "1", "a.txt", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["path"] == "a.txt"
    assert "+two changed" in d["diff"]


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


def test_cli_find_multiple_paths(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "c.txt").write_text("c")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["find", "a.txt", "b.txt", "--json"])
    paths = {h["path"] for h in json.loads(capsys.readouterr().out)[0]["files"]}
    assert paths == {"a.txt", "b.txt"}

    main(["find", "a.txt", "b.txt"])
    out = capsys.readouterr().out
    assert "quicksave recover a.txt b.txt" in out


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


def test_cli_find_since_and_before_window(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keep.txt"
    main(["init"])
    for v in ("one", "two"):
        f.write_text(v)
        main(["save", "-m", v])
    capsys.readouterr()

    snap_files = sorted((tmp_path / ".quicksave" / "snapshots").glob("*.json"))
    oldest = json.loads(snap_files[0].read_text())
    oldest["created_at"] = time.time() - 3 * 3600
    snap_files[0].write_text(json.dumps(oldest))

    main(["find", "keep.txt", "--since", "1h", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in data] == ["two"]

    main(["find", "keep.txt", "--before", "1h", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in data] == ["one"]


def test_cli_find_count(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keep.txt"
    main(["init"])
    for v in ("one", "two", "three"):
        f.write_text(v)
        main(["save", "-m", v])
    capsys.readouterr()

    main(["find", "keep.txt", "--count"])
    out = capsys.readouterr().out.strip()
    assert out == "3"


def test_cli_find_count_respects_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keep.txt"
    main(["init"])
    for v in ("one", "two", "three"):
        f.write_text(v)
        main(["save", "-m", v])
    capsys.readouterr()

    main(["find", "keep.txt", "--limit", "2", "--count"])
    out = capsys.readouterr().out.strip()
    assert out == "2"


def test_cli_find_count_no_matches(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    capsys.readouterr()

    main(["find", "ghost.txt", "--count"])
    out = capsys.readouterr().out.strip()
    assert out == "0"


def test_cli_find_changes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keep.txt"
    other = tmp_path / "other.txt"
    main(["init"])
    f.write_text("one")
    main(["save", "-m", "v1"])
    other.write_text("x")
    main(["save", "-m", "touch other"])
    f.write_text("two")
    main(["save", "-m", "v2"])
    capsys.readouterr()

    main(["find", "keep.txt", "--json"])
    assert len(json.loads(capsys.readouterr().out)) == 3

    main(["find", "keep.txt", "--changes", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [s["message"] for s in data] == ["v2", "v1"]


def test_cli_find_glob(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("a")
    (src / "util.py").write_text("u")
    (tmp_path / "notes.txt").write_text("n")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["find", "*.py", "--json"])
    paths = {h["path"] for h in json.loads(capsys.readouterr().out)[0]["files"]}
    assert paths == {"src/app.py", "src/util.py"}

    main(["find", "src/*.txt"])
    assert "no snapshot" in capsys.readouterr().out


def test_cli_find_ignore_case(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("r")
    main(["init"])
    main(["save", "-m", "base"])
    capsys.readouterr()

    main(["find", "readme"])
    assert "no snapshot" in capsys.readouterr().out

    main(["find", "readme", "-i", "--json"])
    paths = {h["path"] for h in json.loads(capsys.readouterr().out)[0]["files"]}
    assert paths == {"README.md"}

    main(["find", "*.MD", "-i", "--json"])
    paths = {h["path"] for h in json.loads(capsys.readouterr().out)[0]["files"]}
    assert paths == {"README.md"}


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


def test_no_color_env_strips_styling(tmp_path, monkeypatch, capsys):
    from quicksave import cli

    from rich.color import ColorSystem

    monkeypatch.chdir(tmp_path)
    # make rich believe it is a real terminal so it would otherwise emit ansi
    monkeypatch.setattr(cli.console, "_force_terminal", True)
    monkeypatch.setattr(cli.console, "_color_system", ColorSystem.TRUECOLOR)
    (tmp_path / "note.md").write_text("draft")
    main(["init"])
    main(["save", "-m", "wip"])
    capsys.readouterr()

    monkeypatch.delenv("NO_COLOR", raising=False)
    main(["list"])
    assert "\x1b[" in capsys.readouterr().out

    monkeypatch.setenv("NO_COLOR", "1")
    main(["list"])
    assert "\x1b[" not in capsys.readouterr().out


def test_completion_bash_lists_subcommands(capsys):
    main(["completion", "bash"])
    out = capsys.readouterr().out
    assert "complete -F _quicksave quicksave" in out
    # the command list comes straight from the parser, so a real subcommand is in it
    assert "restore" in out
    assert "completion" in out


def test_completion_zsh_wires_compdef(capsys):
    main(["completion", "zsh"])
    out = capsys.readouterr().out
    assert out.startswith("#compdef quicksave")
    assert "compdef _quicksave quicksave" in out
    assert "restore" in out

def test_completion_fish_lists_subcommands(capsys):
    main(["completion", "fish"])
    out = capsys.readouterr().out
    assert "complete -c quicksave" in out
    assert "__fish_use_subcommand" in out
    assert "restore" in out


def test_completion_powershell_registers_completer(capsys):
    main(["completion", "powershell"])
    out = capsys.readouterr().out
    assert "Register-ArgumentCompleter -Native -CommandName quicksave" in out
    assert "restore" in out

# ---------------------------------------------------------------------------
# find --changes --diff
# ---------------------------------------------------------------------------

def test_find_changes_diff_shows_unified_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "notes.txt"
    main(["init"])
    f.write_text("version one\n")
    main(["save", "-m", "v1"])
    f.write_text("version two\n")
    main(["save", "-m", "v2"])
    f.write_text("version three\n")
    main(["save", "-m", "v3"])
    capsys.readouterr()

    main(["find", "notes.txt", "--changes", "--diff"])
    out = capsys.readouterr().out

    # diffs from v1→v2 and v2→v3 should both appear
    assert "-version one" in out
    assert "+version two" in out
    assert "-version two" in out
    assert "+version three" in out


def test_find_changes_diff_first_snapshot_from_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "hello.txt"
    main(["init"])
    f.write_text("hello\n")
    main(["save", "-m", "init"])
    capsys.readouterr()

    main(["find", "hello.txt", "--changes", "--diff"])
    out = capsys.readouterr().out

    # first snapshot diffs from empty, so the line should appear as added
    assert "+hello" in out


def test_find_changes_diff_multi_path_bails(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["init"])
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    main(["save", "-m", "base"])
    capsys.readouterr()

    import pytest
    with pytest.raises(SystemExit):
        main(["find", "*.py", "--changes", "--diff"])
    err_out = capsys.readouterr().err
    assert "exactly one file path" in err_out


def test_save_message_from_stdin(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("content")
    main(["init"])
    monkeypatch.setattr("sys.stdin", io.StringIO("message from stdin\n"))
    main(["save", "-m", "-"])
    out = capsys.readouterr().out
    assert "message from stdin" in out


def test_save_message_from_stdin_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("content")
    main(["init"])
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO("piped message"))
    main(["save", "-m", "-", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["message"] == "piped message"
