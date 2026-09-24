import subprocess
import unittest
from unittest.mock import patch
from execution.backends import SSHBackend,RemoteDockerComposeBackend

class TerminalBackendTests(unittest.TestCase):
    def test_ssh_requires_safe_identity_and_absolute_workspace(self):
        with self.assertRaises(ValueError):SSHBackend("host;bad","user","/work")
        with self.assertRaises(ValueError):SSHBackend("host","user","relative")
    def test_ssh_argv_has_host_key_checking_and_no_shell(self):
        seen={}
        def fake(argv,**kw):seen["argv"]=argv;return subprocess.CompletedProcess(argv,0,"ok","")
        with patch("execution.backends.subprocess.run",fake):
            r=SSHBackend("example.com","aiba","/srv/aiba",key_path="/keys/id",known_hosts="/keys/known_hosts").execute("printf hello",10)
        self.assertTrue(r.ok);self.assertIsInstance(seen["argv"],list);self.assertIn("StrictHostKeyChecking=yes",seen["argv"]);self.assertIn("UserKnownHostsFile=/keys/known_hosts",seen["argv"]);self.assertEqual(seen["argv"][-2:],["aiba@example.com","cd -- /srv/aiba && printf hello"])
    def test_remote_file_paths_cannot_escape(self):
        b=SSHBackend("example.com","aiba","/srv/aiba")
        with self.assertRaises(ValueError):b.read_file("../secret",10)
        with self.assertRaises(ValueError):b.write_file("/etc/passwd","x",10)
    def test_remote_compose_wraps_command(self):
        seen={}
        def fake(argv,**kw):seen["argv"]=argv;return subprocess.CompletedProcess(argv,0,"","")
        with patch("execution.backends.subprocess.run",fake):self.assertTrue(RemoteDockerComposeBackend("example.com","aiba","/srv/aiba",service="worker").execute("id",10).ok)
        self.assertIn("docker compose",seen["argv"][-1]);self.assertIn("exec -T worker",seen["argv"][-1])

if __name__=="__main__":unittest.main()
