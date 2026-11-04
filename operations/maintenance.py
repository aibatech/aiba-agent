"""OS-held profile leases: runtime readers exclude offline maintenance writers.

All AIBA runtimes cooperate. External scripts must take the same lease; this is
not a filesystem sandbox against arbitrary processes writing directly to files.
"""
import os
from pathlib import Path

LOCK_NAME = '.aiba-maintenance.lock'
PENDING_RESTORE = '.aiba-restore-pending'

class MaintenanceBusy(RuntimeError):
    pass

class ProfileLease:
    def __init__(self, data_dir, *, runtime=False):
        root=Path(data_dir).resolve();root.mkdir(parents=True,exist_ok=True)
        path=root/LOCK_NAME
        if path.is_symlink():raise MaintenanceBusy('Unsafe maintenance lock path')
        fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        self.file=os.fdopen(fd,'r+b',buffering=0)
        try:
            if os.fstat(fd).st_size==0:self.file.write(b'0')
            self.file.seek(0)
            if os.name=='nt':
                import ctypes,msvcrt
                from ctypes import wintypes
                class Overlapped(ctypes.Structure):
                    _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                              ('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                lock=kernel.LockFileEx
                lock.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
                lock.restype=wintypes.BOOL
                self._overlapped=Overlapped()
                # LOCKFILE_FAIL_IMMEDIATELY; add EXCLUSIVE only for maintenance.
                if not lock(msvcrt.get_osfhandle(fd),1 if runtime else 3,0,1,0,ctypes.byref(self._overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                import fcntl
                fcntl.flock(fd,(fcntl.LOCK_SH if runtime else fcntl.LOCK_EX)|fcntl.LOCK_NB)
            if runtime and (root/PENDING_RESTORE).exists():
                self.close()
                raise MaintenanceBusy('Interrupted restore requires offline recovery before runtime startup')
        except OSError as exc:
            self.file.close()
            raise MaintenanceBusy('Profile is active. Stop API, workers and CLI runtimes before offline backup, restore or erasure.') from exc

    def close(self):
        if self.file.closed:return
        try:
            self.file.seek(0)
            if os.name=='nt':
                # Closing the handle releases its LockFileEx byte-range lock.
                pass
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
        finally:self.file.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class ProfileLeases:
    """Lock both profile data and any separately configured installed-skill root."""
    def __init__(self,data_dir,skills_dir=None,*,runtime=False):
        self.leases=[]
        roots={Path(data_dir).resolve()}
        if skills_dir is not None:roots.add(Path(skills_dir).resolve())
        try:
            for root in sorted(roots):self.leases.append(ProfileLease(root,runtime=runtime))
        except BaseException:
            self.close()
            raise
    def close(self):
        for lease in reversed(self.leases):lease.close()
        self.leases=[]
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __del__(self):
        try:self.close()
        except Exception:pass
