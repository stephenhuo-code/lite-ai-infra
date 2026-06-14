# S1 Plan 5:data-pipeline-service(契约先行的异步作业薄壳,出口·服务化)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `data-pipeline-service` —— `data-pipeline.yaml` 契约先行,把已建成并云上验收的 `pipelines/data_prep.run_prepare` 包成**异步作业**服务:`POST /v1/data/prepare`(can() 同步过闸 → 立即返回 job_id)+ `GET /v1/data/jobs/{id}`(查状态)。达成 S1 服务化出口的第三个服务。

**Architecture(ADR-018):** S1 **不引入调度框架** —— detached 子进程 + 状态文件 `JobStore` + 单槽串行队列。可演进性来自**契约 + `JobRunner` 端口**两道稳定边界,固化五条不变量(异步 submit/poll 契约、`JobRunner` 端口、服务端不透明 job_id、含 `queued` 的后端中立状态、can() 同步边界 + worker 内复检)。S2a 在 `JobRunner` 端口下把 `SubprocessJobRunner` 换成 `ArgoJobRunner`,契约/SDK/CLI 零改。沿用 Plan 3/4 范式:契约(OpenAPI 3.1)→ datamodel-codegen → 脚手架 app(/docs)→ can()+审计 → 挂 gateway → 漂移守卫(运行时 openapi ⊆ 契约,CI)。分层 `services → pipelines → libs` 不变;作业/状态属 services 层(worker 是 service 入口,import pipelines.run_prepare)。

**Tech Stack:** FastAPI(脚手架工厂)、datamodel-codegen(仅模型)、`pipelines/data_prep`(后端实现)、boto3/Lance(经 run_prepare)、pytest 两层(unit / integration-MinIO)、Data-Juicer(subprocess,集成测试用 `DJ_BIN` seam 桩)。

**端口/env:** data-pipeline **8003**;env `JOBS_DIR`(状态文件根)、`OSS_*`/`DATA_BUCKET`/`AUDIT_BUCKET`(worker 传给 run_prepare)、`LITEAI_JWKS_URL`(验签)、`DJ_BIN`(DJ 可执行,默认 `dj-process`)。

**身份传递:** gateway 边缘验签 → 透传 bearer;本服务共享依赖再验一次(纵深);worker 用提交时快照的 `(enterprise, group, role, sub)` 重建 `Context` 做 run_prepare 内 can() 复检(角色撤销新鲜度依赖 token 生命周期/Spike A,S1 可接受)。

---

### Task 1:契约 `data-pipeline.yaml` 先行 + codegen 接线

**Files:**
- 创建:`contracts/openapi/data-pipeline.yaml`
- 修改:`Makefile`(`gen` 目标追加第三条 codegen)
- 生成:`libs/contracts_gen/data_pipeline_models.py`(codegen 产物,提交)

- [x] **步骤 1:写契约**(异步:POST 返 `202` + Job;状态枚举含 `queued`——不变量 1/4)(注:路径参数统一为 `{job_id}` 以与 app handler/漂移守卫对齐)

```yaml
# contracts/openapi/data-pipeline.yaml
openapi: 3.1.0
info: {title: data-pipeline, version: 0.1.0}
paths:
  /v1/data/prepare:
    post:
      summary: 提交数据准备作业(异步;立即返回 job,不阻塞)
      requestBody: {required: true, content: {application/json: {schema: {$ref: '#/components/schemas/PrepareJobRequest'}}}}
      responses:
        '202': {description: accepted, content: {application/json: {schema: {$ref: '#/components/schemas/Job'}}}}
        '401': {description: unauthenticated}
        '403': {description: forbidden}
  /v1/data/jobs/{id}:
    get:
      parameters: [{name: id, in: path, required: true, schema: {type: string}}]
      responses:
        '200': {description: job, content: {application/json: {schema: {$ref: '#/components/schemas/Job'}}}}
        '403': {description: forbidden}
        '404': {description: not found}
components:
  schemas:
    PrepareJobRequest:
      type: object
      required: [dataset, group_id, tar_dir]
      properties:
        dataset: {type: string, pattern: '^[a-z0-9][a-z0-9_-]{0,63}$'}
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        tar_dir: {type: string}                       # S1: 管线宿主机 ops 路径(ADR-018);S2a 改 OSS raw 引用
        np: {type: [integer, 'null'], minimum: 1}
        process: {type: [array, 'null'], items: {type: object}}   # Layer 1 DJ 算子(spec §8;build_recipe(process=…))
    Job:
      type: object
      required: [id, status, terminal, dataset, group_id, enterprise_id]
      properties:
        id: {type: string}
        status: {type: string, enum: [queued, running, succeeded, failed]}
        terminal: {type: boolean}     # 派生:status∈{succeeded,failed}。客户端按此判终态(ADR-018 不变量 4;S2a 加新终态如 cancelled 不破坏轮询)
        dataset: {type: string}
        group_id: {type: string, pattern: '^g-[0-9a-z]+$'}
        enterprise_id: {type: string, pattern: '^e-[0-9a-z]+$'}
        rows_in: {type: [integer, 'null']}
        rows_written: {type: [integer, 'null']}
        lance_uri: {type: [string, 'null']}
        error: {type: [string, 'null']}
        created_at: {type: [string, 'null']}
        updated_at: {type: [string, 'null']}
```

- [x] **步骤 2:`Makefile` 的 `gen` 目标追加**(沿用 `--disable-timestamp` 保 freshness 门禁确定性):
  `&& uv run datamodel-codegen --disable-timestamp --input contracts/openapi/data-pipeline.yaml --input-file-type openapi --output libs/contracts_gen/data_pipeline_models.py`
- [x] **步骤 3:`make gen` 生成模型,确认 `git diff` 无残留**(freshness 门禁口径;实测二次 gen 无 drift);`oasdiff` warn 门禁自动覆盖新契约(无破坏性变更基线)。
- [x] **步骤 4:提交** `feat(contracts): data-pipeline.yaml — async prepare/job contract + codegen`

---

### Task 2:`PrepareRequest` 透传 `process`(Layer 1 端到端打通,TDD)

> 现状:`run_prepare` 调 `build_recipe(jsonl, cleaned, np)` 未透传 `process`;契约要暴露算子自定义(owner 决策),需把 `process` 从请求一路带到 `build_recipe`。

**Files:** 修改:`pipelines/data_prep/runner.py`、`tests/pipelines/test_runner.py`(加用例)

- [x] **步骤 1:写失败测试**(注入 fake `build_recipe` 断言收到 `process`;happy path 已有,复用 seam)

```python
# 追加到 tests/pipelines/test_runner.py
def test_process_override_passed_to_recipe(tmp_path, monkeypatch):
    seen = {}
    import pipelines.data_prep.runner as R
    monkeypatch.setattr(R, "build_recipe",
                        lambda inp, out, np, process=None: seen.update(process=process) or "x: 1")
    sink = MemoryAuditSink(); calls = []
    ctx = parse_context("u-alice", ["/e-0001/g-0001/members"])
    req = _req(tmp_path, process=[{"text_length_filter": {"min_len": 9}}])
    run_prepare(ctx, req, AuditWriter(sink), **_ok_fakes(calls))
    assert seen["process"] == [{"text_length_filter": {"min_len": 9}}]
```
（`_req` 加 `process` 透传到 `PrepareRequest`;默认 `None`。）

- [x] **步骤 2:跑红**;**步骤 3:实现** —— `PrepareRequest` 加 `process: list[dict] | None = None`;`run_prepare` 改 `recipe_path.write_text(build_recipe(..., req.np, process=req.process))`。
- [x] **步骤 4:跑绿**(原 3 + 新 1 = 4 passed);**步骤 5:提交** `feat(pipelines): thread DJ process override through run_prepare`

---

### Task 3:`JobSpec` + `JobStore`(状态文件存储,TDD)

**Files:** 创建:`services/data_pipeline_service/__init__.py`、`services/data_pipeline_service/jobs.py`、`tests/services/data_pipeline/__init__.py`、`tests/services/data_pipeline/test_store.py`

- [x] **步骤 1:写失败测试**(create→queued、update 转状态、read 投影、oldest_queued FIFO、running_count、未知 id 返 None)

```python
# tests/services/data_pipeline/test_store.py
from services.data_pipeline_service.jobs import JobSpec, JobStore

def _spec(jid="job-1", **kw):
    d = dict(job_id=jid, dataset="cc3m", group_id="g-0001", enterprise_id="e-0001",
             role="member", sub="u-alice", tar_dir="/d", np=3, process=None)
    d.update(kw); return JobSpec(**d)

def test_create_then_read_is_queued(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    r = s.read("job-1")
    assert r["status"] == "queued" and r["dataset"] == "cc3m" and r["enterprise_id"] == "e-0001"
    assert r["created_at"] and r["rows_written"] is None and r["terminal"] is False

def test_update_terminal_fields(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    s.update("job-1", "succeeded", rows_in=15138, rows_written=15000, lance_uri="s3://b/x.lance")
    r = s.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 15000 and r["lance_uri"].endswith(".lance")
    assert r["terminal"] is True

def test_running_jobs_lists_pid(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec())
    s.update("job-1", "running", pid=4242)
    assert s.running_jobs() == [("job-1", 4242)]

def test_oldest_queued_and_running_count(tmp_path):
    s = JobStore(str(tmp_path))
    s.create(_spec("job-1")); s.create(_spec("job-2"))
    assert s.running_count() == 0
    assert s.oldest_queued() == "job-1"          # FIFO(按 created_at)
    s.update("job-1", "running")
    assert s.running_count() == 1 and s.oldest_queued() == "job-2"

def test_read_unknown_is_none(tmp_path):
    assert JobStore(str(tmp_path)).read("nope") is None

def test_load_spec_roundtrip(tmp_path):
    s = JobStore(str(tmp_path)); s.create(_spec(process=[{"a": 1}]))
    sp = s.load_spec("job-1")
    assert sp.tar_dir == "/d" and sp.role == "member" and sp.process == [{"a": 1}]
```

- [x] **步骤 2:跑红**;**步骤 3:实现**(`<root>/<id>/spec.json` 由 create 一次写;`status.json` 初始 queued、后续 update;read = 投影合并;时间戳 UTC ISO)

```python
# services/data_pipeline_service/jobs.py
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

_PUBLIC = ("rows_in", "rows_written", "lance_uri", "error")

@dataclass(frozen=True)
class JobSpec:
    job_id: str
    dataset: str
    group_id: str
    enterprise_id: str
    role: str            # 提交时调用者在该组的角色快照(worker 复检 can() 用)
    sub: str
    tar_dir: str
    np: int
    process: list[dict] | None = None

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class JobStore:
    """状态文件作业存储(ADR-018:v1 无 PG)。spec.json 写一次;status.json 由
    service(queued→running)与 worker(running→终态)分时写,无并发写者。"""
    def __init__(self, root: str):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(self, spec: JobSpec) -> None:
        d = self.job_dir(spec.job_id); d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(asdict(spec)))
        ts = _now()
        self._write_status(spec.job_id, {"status": "queued", "created_at": ts, "updated_at": ts,
                                         **{k: None for k in _PUBLIC}})

    def _write_status(self, job_id: str, status_obj: dict) -> None:
        (self.job_dir(job_id) / "status.json").write_text(json.dumps(status_obj))

    def update(self, job_id: str, status: str, **fields) -> None:
        cur = json.loads((self.job_dir(job_id) / "status.json").read_text())
        cur.update(status=status, updated_at=_now(), **fields)
        self._write_status(job_id, cur)

    def load_spec(self, job_id: str) -> JobSpec | None:
        p = self.job_dir(job_id) / "spec.json"
        return JobSpec(**json.loads(p.read_text())) if p.exists() else None

    def read(self, job_id: str) -> dict | None:
        d = self.job_dir(job_id)
        if not (d / "status.json").exists():
            return None
        spec = json.loads((d / "spec.json").read_text())
        st = json.loads((d / "status.json").read_text())
        return {"id": job_id, "dataset": spec["dataset"], "group_id": spec["group_id"],
                "enterprise_id": spec["enterprise_id"], "status": st["status"],
                "terminal": st["status"] in ("succeeded", "failed"),   # 派生:客户端按此判终态(ADR-018 不变量 4)
                "created_at": st["created_at"], "updated_at": st["updated_at"],
                **{k: st.get(k) for k in _PUBLIC}}

    def _all_status(self):
        for d in self.root.iterdir():
            sp = d / "status.json"
            if sp.exists():
                yield d.name, json.loads(sp.read_text())

    def running_count(self) -> int:
        return sum(1 for _, st in self._all_status() if st["status"] == "running")

    def running_jobs(self) -> list[tuple[str, int | None]]:
        """(job_id, pid) of status==running —— 供 PID 看门狗回收孤儿(ADR-018)。"""
        return [(jid, st.get("pid")) for jid, st in self._all_status() if st["status"] == "running"]

    def oldest_queued(self) -> str | None:
        q = [(st["created_at"], jid) for jid, st in self._all_status() if st["status"] == "queued"]
        return min(q)[1] if q else None
```

- [x] **步骤 4:跑绿** → 全 passed;**步骤 5:提交** `feat(data-pipeline): JobSpec + status-file JobStore (ADR-018)`

---

### Task 4:`JobRunner` 端口 + `SubprocessJobRunner`(单槽串行,TDD)

> 不变量 2:`submit`/`get` **都走端口**;不变量 3:job_id 服务端生成不透明串(handler 生成,见 Task 6)。串行=单槽(owner 决策);dispatch 可被后台线程或 submit 触发,本身是纯逻辑可单测。

**Files:** 创建:`services/data_pipeline_service/scheduler.py`、`tests/services/data_pipeline/test_scheduler.py`

- [x] **步骤 1:写失败测试**(submit 非阻塞即返;空槽时 dispatch 标 running 并 spawn;有 running 时不再 spawn=串行;spawn 用 seam 注入 fake)

```python
# tests/services/data_pipeline/test_scheduler.py
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
```

- [x] **步骤 2:跑红**;**步骤 3:实现**(`spawn` 默认 `subprocess.Popen(..., start_new_session=True)` = detached → "服务挂管线不挂";`worker_argv` 默认指向 Task 5 的 worker 模块)

```python
# services/data_pipeline_service/scheduler.py
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
```

- [x] **步骤 4:跑绿** → 全 passed;**步骤 5:提交** `feat(data-pipeline): JobRunner port + SubprocessJobRunner (serial, detached)`

---

### Task 5:worker 模块 —— 调 `run_prepare` + 写终态(TDD)

> worker = service 层 detached 入口,import `pipelines.run_prepare`(分层合法)。用 spec 快照重建 `Context`(run_prepare 内 can() 复检 = 纵深防御,不变量 5);run_prepare 自带 allow/fail 审计,故 worker 不重复审计。

**Files:** 创建:`services/data_pipeline_service/worker.py`、`tests/services/data_pipeline/test_worker.py`

- [x] **步骤 1:写失败测试**(注入 fake run_prepare:成功→写 succeeded + 字段;PermissionError→failed;其他异常→failed;断言用快照重建的 ctx 角色正确)

```python
# tests/services/data_pipeline/test_worker.py
import pytest
from services.data_pipeline_service.jobs import JobSpec, JobStore
from services.data_pipeline_service import worker as W

def _seed(tmp_path, **kw):
    store = JobStore(str(tmp_path))
    sp = JobSpec("job-1", "cc3m", "g-0001", "e-0001", "member", "u-a", "/d", 3, kw.get("process"))
    store.create(sp); store.update("job-1", "running")
    return store

def test_success_writes_terminal(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    seen = {}
    def fake_run_prepare(ctx, req, audit):
        seen["role"] = ctx.role_in.__self__ and ctx.user
        seen["ctx_role"] = ctx.role_in(req.__class__ and __import__("libs.identity.ids", fromlist=["EnterpriseId"]).EnterpriseId("e-0001"),
                                       __import__("libs.identity.ids", fromlist=["GroupId"]).GroupId("g-0001"))
        return {"rows_in": 15138, "rows_written": 15000, "lance_uri": "s3://b/cc3m.lance"}
    monkeypatch.setattr(W, "run_prepare", fake_run_prepare)
    monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 15000 and r["lance_uri"].endswith(".lance")
    assert seen["ctx_role"] == "member"          # 快照角色重建正确

def test_permission_error_marks_failed(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    def boom(ctx, req, audit): raise PermissionError("cross-group")
    monkeypatch.setattr(W, "run_prepare", boom); monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "failed" and "cross-group" in r["error"]

def test_generic_error_marks_failed(tmp_path, monkeypatch):
    store = _seed(tmp_path)
    monkeypatch.setattr(W, "run_prepare", lambda *a: (_ for _ in ()).throw(RuntimeError("dj exit=1")))
    monkeypatch.setattr(W, "_audit_writer", lambda: None)
    W.run_job(str(store.job_dir("job-1")))
    assert store.read("job-1")["status"] == "failed"
```
> 注:上面 `seen["ctx_role"]` 写得啰嗦只为单测内联断言;实现期可在测试里直接 `from libs.identity.ids import EnterpriseId, GroupId` 顶部导入简化。

- [x] **步骤 2:跑红**;**步骤 3:实现**(凭据/桶走 env,同 `pipelines/data_prep/__main__.py`;`_audit_writer()` 抽成可 monkeypatch 的 seam)

```python
# services/data_pipeline_service/worker.py
"""detached 作业 worker:python -m services.data_pipeline_service.worker --job-dir <dir>
读 spec → 重建 Context(快照角色)→ run_prepare(内部 can() 复检 + 审计)→ 写终态。"""
from __future__ import annotations
import argparse, os, sys
import boto3
from libs.identity.context import Context, Membership
from libs.identity.ids import EnterpriseId, GroupId
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from pipelines.data_prep.runner import PrepareRequest, run_prepare
from services.data_pipeline_service.jobs import JobStore

def _audit_writer() -> AuditWriter:
    endpoint = os.environ["OSS_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint,
                      aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                      aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                      aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                      region_name=os.getenv("OSS_REGION", "cn-hangzhou"),
                      config=oss_boto3_config(endpoint))
    return AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=s3))

def run_job(job_dir: str) -> None:
    root, job_id = os.path.dirname(job_dir.rstrip("/")), os.path.basename(job_dir.rstrip("/"))
    store = JobStore(root)
    spec = store.load_spec(job_id)
    ctx = Context(user=spec.sub, memberships=[
        Membership(EnterpriseId(spec.enterprise_id), GroupId(spec.group_id), spec.role)])
    req = PrepareRequest(
        tar_dir=spec.tar_dir, work_dir=str(store.job_dir(job_id) / "work"),
        bucket=os.environ["DATA_BUCKET"], enterprise_id=spec.enterprise_id,
        group_id=spec.group_id, dataset=spec.dataset, np=spec.np,
        oss_endpoint=os.environ["OSS_ENDPOINT"], access_key=os.environ["OSS_ACCESS_KEY"],
        secret_key=os.environ["OSS_SECRET_KEY"], session_token=os.getenv("OSS_SESSION_TOKEN"),
        region=os.getenv("OSS_REGION", "cn-hangzhou"), process=spec.process)
    try:
        out = run_prepare(ctx, req, _audit_writer())
        store.update(job_id, "succeeded", rows_in=out["rows_in"],
                     rows_written=out["rows_written"], lance_uri=out["lance_uri"])
    except PermissionError as e:
        store.update(job_id, "failed", error=f"forbidden: {e}")
    except Exception as e:
        store.update(job_id, "failed", error=str(e))

def main() -> int:
    ap = argparse.ArgumentParser("data-pipeline-worker")
    ap.add_argument("--job-dir", required=True)
    run_job(ap.parse_args().job_dir)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [x] **步骤 4:跑绿** → 全 passed;**步骤 5:提交** `feat(data-pipeline): detached worker — run_prepare + terminal status`

---

### Task 6:服务 app —— `POST /v1/data/prepare` + `GET /v1/data/jobs/{id}`(TDD)

> can() 在**同步边界**(deny→403 零副作用 + 审计 deny;allow 委托 worker 内审计,不重复)。企业从 token 推导(隐藏,单企业守卫,镜像 metadata-service)。后台 dispatcher 线程在 lifespan 起,空闲推进队列。

**Files:** 创建:`services/data_pipeline_service/app.py`、`services/data_pipeline_service/main.py`、`tests/services/data_pipeline/test_app.py`;修改:`services/_scaffold/auth.py`(加共享 `enterprise_of`)、`services/metadata_service/app.py`(改用 `enterprise_of`,删本地 `_enterprise`)

- [x] **步骤 1:写失败测试**(seam 开启;happy→202+queued/running、job_id 不透明;跨企业 submit→403 零副作用(store 空)+审计 deny【修正:企业从 token 推导,跨企业 POST 结构上不可能,改测跨组 deny】;GET 本组→200、跨组→403、未知→404;暴露 process)

```python
# tests/services/data_pipeline/test_app.py
import json, pytest
from fastapi.testclient import TestClient
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore

class MemSink:
    def __init__(self): self.items = []
    def put(self, key, body): self.items.append((key, body))

@pytest.fixture(autouse=True)
def _seam(monkeypatch): monkeypatch.setenv("LITEAI_ALLOW_TEST_CLAIMS", "1")

def _client(tmp_path):
    from libs.audit.oss_audit import AuditWriter
    from services.data_pipeline_service.scheduler import SubprocessJobRunner
    store = JobStore(str(tmp_path)); sink = MemSink()
    runner = SubprocessJobRunner(store, spawn=lambda argv, **kw: None)   # 不真 spawn
    return TestClient(build_app(runner=runner, audit=AuditWriter(sink))), store, sink

def _hdr(sub, groups): return {"x-test-claims": json.dumps({"sub": sub, "groups": groups})}

def test_submit_returns_202_job(tmp_path):
    c, store, _ = _client(tmp_path)
    r = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "tar_dir": "/d"})
    assert r.status_code == 202
    body = r.json()
    assert body["id"] and body["enterprise_id"] == "e-0001" and body["status"] in ("queued", "running")
    assert store.read(body["id"]) is not None        # 已入库

def test_cross_enterprise_denied_no_side_effect(tmp_path):
    c, store, sink = _client(tmp_path)
    r = c.post("/v1/data/prepare", headers=_hdr("u-x", ["/e-0099/g-0001/members"]),
               json={"dataset": "cc3m", "group_id": "g-0001", "tar_dir": "/d"})
    assert r.status_code == 403
    assert list(store.root.iterdir()) == []          # 零副作用:无作业落库
    assert json.loads(sink.items[0][1])["decision"] == "deny"   # deny 仍审计

def test_get_same_group_ok_cross_group_403_unknown_404(tmp_path):
    c, store, _ = _client(tmp_path)
    jid = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"dataset": "cc3m", "group_id": "g-0001", "tar_dir": "/d"}).json()["id"]
    assert c.get(f"/v1/data/jobs/{jid}", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).status_code == 200
    assert c.get(f"/v1/data/jobs/{jid}", headers=_hdr("u-b", ["/e-0001/g-0002/members"])).status_code == 403
    assert c.get("/v1/data/jobs/nope", headers=_hdr("u-a", ["/e-0001/g-0001/members"])).status_code == 404

def test_process_override_persisted(tmp_path):
    c, store, _ = _client(tmp_path)
    jid = c.post("/v1/data/prepare", headers=_hdr("u-a", ["/e-0001/g-0001/members"]),
                 json={"dataset": "cc3m", "group_id": "g-0001", "tar_dir": "/d",
                       "process": [{"text_length_filter": {"min_len": 9}}]}).json()["id"]
    assert store.load_spec(jid).process == [{"text_length_filter": {"min_len": 9}}]
```

- [x] **步骤 2:跑红**
- [x] **步骤 3:抽取共享 `enterprise_of`**(复审意见:第二次复制 → 抽到 `_scaffold`;纯函数零跨服务 import 风险)

```python
# 追加 services/_scaffold/auth.py(metadata-service 改 import 它、删本地 _enterprise;其测试守回归)
from fastapi import HTTPException
from libs.identity.context import Context

def enterprise_of(ctx: Context) -> str:
    """v1 单企业:从 token 推导调用者企业;属 0/多个企业显式拒(宪法 §3.7,不静默挑第一个)。"""
    ents = []
    for m in ctx.memberships:
        if m.enterprise_id not in ents:
            ents.append(m.enterprise_id)
    if not ents:
        raise HTTPException(status_code=403, detail="no enterprise membership")
    if len(ents) > 1:
        raise HTTPException(status_code=400, detail="ambiguous enterprise membership; v1 single-enterprise only")
    return ents[0]
```

- [x] **步骤 4:实现 app**(job_id=`job-`+uuid4 hex 服务端生成=不变量 3;deny 审计走 AuditWriter;dispatch 由 runner 自管 handler 不碰)

```python
# services/data_pipeline_service/app.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from libs.authz.engine import can
from libs.authz.types import Resource
from libs.audit.oss_audit import AuditWriter, AuditEvent
from libs.contracts_gen.data_pipeline_models import PrepareJobRequest
from libs.identity.context import Context
from libs.identity.ids import EnterpriseId, GroupId
from services._scaffold.app import make_service_app
from services._scaffold.auth import context_from_request, enterprise_of   # enterprise_of 本 plan 抽自 metadata-service
from services.data_pipeline_service.jobs import JobSpec

def _audit_deny(audit: AuditWriter, ctx: Context, ent: str, gid: str, dataset: str, reason: str) -> None:
    audit.write(AuditEvent(ts=datetime.now(timezone.utc).isoformat(), enterprise_id=ent, group_id=gid,
                           actor_user=ctx.user, actor_role=ctx.role_in(EnterpriseId(ent), GroupId(gid)) or "none",
                           action="data.prepare", resource_uri=f"dataset/{dataset}", decision="deny",
                           override=False, reason=reason, metadata={}))

def build_app(runner, audit: AuditWriter):
    app = make_service_app(title="data-pipeline-service", version="0.1.0")

    @app.post("/v1/data/prepare", status_code=202)
    def prepare(body: PrepareJobRequest, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        res = Resource(kind="dataset", enterprise_id=EnterpriseId(ent), group_id=GroupId(body.group_id))
        d = can(ctx, "data.prepare", res)
        if not d.allow:                       # deny → 零副作用 + 审计
            _audit_deny(audit, ctx, ent, body.group_id, body.dataset, d.reason)
            return JSONResponse(status_code=403, content={"reason": d.reason})
        job_id = "job-" + uuid.uuid4().hex[:16]      # 服务端不透明 id(不变量 3)
        spec = JobSpec(job_id=job_id, dataset=body.dataset, group_id=body.group_id, enterprise_id=ent,
                       role=ctx.role_in(EnterpriseId(ent), GroupId(body.group_id)) or "member",
                       sub=ctx.user, tar_dir=body.tar_dir, np=body.np or 3, process=body.process)
        runner.submit(spec)
        return runner.get(job_id)

    @app.get("/v1/data/jobs/{job_id}")
    def get_job(job_id: str, ctx: Context = Depends(context_from_request)):
        ent = enterprise_of(ctx)
        job = runner.get(job_id)
        if job is None or job["enterprise_id"] != ent:
            raise HTTPException(status_code=404, detail="not found")   # 跨企业=不存在(不泄漏)
        res = Resource(kind="job", enterprise_id=EnterpriseId(ent), group_id=GroupId(job["group_id"]))
        if not can(ctx, "data.read", res).allow:                      # 跨组 → 403
            return JSONResponse(status_code=403, content={"reason": "cross-group"})
        return job

    return app
```

```python
# services/data_pipeline_service/main.py  启动:uvicorn services.data_pipeline_service.main:app --port 8003
import os
import boto3
from libs.audit.oss_audit import OssAuditSink, AuditWriter, oss_boto3_config
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore
from services.data_pipeline_service.scheduler import SubprocessJobRunner

_endpoint = os.environ["OSS_ENDPOINT"]
_s3 = boto3.client("s3", endpoint_url=_endpoint, aws_access_key_id=os.environ["OSS_ACCESS_KEY"],
                   aws_secret_access_key=os.environ["OSS_SECRET_KEY"],
                   aws_session_token=os.getenv("OSS_SESSION_TOKEN"),
                   region_name=os.getenv("OSS_REGION", "cn-hangzhou"), config=oss_boto3_config(_endpoint))
# runner 自管后台调度线程(队列推进 + PID 看门狗);main.py 对 runner 实现无感 →
# S2a 唯一改动 = 下一行换 ArgoJobRunner(build_app 不变)。
_runner = SubprocessJobRunner(JobStore(os.environ.get("JOBS_DIR", "./.jobs")), dispatch_interval=2.0)
app = build_app(runner=_runner, audit=AuditWriter(OssAuditSink(bucket=os.environ["AUDIT_BUCKET"], client=_s3)))
```

- [x] **步骤 5:跑绿** → 全 passed(含并发/看门狗用例);**步骤 6:提交** `feat(data-pipeline-service): async prepare/job-status app on scaffold (can() boundary)`

---

### Task 7:接线 —— gateway 路由 + dev 编排 + swagger + 漂移守卫(TDD)

**Files:** 修改:`services/gateway/main.py`、`scripts/dev_services.sh`、`Makefile`(`run-data-pipeline`)、`README.md`(端口表);创建:`tests/services/data_pipeline/test_drift.py`

- [x] **步骤 1:gateway 加路由**(Plan 3 的 async 反代已转发 body,无需改 proxy):`services/gateway/main.py` 的 routes 追加 `"/v1/data": os.environ.get("DATA_PIPELINE_URL", "http://localhost:8003")`,删去该处 Plan 5 占位注释。
- [x] **步骤 2:`scripts/dev_services.sh`**:`SERVICES` 加 `"data-pipeline|8003|services.data_pipeline_service.main:app"`;`_env_for` 加 `data-pipeline)` 分支(`JOBS_DIR` + `OSS_*`/`DATA_BUCKET`/`AUDIT_BUCKET` + `LITEAI_JWKS_URL`,本地指向 MinIO);gateway 分支 env 追加 `DATA_PIPELINE_URL=http://localhost:8003`。
- [x] **步骤 3:`Makefile`** 加 `run-data-pipeline`(前台 + --reload,带本地 MinIO env);`make api-docs` 经 `swagger_urls.py` 自动纳入 `data-pipeline.yaml`(无需改脚本);README 端口表加 data-pipeline 8003。
- [x] **步骤 4:漂移守卫测试**(运行时 openapi ⊆ 契约,L3 活样例)

```python
# tests/services/data_pipeline/test_drift.py
import yaml, pathlib
from fastapi.testclient import TestClient
from libs.audit.oss_audit import AuditWriter
from services._scaffold.drift import assert_openapi_subset_of_contract
from services.data_pipeline_service.app import build_app
from services.data_pipeline_service.jobs import JobStore
from services.data_pipeline_service.scheduler import SubprocessJobRunner

def test_runtime_matches_contract(tmp_path):
    class _S:
        def put(self, k, b): ...
    app = build_app(SubprocessJobRunner(JobStore(str(tmp_path)), spawn=lambda *a, **k: None), AuditWriter(_S()))
    contract = yaml.safe_load(pathlib.Path("contracts/openapi/data-pipeline.yaml").read_text())
    assert_openapi_subset_of_contract(TestClient(app).app.openapi(), contract)
```

- [x] **步骤 5:提交** `feat(data-pipeline): wire into gateway + dev orchestration + drift guard`

---

### Task 8:集成测试(真 MinIO,DJ seam)+ E2E + 验收 + 合并

**Files:** 创建:`tests/integration/test_data_pipeline_e2e.py`

- [x] **步骤 1:集成测试**(标 `integration`;真 MinIO + `DJ_BIN` 桩=把输入 jsonl 拷成 `cleaned/cleaned.jsonl` 模拟 DJ → run_prepare 真写 Lance on MinIO;**同步驱动 worker.run_job 直跑**避免子进程不确定性,真验"提交参数→Lance 产物→状态终态")

```python
# tests/integration/test_data_pipeline_e2e.py
import io, json, os, tarfile, pytest
import lance
from services.data_pipeline_service.jobs import JobSpec, JobStore
from services.data_pipeline_service import worker as W
pytestmark = pytest.mark.integration

_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
                     "0000000c4944415408d763f8cfc0000003010100c9fe92ef0000000049454e44ae426082")

def _mk_tar(p):
    with tarfile.open(p, "w") as tf:
        for k, t in [("0", "a cat"), ("1", "blue sky")]:
            ti = tarfile.TarInfo(f"{k}.jpg"); ti.size = len(_PNG); tf.addfile(ti, io.BytesIO(_PNG))
            b = t.encode(); ti2 = tarfile.TarInfo(f"{k}.txt"); ti2.size = len(b); tf.addfile(ti2, io.BytesIO(b))

def test_prepare_job_to_lance_on_minio(tmp_path, minio_s3, minio_bucket, monkeypatch, dj_passthrough_bin):
    tar_dir = tmp_path / "tars"; tar_dir.mkdir(); _mk_tar(tar_dir / "s.tar")
    monkeypatch.setenv("DATA_BUCKET", minio_bucket); monkeypatch.setenv("AUDIT_BUCKET", minio_bucket)
    monkeypatch.setenv("OSS_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("OSS_ACCESS_KEY", "minio"); monkeypatch.setenv("OSS_SECRET_KEY", "minio123")
    monkeypatch.setenv("OSS_REGION", "us-east-1"); monkeypatch.setenv("DJ_BIN", dj_passthrough_bin)
    store = JobStore(str(tmp_path / "jobs"))
    store.create(JobSpec("job-1", "cc3m", "g-0001", "e-0001", "member", "u-a", str(tar_dir), 2, None))
    store.update("job-1", "running")
    W.run_job(str(store.job_dir("job-1")))
    r = store.read("job-1")
    assert r["status"] == "succeeded" and r["rows_written"] == 2
    ds = lance.dataset(r["lance_uri"], storage_options={
        "access_key_id": "minio", "secret_access_key": "minio123", "endpoint": "http://localhost:9000",
        "region": "us-east-1", "allow_http": "true", "virtual_hosted_style_request": "false"})
    assert ds.count_rows() == 2
```
> `dj_passthrough_bin` fixture:写一个临时可执行,解析 `--config recipe.yaml` 取 `dataset_path`/`export_path`,把输入 jsonl 原样写到 `<export_path>/cleaned.jsonl`(模拟 DJ 清洗为恒等)。放 `tests/conftest.py` 或 `tests/integration/conftest.py`,复用既有 `minio_s3/minio_bucket` fixture。

- [x] **步骤 2:跑** `make dev-up` 后 `uv run pytest -q -m integration`(新 1 + 既有全绿:8 passed);`uv run pytest -q && uv run lint-imports && bash scripts/ci_guards.sh` 全绿(101 unit + 分层 KEPT + guards exit 0;含 data-pipeline 层无越界、codegen freshness、漂移守卫)。
- [ ] **步骤 3:手动验收**——按文末 runbook 真起 `make up`,经 gateway 提交作业 → 轮询到 `succeeded` → 跨企业 403。贴输出。
- [ ] **步骤 4:requesting-code-review 子代理评审 → 修订**(宪法 §3.4/ADR-017:计划完成后强制隔离评审)。
- [ ] **步骤 5:回写状态**(本 plan checkbox 实时勾、spec §5.3/§9.3 Plan 5 标 ✅ + 服务化出口推进)+ 提交 `feat(data-pipeline-service): integration e2e + S1 service #3 done` + 合并。

---

## 验收对照

| 目标 | 任务 |
|---|---|
| 契约先行(`data-pipeline.yaml` + codegen) | Task 1 |
| Layer 1 配方自定义暴露(`process`) | Task 2(透传)+ Task 6(契约/handler) |
| 异步 submit→job_id(不变量 1) | Task 6 `POST` 202 + Task 4 非阻塞 submit |
| 查状态 `GET /v1/data/jobs/{id}` | Task 6 + Task 3 JobStore |
| `JobRunner` 端口(不变量 2,S2a 换 Argo) | Task 4 |
| 服务端不透明 job_id(不变量 3) | Task 6(`job-`+uuid) |
| 含 `queued` 的中立状态(不变量 4) | Task 1 契约 + Task 3 store |
| can() 同步边界 + worker 复检(不变量 5) | Task 6(边界 deny→403 零副作用)+ Task 5(worker 内 run_prepare 复检) |
| 串行单作业(owner 决策) | Task 4 单槽 dispatch |
| "服务挂管线不挂"(spec §2.2) | Task 4 detached spawn |
| 终态判定契约 `terminal`(不变量 4,复审) | Task 1 契约 + Task 3 read 投影 + runbook 按 terminal 轮询 |
| 并发安全:锁防同一作业起两次(复审,宪法 §3.9) | Task 4 `threading.Lock` + `test_concurrent_dispatch_spawns_once` |
| 孤儿 running 回收防队列死锁(复审) | Task 4 PID 看门狗 + `test_pid_watchdog_reaps_orphan` |
| DRY:`enterprise_of` 抽到 `_scaffold`(复审) | Task 6 步骤 3(metadata-service 同步改用) |
| 挂 gateway + 聚合 Swagger + 漂移守卫 | Task 7 |
| 端到端真产物(Lance on OSS) | Task 8 |

SDK/CLI(出口⑤)= Plan 6(由本契约生成)。

## 自审记录

- 占位符:无 TBD;每步含代码/命令/期望。`tar_dir` 的 S1 ops-路径性质与 S2a 收紧已在契约注释 + ADR-018 标明,非遗漏。
- 类型一致:`JobSpec`/`JobStore.{create,read,update,load_spec,oldest_queued,running_count,running_jobs,job_dir}`/`SubprocessJobRunner.{submit,get,dispatch}`(构造含 `spawn,worker_argv,pid_alive,dispatch_interval` seam)/`worker.run_job`/`build_app(runner,audit)` 签名在各 Task 调用处一一对齐;`PrepareRequest` 加 `process`、`Job` 加 `terminal` 后契约/store/handler 三处字段一致;`can()` action 用 `data.prepare`(写,同 run_prepare)/`data.read`(查),均依赖引擎"有组角色→放行"基线(libs/authz/engine.py 已验)。
- 分层:worker 在 services 层 import `pipelines.run_prepare` 合法;`services/data_pipeline_service` 不被 pipelines/libs 反向 import(lint-imports 守);`enterprise_of` 抽到 `_scaffold/auth.py`(复审采纳,纯函数零跨服务 import),metadata-service 同步改用。
- 边界:can() 同步边界 deny 零副作用(测试 `store.root` 空断言);allow 审计委托 worker 内 run_prepare(不重复);GET 跨企业返 404 不泄漏、跨组返 403。worker 复检用提交时角色快照 = 防 handler bug 纵深防御(非授权新鲜度,ADR-018 已登记撤销窗口)。
- 并发(复审采纳,宪法 §3.9):`dispatch` 全程持 `threading.Lock`(handler 线程 + 后台线程并发安全),`test_concurrent_dispatch_spawns_once` 真起多线程撞锁,不靠假对象掩盖。
- ADR 对齐:ADR-018 五条不变量逐条落到 Task(见验收对照);S1 已知限制(单副本/队列推进依赖服务/**孤儿 running 由 PID 看门狗回收防死锁**/授权撤销窗口/无取消)在 ADR Consequences + runbook 标注,S2a 解决。

---

## 手动验收 runbook(实现完成后照此验证)

> 原则(宪法 §3.2):证据先于断言。本服务套脚手架后,`make up` 自动带起、契约自动进 `make api-docs` 下拉(spec §9.2 runbook 模板)。

**前置:本地凭据用 MinIO**(dev compose 已起 MinIO);`make up` 后确认 4 服务运行(identity 8001 / metadata 8002 / data-pipeline 8003 / gateway 8090)。

```bash
make up                 # Keycloak/MinIO + Gravitino + 4 服务
make ps                 # 确认 data-pipeline 在 :8003 运行中
```

**验收 1 — Swagger**
- 聚合契约:`make api-docs` → http://localhost:8088 下拉应出现 `data-pipeline`(3 个 path 之外现 4 契约)。
- 运行时 /docs:http://localhost:8003/docs(见 `POST /v1/data/prepare`、`GET /v1/data/jobs/{id}`)。

**验收 2 — 端到端(经 gateway 反代,真 token + 异步作业)**
```bash
TOKEN=$(curl -fsS -d client_id=gateway -d client_secret=dev-secret -d username=alice \
  -d password=alice -d grant_type=password \
  http://localhost:8080/realms/lite-ai/protocol/openid-connect/token \
  | uv run python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
# 提交作业(tar_dir 用宿主机上一个小 tar 目录;DJ_BIN 桩或真 dj-venv 见下)
JOB=$(curl -fsS -X POST -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"dataset":"cc3m","group_id":"g-0001","tar_dir":"/tmp/tars"}' \
  http://localhost:8090/v1/data/prepare | uv run python -c 'import sys,json;print(json.load(sys.stdin)["id"])')   # A
echo "job=$JOB"
# 轮询直到 terminal(按派生布尔判终态,非字符串匹配 → S2a 加新终态不破坏此脚本)
for i in $(seq 1 30); do
  J=$(curl -fsS -H "Authorization: Bearer $TOKEN" http://localhost:8090/v1/data/jobs/$JOB)
  echo "  $(echo "$J" | uv run python -c 'import sys,json;print(json.load(sys.stdin)["status"])')"
  echo "$J" | uv run python -c 'import sys,json;sys.exit(0 if json.load(sys.stdin)["terminal"] else 1)' && break
  sleep 2
done                                                                                                              # B
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8090/v1/data/prepare                                   # C 无 token
```
期望:A=返回 `202` + 含 `id`/`status`(queued|running)/`enterprise_id=e-0001`;B=数轮后 `succeeded`,`GET` 返回含 `rows_written`/`lance_uri`(`s3://…/e-0001/g-0001/processed/cc3m.lance`);C=`401`。
> 本地无真 DJ:`make run-data-pipeline` 前 `export DJ_BIN=<passthrough 桩>`(Task 8 fixture 同款),或在云上 spike-ECS 用 `/opt/dj-venv/bin/dj-process` 真跑。

**验收 3 — 隔离(can() deny 边界 = 跨组)**
> 修正:企业从 caller token 推导(`enterprise_of`),跨**企业** POST 结构上不可能(token 为 e-0099 只能在 e-0099 内操作)。本端点的 deny-审计边界是**跨组**:caller 属 e-0001/g-0002,却提交到 g-0001。
```bash
# x-test-claims seam(仅本地,需 LITEAI_ALLOW_TEST_CLAIMS=1):caller 在 g-0002,提交 g-0001 → 跨组 deny
export LITEAI_ALLOW_TEST_CLAIMS=1
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'content-type: application/json' \
  -H 'x-test-claims: {"sub":"u-x","groups":["/e-0001/g-0002/members"]}' \
  -d '{"dataset":"cc3m","group_id":"g-0001","tar_dir":"/tmp/tars"}' \
  http://localhost:8003/v1/data/prepare                                                                          # D
```
期望:D=`403`(跨组 deny,零副作用 = 无作业落库 + 审计桶出现 `decision:deny`)。

**验收 4 — 漂移守卫**
```bash
uv run pytest tests/services/data_pipeline/ -q     # 期望全 passed,含 test_runtime_matches_contract
```

**收尾**:`make down`(停全部 + deps);`make api-docs-down`。

> **S1 已知限制(ADR-018,S2a 解决)**:单副本;queued 队列推进依赖服务在线(running 的 detached 作业不受重启影响);**孤儿 `running`(worker 被 OOM/硬杀)由 dispatch 内 PID 看门狗回收为 `failed` 释放槽**,跨重启的声明式自动对账属 S2a;提交后授权撤销窗口(worker 用快照角色复检);无取消/无 per-shard 重试;`tar_dir` 为宿主机 ops 路径。
