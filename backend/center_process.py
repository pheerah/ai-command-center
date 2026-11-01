"""Bounded, cancellable processes. No shell interpolation and no token harvesting."""
from __future__ import annotations

import os
import signal
import subprocess
import shutil
import time
from pathlib import Path


def worker_env():
    # Preserve CLI-managed subscription login, never read auth files ourselves.
    allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'TMPDIR',
               'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
               'PROGRAMDATA', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'LANG', 'LC_ALL',
               'TERM', 'NO_COLOR', 'CI', 'PYTHONIOENCODING', 'PYTHONUTF8'}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


class WindowsJob:
    """Kill the owned tree even when its original root exits or owner crashes."""
    def __init__(self, proc):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong), ('flags', w.DWORD),
                        ('min_working_set', c.c_size_t), ('max_working_set', c.c_size_t), ('active_limit', w.DWORD),
                        ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                        ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle:
            raise OSError(c.get_last_error(), 'Cannot create owned process job')
        if not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info)) or not self.kernel.AssignProcessToJobObject(self.handle, w.HANDLE(int(proc._handle))):
            self.close()
            raise OSError(c.get_last_error(), 'Cannot enforce process-tree cleanup')

    def close(self):
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def terminate_tree(proc):
    if os.name == "nt":
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def execute(argv, cwd, log_path, timeout, tick, started, env_extra=None):
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError("Commands must be explicit argument arrays")
    if os.name == "nt" and argv[0] in ("npm", "npx", "npm.cmd", "npx.cmd"):
        name = argv[0].split('.')[0]
        shim = shutil.which(name + ".cmd")
        script = Path(shim).parent / "node_modules/npm/bin" / (name + "-cli.js") if shim else None
        if script is None or not script.is_file() or not shutil.which("node"):
            raise ValueError("npm/npx CLI is missing")
        argv = [shutil.which("node"), str(script), *argv[1:]]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = worker_env()
    env.update(env_extra or {})
    with log_path.open("wb") as output:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
        job = None
        try:
            if os.name == 'nt':
                job = WindowsJob(proc)
            started(proc.pid)
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if not tick():
                    terminate_tree(proc)
                    return {"code": None, "error": "cancelled_or_lease_lost", "pid": proc.pid}
                if time.monotonic() >= deadline:
                    terminate_tree(proc)
                    return {"code": None, "error": "timeout", "pid": proc.pid}
                time.sleep(0.1)
            if not tick():
                return {"code": None, "error": "cancelled_or_lease_lost", "pid": proc.pid}
            return {"code": proc.returncode, "error": None, "pid": proc.pid}
        finally:
            if job:
                job.close()
            terminate_tree(proc)
