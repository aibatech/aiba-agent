from __future__ import annotations
import tempfile
from pathlib import Path
from tools.host_files import HostFiles, _safe_host_path


def test_host_files_list_search_and_read_are_read_only():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); (root/"project").mkdir(); (root/"project"/"README.txt").write_text("hello host",encoding="utf-8")
        h=HostFiles()
        listing=h.list(str(root)); assert listing.ok
        search=h.search(str(root),"readme"); assert search.ok and search.output["matches"]
        read=h.read(str(root/"project"/"README.txt")); assert read.ok and "hello host" in read.output["text"]


def test_sensitive_key_directories_are_blocked():
    try:
        _safe_host_path(str(Path.home()/".ssh"/"id_rsa"))
    except PermissionError:
        pass
    else:
        raise AssertionError("sensitive host path should be blocked")


def test_search_does_not_follow_symlinks():
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
        root=Path(td); target=Path(outside); (target/"secret.txt").write_text("x",encoding="utf-8")
        try:
            (root/"link").symlink_to(target, target_is_directory=True)
        except OSError:
            return
        result=HostFiles().search(str(root),"secret")
        assert result.ok
        assert result.output["matches"] == []
