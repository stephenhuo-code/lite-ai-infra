import threading, types
from services.data_pipeline_service.jobs import JobSpec, JobStore
from services.data_pipeline_service.scheduler import SubprocessJobRunner

def _spec(jid): return JobSpec(jid, "cc3m", "g-0001", "e-0001", "member", "u-a", "/d", 3, None)

def _runner(tmp_path, alive=None):
    """alive=None → 所有 pid 视为活(默认);alive=set(...) → 仅集合内 pid 活(测看门狗)。
    spawn 仿 Popen 返回带 .pid 的对象。"""
    store = JobStore(str(tmp_path)); spawned = []; nxt = [1000]
    def _spawn(argv, **kw):
        spawned.append(argv); nxt[0] += 1
        return types.SimpleNamespace(pid=nxt[0])
    r = SubprocessJobRunner(store, spawn=_spawn, worker_argv=lambda d: ["WORKER", d],
                            pid_alive=(lambda p: True) if alive is None else (lambda p: p in alive))
    return store, r, spawned

def test_submit_returns_id_and_dispatches(tmp_path):
    store, r, spawned = _runner(tmp_path)
    jid = r.submit(_spec("job-1"))
    assert jid == "job-1" and store.read("job-1")["status"] == "running"   # 空槽 → 立即调度
    assert len(spawned) == 1 and spawned[0][0] == "WORKER"
    assert store.running_jobs()[0][1] is not None          # pid 已记录(看门狗依赖)

def test_serial_single_slot(tmp_path):
    store, r, spawned = _runner(tmp_path)
    r.submit(_spec("job-1")); r.submit(_spec("job-2"))
    assert store.read("job-1")["status"] == "running"
    assert store.read("job-2")["status"] == "queued" and len(spawned) == 1  # 槽被占 → 排队

def test_get_proxies_store(tmp_path):
    store, r, _ = _runner(tmp_path)
    r.submit(_spec("job-1"))
    assert r.get("job-1")["id"] == "job-1" and r.get("nope") is None

def test_dispatch_picks_next_when_slot_frees(tmp_path):
    store, r, spawned = _runner(tmp_path)
    r.submit(_spec("job-1")); r.submit(_spec("job-2"))
    store.update("job-1", "succeeded")                      # 模拟 worker 完成
    r.dispatch()
    assert store.read("job-2")["status"] == "running" and len(spawned) == 2

def test_concurrent_dispatch_spawns_once(tmp_path):        # 锁:8 线程并发 dispatch 只起 1 个(防竞态)
    store, r, spawned = _runner(tmp_path)
    for i in range(5): store.create(_spec(f"job-{i}"))
    ts = [threading.Thread(target=r.dispatch) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    running = [j for j in range(5) if store.read(f"job-{j}")["status"] == "running"]
    assert len(running) == 1 and len(spawned) == 1

def test_pid_watchdog_reaps_orphan(tmp_path):              # OOM/硬杀:running 的死 pid → failed 释放槽
    store, r, spawned = _runner(tmp_path, alive=set())     # 空集 = 所有 pid 已死
    r.submit(_spec("job-1"))                               # job-1 running + pid 记录
    r.submit(_spec("job-2"))                               # 触发 dispatch:看门狗回收 job-1 → 起 job-2
    assert store.read("job-1")["status"] == "failed" and "orphan" in store.read("job-1")["error"]
    assert store.read("job-2")["status"] == "running"
