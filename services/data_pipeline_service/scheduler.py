from __future__ import annotations
import os, subprocess, sys, threading, time
from typing import Protocol
from services.data_pipeline_service.jobs import JobSpec, JobStore

class JobRunner(Protocol):
    def submit(self, spec: JobSpec) -> str: ...
    def get(self, job_id: str) -> dict | None: ...

def _default_argv(job_dir: str) -> list[str]:
    return [sys.executable, "-m", "services.data_pipeline_service.worker", "--job-dir", job_dir]

def _detached(argv, **kw):
    return subprocess.Popen(argv, start_new_session=True, **kw)   # 脱离服务进程组(服务挂管线不挂)

def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True            # 存在但不可发信号 → 视为活
    return True

class SubprocessJobRunner:
    """S1 实现:状态文件 + detached 子进程 + 单槽串行 + PID 看门狗(ADR-018)。
    调度/队列推进(dispatch/后台线程/看门狗)为本类**私有**,不进 JobRunner 端口、不进 runtime;
    S2a 在同一端口换 ArgoJobRunner,契约/handler/main.py 编排不变。"""
    def __init__(self, store: JobStore, *, spawn=_detached, worker_argv=_default_argv,
                 pid_alive=_pid_alive, dispatch_interval: float | None = None):
        self.store, self._spawn, self._worker_argv, self._alive = store, spawn, worker_argv, pid_alive
        self._lock = threading.Lock()
        if dispatch_interval:                       # 生产:自管后台线程推进队列(main.py 无感)
            threading.Thread(target=self._loop, args=(dispatch_interval,), daemon=True).start()

    def _loop(self, interval: float) -> None:
        while True:
            time.sleep(interval); self.dispatch()

    def submit(self, spec: JobSpec) -> str:
        self.store.create(spec); self.dispatch(); return spec.job_id

    def get(self, job_id: str) -> dict | None:
        return self.store.read(job_id)

    def dispatch(self) -> None:
        """单槽串行 + 孤儿回收。全程持锁 → handler 线程与后台线程并发安全(防同一作业起两次)。"""
        with self._lock:
            for jid, pid in self.store.running_jobs():     # PID 看门狗:死 worker(OOM/硬杀)→ failed 释放槽
                if not self._alive(pid):
                    self.store.update(jid, "failed", error="worker died (orphan reaped)")
            if self.store.running_count() > 0:
                return
            jid = self.store.oldest_queued()
            if jid is None:
                return
            self.store.update(jid, "running")
            proc = self._spawn(self._worker_argv(str(self.store.job_dir(jid))))
            self.store.update(jid, "running", pid=getattr(proc, "pid", None))
