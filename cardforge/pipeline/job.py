"""后台任务与进度事件 —— GUI 的长耗时操作都走这里。

为什么需要它
------------
出图（ComfyUI 单张几十秒到几分钟）、实跑对局、整系列渲染都不可能塞进一个
HTTP 请求里。所以统一模式是：

::

    POST /api/art/generate   → 202 {"job": "j-0001"}
    GET  /api/events?job=j-0001  → SSE：progress / done / error

设计约束
--------
* **只用标准库**（``threading`` + ``queue``），不引入 asyncio/celery。
* ``fn`` 的返回值必须可 JSON 序列化；不可序列化时包一层 ``str``，**不抛**。
* 任务内部异常**绝不冒到 HTTP 线程**：捕获后写进 ``Job.error`` 并广播 ``error`` 事件。
* 事件带单调递增 ``seq``，``events()`` 支持从任意游标续读 —— 浏览器断线重连
  不丢进度（这是 SSE 最容易写错的地方）。
* ``cancel()`` 只是**协作式**标记：fn 可以通过 ``Job.cancelled()`` 自查。
  强杀线程在 Python 里做不到，这里不假装能做到。
"""
from __future__ import annotations

import inspect
import itertools
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

__all__ = ["Job", "JobManager", "manager", "STATUS"]

#: 任务状态机：queued → running → done | error | cancelled
STATUS = ("queued", "running", "done", "error", "cancelled")

_MAX_EVENTS_PER_JOB = 512
_KEEP_DONE = 64                     # 内存里保留最近完成的任务数


def _jsonable(value: Any) -> Any:
    """把任意返回值压成可 JSON 序列化的结构，失败退化成字符串。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:
            pass
    return str(value)


@dataclass
class Job:
    """一次后台任务。GUI 只读它，不碰线程。"""
    id: str
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""
    hint: str = ""
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0
    log: list = field(default_factory=list)

    # ── 内部状态（不参与序列化）──────────────────────────────────
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _events: deque = field(default_factory=deque, repr=False)
    _seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cond: threading.Condition = None  # type: ignore[assignment]

    # ── 事件 ────────────────────────────────────────────────────
    def emit(self, event: str, **data) -> dict:
        """追加一条事件并唤醒所有等待者。"""
        payload = {"job": self.id, "kind": self.kind, "seq": None,
                   "event": event, "ts": time.time(), "status": self.status,
                   "progress": round(self.progress, 4), "message": self.message}
        payload.update({k: _jsonable(v) for k, v in data.items()})
        with self._lock:
            self._seq += 1
            payload["seq"] = self._seq
            self._events.append(payload)
            while len(self._events) > _MAX_EVENTS_PER_JOB:
                self._events.popleft()
        cond = self._cond
        if cond is not None:
            with cond:
                cond.notify_all()
        return payload

    def cancelled(self) -> bool:
        """协作式取消：长任务应在循环里自查这个。"""
        return self._cancel.is_set()

    # ── 进度 ────────────────────────────────────────────────────
    def set_progress(self, value: float, message: str = "") -> None:
        try:
            v = float(value)
        except Exception:
            return
        if v > 1.0:                    # 允许 0–100 的回调
            v /= 100.0
        self.progress = max(0.0, min(1.0, v))
        if message:
            self.message = str(message)
        self.emit("progress")

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status,
                "progress": round(self.progress, 4), "message": self.message,
                "result": _jsonable(self.result), "error": self.error,
                "hint": self.hint, "created": self.created, "started": self.started,
                "finished": self.finished, "took_ms": int((self.finished - self.started) * 1000)
                if self.started and self.finished else 0,
                "log": list(self.log)[-50:], "last_seq": self._seq}

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d or {})
        allowed = {f for f in cls.__dataclass_fields__} - {"_cancel", "_events", "_seq", "_lock", "_cond"}
        return cls(**{k: v for k, v in d.items() if k in allowed})  # type: ignore[call-arg]


class JobManager:
    """线程池极简版：每个任务一条线程，状态留在内存里。

    本项目是单人本地工具，不做持久化队列 —— 服务重启后任务丢掉是**可接受**的，
    但已完成的**产物**（图/卡/包）都在磁盘上，所以不丢工作成果。
    """

    def __init__(self, *, max_workers: int = 4):
        self.max_workers = max(1, int(max_workers))
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._lock = threading.RLock()
        self._counter = itertools.count(1)
        self._cond = threading.Condition()

    # ── 提交 ────────────────────────────────────────────────────
    def submit(self, kind: str, fn: Callable, *args, **kw) -> str:
        """投递一个任务，立刻返回 job id（不阻塞请求线程）。

        ``fn`` 若声明了 ``on_progress`` / ``job`` 形参，会自动注入。
        """
        job = Job(id=f"j{next(self._counter):04d}", kind=str(kind))
        job._cond = self._cond
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._trim()
        t = threading.Thread(target=self._runner, args=(job, fn, args, kw),
                             name=f"cardforge-{job.id}", daemon=True)
        job.emit("queued")
        t.start()
        return job.id

    def _trim(self) -> None:
        """只保留最近的若干已完成任务，防止长时间运行内存无上限增长。"""
        while len(self._order) > self.max_workers * 40:
            old = self._order.popleft()
            j = self._jobs.get(old)
            if j and j.status in ("done", "error", "cancelled"):
                self._jobs.pop(old, None)
            else:
                self._order.appendleft(old)
                break

    # ── 执行 ────────────────────────────────────────────────────
    def _runner(self, job: Job, fn: Callable, args: tuple, kw: dict) -> None:
        job.status = "running"
        job.started = time.time()
        job.emit("started")
        try:
            sig_params = set()
            try:
                sig_params = set(inspect.signature(fn).parameters)
            except Exception:
                pass
            if "on_progress" in sig_params and "on_progress" not in kw:
                kw["on_progress"] = job.set_progress
            if "job" in sig_params and "job" not in kw:
                kw["job"] = job
            out = fn(*args, **kw)
            if job.cancelled():
                job.status = "cancelled"
                job.emit("cancelled")
            else:
                job.status = "done"
                job.progress = 1.0
                job.result = _jsonable(out) if isinstance(out, (dict, list)) \
                    else {"value": _jsonable(out)}
                job.emit("done", result=job.result)
        except Exception as e:
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
            hint = getattr(e, "hint", "") or ""
            job.hint = hint
            job.log.append(traceback.format_exc(limit=4))
            job.emit("error", error=job.error, hint=hint)
        finally:
            job.finished = time.time()
            with self._cond:
                self._cond.notify_all()

    # ── 查询 ────────────────────────────────────────────────────
    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(str(job_id))

    def list(self, *, kind: str = "", status: str = "", limit: int = 50) -> list[dict]:
        with self._lock:
            items = [self._jobs[i] for i in list(self._order)[::-1] if i in self._jobs]
        out = []
        for j in items:
            if kind and j.kind != kind:
                continue
            if status and j.status != status:
                continue
            out.append(j.to_dict())
            if limit and len(out) >= limit:
                break
        return out

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status in ("done", "error", "cancelled"):
            return False
        job._cancel.set()
        job.emit("cancel_requested")
        return True

    # ── SSE 事件流 ───────────────────────────────────────────────
    def events(self, job_id: str, *, since: int = 0,
               timeout: float = 25.0, idle_ping: float = 8.0) -> Iterator[dict]:
        """从 ``since`` 游标起持续产出事件，直到任务进入终态或 ``timeout``。

        每 ``idle_ping`` 秒至少产出一条 ``ping`` —— SSE 没有心跳就会被
        浏览器/代理当成死连接掐掉。
        """
        job = self.get(job_id)
        if job is None:
            yield {"job": job_id, "event": "unknown_job", "seq": 0}
            return
        cursor = max(0, int(since or 0))
        deadline = time.time() + timeout
        last_emit = time.time()
        while True:
            batch = []
            with job._lock:
                for ev in job._events:
                    if ev["seq"] > cursor:
                        batch.append(ev)
                        cursor = ev["seq"]
            for ev in batch:
                last_emit = time.time()
                yield ev
            if job.status in ("done", "error", "cancelled"):
                if not batch:
                    return
                continue
            now = time.time()
            if now - last_emit >= idle_ping:
                last_emit = now
                yield {"job": job.id, "kind": job.kind, "seq": cursor,
                       "event": "ping", "status": job.status,
                       "progress": round(job.progress, 4), "message": job.message,
                       "ts": now}
            if now > deadline:
                yield {"job": job.id, "kind": job.kind, "seq": cursor,
                       "event": "timeout", "status": job.status,
                       "progress": round(job.progress, 4), "message": job.message,
                       "ts": now}
                return
            with self._cond:
                self._cond.wait(0.35)


# ══════════════════════════════════════════════════════════════════════
#  模块级单例
# ══════════════════════════════════════════════════════════════════════
_MANAGER: Optional[JobManager] = None
_MLOCK = threading.Lock()


def manager() -> JobManager:
    global _MANAGER
    with _MLOCK:
        if _MANAGER is None:
            _MANAGER = JobManager()
        return _MANAGER
