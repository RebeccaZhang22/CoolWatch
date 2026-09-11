"""Bounded, deadline-aware microbatching; one owner of the activation engine."""
import asyncio
from collections import deque
from dataclasses import dataclass
import time


class Overloaded(Exception):
    pass


class Unavailable(Exception):
    pass


@dataclass
class Job:
    ids: list
    future: asyncio.Future
    submitted: float
    deadline: float


class ProbeBatcher:
    def __init__(self, run_batch, *, max_batch=64, token_budget=32768,
                 max_inflight=128, wait_ms=10, timeout=30):
        if min(max_batch, token_budget, max_inflight, timeout) <= 0 or wait_ms < 0:
            raise ValueError('Invalid batch limits')
        self.run_batch = run_batch
        self.max_batch, self.token_budget = max_batch, token_budget
        self.max_inflight, self.wait_seconds, self.timeout = max_inflight, wait_ms / 1000, timeout
        self.pending = deque()
        self.event = asyncio.Event()
        self.active = 0
        self.task = None
        self.failed = False
        self.closing = False
        self.stats = dict(batches=0, completed=0, rejected=0, expired=0,
                          largest_batch=0, largest_batch_tokens=0, last_batch_size=0)

    def start(self):
        self.task = asyncio.create_task(self._worker())

    def reserve(self):
        if self.failed or self.closing:
            raise Unavailable('Probe worker unavailable')
        if self.active >= self.max_inflight:
            self.stats['rejected'] += 1
            raise Overloaded('Probe capacity full; retry with backoff')
        self.active += 1

    def release(self):
        self.active -= 1

    async def submit(self, ids, submitted):
        if len(ids) > self.token_budget:
            raise ValueError('Request exceeds batch token budget')
        future = asyncio.get_running_loop().create_future()
        job = Job(ids, future, submitted, submitted + self.timeout)
        self.pending.append(job)
        self.event.set()
        try:
            return await asyncio.wait_for(future, timeout=max(0, job.deadline - time.perf_counter()))
        except TimeoutError:
            self.stats['expired'] += 1
            raise

    async def _worker(self):
        while not self.closing:
            await self.event.wait()
            self.event.clear()
            await asyncio.sleep(self.wait_seconds)
            while self.pending:
                jobs, tokens = [], 0
                now = time.perf_counter()
                while self.pending and len(jobs) < self.max_batch:
                    job = self.pending[0]
                    if job.future.done() or job.deadline <= now:
                        self.pending.popleft()
                        if not job.future.done():
                            job.future.set_exception(TimeoutError('Queue deadline exceeded'))
                        continue
                    if tokens + len(job.ids) > self.token_budget:
                        break
                    jobs.append(self.pending.popleft())
                    tokens += len(job.ids)
                if not jobs:
                    continue
                batch_start = time.perf_counter()
                try:
                    results = await asyncio.to_thread(self.run_batch, [j.ids for j in jobs])
                    if len(results) != len(jobs):
                        raise RuntimeError('Incomplete batch result')
                except Exception:
                    # A corrupt tap or CUDA failure must not be retried against
                    # shared state. Mark unready and require process restart.
                    self.failed = True
                    for job in [*jobs, *self.pending]:
                        if not job.future.done():
                            job.future.set_exception(Unavailable('Probe batch failed; worker needs restart'))
                    self.pending.clear()
                    import logging
                    logging.exception('Probe batch worker failed')
                    return
                finished = time.perf_counter()
                self.stats['batches'] += 1
                self.stats['completed'] += len(jobs)
                self.stats['last_batch_size'] = len(jobs)
                self.stats['largest_batch'] = max(self.stats['largest_batch'], len(jobs))
                self.stats['largest_batch_tokens'] = max(self.stats['largest_batch_tokens'], tokens)
                for job, result in zip(jobs, results):
                    if not job.future.done():
                        result['latency_ms'] = dict(queue=(batch_start-job.submitted)*1000,
                            detect=(finished-batch_start)*1000, total=(finished-job.submitted)*1000)
                        result['batch_size'] = len(jobs)
                        result['batch_tokens'] = tokens
                        job.future.set_result(result)

    def info(self):
        return dict(ready=not (self.failed or self.closing), active=self.active,
                    queued=len(self.pending), max_batch=self.max_batch,
                    token_budget=self.token_budget, max_inflight=self.max_inflight,
                    wait_ms=self.wait_seconds*1000, timeout_seconds=self.timeout, **self.stats)

    async def close(self):
        self.closing = True
        for job in self.pending:
            if not job.future.done():
                job.future.set_exception(Unavailable('Probe service shutting down'))
        self.pending.clear()
        self.event.set()
        if self.task:
            await self.task
