import subprocess
from pathlib import Path
import pytest
from execution.backends import SSHBackend,RemoteDockerComposeBackend

def test_ssh_requires_safe_identity_and_absolute_workspace():
    with pytest.raises(ValueError):SSHBackend("host;bad","user","/work")
    with pytest.raises(ValueError):SSHBackend("host","user","relative")

def test_ssh_argv_has_host_key_checking_and_no_shell(monkeypatch):
    seen={}
    def fake(argv,**kw):
        seen["argv"]=argv
        return subprocess.CompletedProcess(argv,0,"ok","")
    monkeypatch.setattr(subprocess,"run",fake)
    b=SSHBackend("example.com","aiba","/srv/aiba",key_path="/keys/id",known_hosts="/keys/known_hosts")
    r=b.execute("printf hello",10)
    assert r.ok
    assert isinstance(seen["argv"],list)
    assert "StrictHostKeyChecking=yes" in seen["argv"]
    assert "UserKnownHostsFile=/keys/known_hosts" in seen["argv"]
    assert seen["argv"][-2:] == ["aiba@example.com","cd -- /srv/aiba && printf hello"]

def test_remote_file_paths_cannot_escape():
    b=SSHBackend("example.com","aiba","/srv/aiba")
    with pytest.raises(ValueError):b.read_file("../secret",10)
    with pytest.raises(ValueError):b.write_file("/etc/passwd","x",10)

def test_remote_compose_wraps_command(monkeypatch):
    seen={}
    def fake(argv,**kw):
        seen["argv"]=argv;return subprocess.CompletedProcess(argv,0,"","")
    monkeypatch.setattr(subprocess,"run",fake)
    b=RemoteDockerComposeBackend("example.com","aiba","/srv/aiba",service="worker")
    assert b.execute("id",10).ok
    assert "docker compose" in seen["argv"][-1]
    assert "exec -T worker" in seen["argv"][-1]
