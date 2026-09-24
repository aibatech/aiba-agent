"""Execution backend contract for AIBA terminal/file operations.

Backends define the confinement envelope for shell and backend file operations.
Selecting a backend never bypasses ToolRegistry approval or permissions policy.
"""
from __future__ import annotations
from abc import ABC,abstractmethod
from dataclasses import dataclass
from pathlib import Path
import base64,json,shlex,subprocess

@dataclass
class BackendResult:
    ok:bool
    returncode:int=0
    stdout:str=""
    stderr:str=""

class TerminalBackend(ABC):
    name="abstract"
    @abstractmethod
    def execute(self,command:str,timeout:int)->BackendResult: ...
    @abstractmethod
    def read_file(self,path:str,timeout:int)->BackendResult: ...
    @abstractmethod
    def write_file(self,path:str,content:str,timeout:int)->BackendResult: ...
    def patch(self,path:str,old:str,new:str,replace_all:bool,timeout:int)->BackendResult:
        payload=base64.b64encode(json.dumps({"p":path,"o":old,"n":new,"a":replace_all}).encode()).decode()
        script=("import base64,json,pathlib;d=json.loads(base64.b64decode("+repr(payload)+"));"
                "p=pathlib.Path(d['p']);s=p.read_text();c=s.count(d['o']);"
                "assert c and (d['a'] or c==1),'patch target missing or ambiguous';"
                "p.write_text(s.replace(d['o'],d['n'],-1 if d['a'] else 1));print(c)")
        return self.execute("python3 -c "+shlex.quote(script),timeout)

class DockerBackend(TerminalBackend):
    name="docker"
    def __init__(self,workspace:Path,image:str,memory:str,cpus:str,network:bool):
        self.workspace=workspace;self.image=image;self.memory=memory;self.cpus=cpus;self.network=network
    def _run(self,args,timeout):
        cp=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
        return BackendResult(cp.returncode==0,cp.returncode,cp.stdout[-12000:],cp.stderr[-12000:])
    def execute(self,command,timeout):
        cmd=["docker","run","--rm","-v",f"{self.workspace}:/workspace","-w","/workspace","--memory",self.memory,"--cpus",self.cpus]
        if not self.network:cmd+=["--network","none"]
        return self._run(cmd+[self.image,"sh","-lc",command],timeout)
    def read_file(self,path,timeout):return self.execute("cat -- "+shlex.quote(path),timeout)
    def write_file(self,path,content,timeout):
        enc=base64.b64encode(content.encode()).decode()
        return self.execute("mkdir -p -- $(dirname "+shlex.quote(path)+"); printf %s "+shlex.quote(enc)+" | base64 -d > "+shlex.quote(path),timeout)

class SSHBackend(TerminalBackend):
    """Operator-selected SSH envelope.

    Host-key checking is mandatory. Passwords and shell-expanded host strings
    are not accepted; authentication is delegated to OpenSSH/ssh-agent or an
    explicit key path. The remote workspace is the only file root exposed by
    backend file methods. SSH isolates execution from the AIBA host but does not
    itself sandbox activity on the remote host.
    """
    name="ssh"
    def __init__(self,host:str,user:str,workspace:str,key_path:str|None=None,port:int=22,known_hosts:str|None=None):
        if not host or any(x in host for x in " \t\n/@"):raise ValueError("invalid SSH host")
        if not user or any(x in user for x in " \t\n/@"):raise ValueError("invalid SSH user")
        if not workspace.startswith("/"):raise ValueError("SSH workspace must be absolute")
        self.host=host;self.user=user;self.workspace=workspace.rstrip("/");self.key_path=key_path;self.port=int(port);self.known_hosts=known_hosts
    def _argv(self,remote):
        a=["ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-p",str(self.port)]
        if self.known_hosts:a+=["-o",f"UserKnownHostsFile={self.known_hosts}"]
        if self.key_path:a+=["-i",self.key_path]
        return a+["--",f"{self.user}@{self.host}",remote]
    def _run(self,remote,timeout):
        cp=subprocess.run(self._argv(remote),text=True,capture_output=True,timeout=timeout)
        return BackendResult(cp.returncode==0,cp.returncode,cp.stdout[-12000:],cp.stderr[-12000:])
    def _remote_path(self,path):
        if path.startswith("/") or ".." in Path(path).parts:raise ValueError("remote path must stay relative to configured workspace")
        return f"{self.workspace}/{path.lstrip('./')}"
    def execute(self,command,timeout):
        return self._run("cd -- "+shlex.quote(self.workspace)+" && "+command,timeout)
    def read_file(self,path,timeout):return self._run("cat -- "+shlex.quote(self._remote_path(path)),timeout)
    def write_file(self,path,content,timeout):
        p=self._remote_path(path);enc=base64.b64encode(content.encode()).decode()
        return self._run("mkdir -p -- "+shlex.quote(str(Path(p).parent))+" && printf %s "+shlex.quote(enc)+" | base64 -d > "+shlex.quote(p),timeout)

class RemoteDockerComposeBackend(SSHBackend):
    """Self-hostable persistent remote Docker Compose execution.

    Commands execute inside an already operator-provisioned service. AIBA does
    not create the daemon, compose project, mounts, credentials, or network.
    """
    name="remote_compose"
    def __init__(self,*args,service:str,compose_file:str="compose.yaml",**kwargs):
        super().__init__(*args,**kwargs)
        if not service or any(x in service for x in " \t\n/"):raise ValueError("invalid compose service")
        self.service=service;self.compose_file=compose_file
    def execute(self,command,timeout):
        remote=("cd -- "+shlex.quote(self.workspace)+" && docker compose -f "+shlex.quote(self.compose_file)+
                " exec -T "+shlex.quote(self.service)+" sh -lc "+shlex.quote(command))
        return self._run(remote,timeout)
