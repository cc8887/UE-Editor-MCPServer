from asyncio import ProactorEventLoop

# 添加常量定义
# _MIN_SCHEDULED_TIMER_HANDLES = 100
# _MIN_CANCELLED_TIMER_HANDLES_FRACTION = 0.5
# MAXIMUM_SELECT_TIMEOUT = 60000  # 1 day

class WinCustomEventLoop(ProactorEventLoop):
    def __init__(self, proactor=None):
        super().__init__(proactor)
        self.stop()
        self._pending_stop = False
        self._regist_tick = None
        self._unregist_tick = None
        self._future = None
        self._is_new_task = False
        self._handle = None
        self._old_agen_hooks = None

    def run_until_complete(self, future):
        from asyncio import futures
        from asyncio import tasks
        super()._check_closed()
        super()._check_running()
        self._is_new_task = not futures.isfuture(future)
        self._future = tasks.ensure_future(future, loop=self)
        if self._is_new_task:
            # An exception is raised if the future didn't complete, so there
            # is no need to log the "destroy pending task" message
            self._future._log_destroy_pending = False

        # self._future.add_done_callback(_run_until_complete_cb)
        self.run_forever()


    def run_forever(self):
        import sys
        import threading
        from asyncio import events
        try:
            self._stopping = False
            # ProactorEventLoop logic
            assert self._self_reading_future is None
            self._pending_stop = False
            self.call_soon(self._loop_self_reading)
            # BaseEventLoop
            self._check_closed()
            self._check_running()
            self._set_coroutine_origin_tracking(self._debug)
            self._thread_id = threading.get_ident()

            self._old_agen_hooks = sys.get_asyncgen_hooks()
            sys.set_asyncgen_hooks(firstiter=self._asyncgen_firstiter_hook,
                                finalizer=self._asyncgen_finalizer_hook)
            events._set_running_loop(self)
            if self._stopping:
                raise RuntimeError("Cannot run forever while stopping")
        except Exception as ex:
            self._pending_stop = True
    def tick(self):
        if self._stopping:
            return
        if self._pending_stop:
            self._stopping = True
            self.on_tick_end()
            return
        try:
            self._run_once()
            if self._stopping:
                self.on_tick_end()
                return
        except Exception as ex:
            self._pending_stop = True
    def on_tick_end(self):
        import sys
        from asyncio import events

        self._stopping = False
        self._thread_id = None
        events._set_running_loop(None)
        super()._set_coroutine_origin_tracking(False)
        sys.set_asyncgen_hooks(*self._old_agen_hooks)
        if self._self_reading_future is not None:
            ov = self._self_reading_future._ov
            self._self_reading_future.cancel()
            # self_reading_future was just cancelled so if it hasn't been
            # finished yet, it never will be (it's possible that it has
            # already finished and its callback is waiting in the queue,
            # where it could still happen if the event loop is restarted).
            # Unregister it otherwise IocpProactor.close will wait for it
            # forever
            if ov is not None:
                self._proactor._unregister(ov)
            self._self_reading_future = None
        if self._unregist_tick is not None:
            self._unregist_tick(self)
        if self._is_new_task and self._future.done() and not self._future.cancelled():
            self._future.exception()
        # self._future.remove_done_callback(_run_until_complete_cb)

    # def _run_once(self):
    #     """Run one full iteration of the event loop.

    #     This calls all currently ready callbacks, polls for I/O,
    #     schedules the resulting callbacks, and finally schedules
    #     'call_later' callbacks.
    #     """
    #     import unreal
    #     import heapq
    #     sched_count = len(self._scheduled)
    #     if (sched_count > _MIN_SCHEDULED_TIMER_HANDLES and
    #         self._timer_cancelled_count / sched_count >
    #             _MIN_CANCELLED_TIMER_HANDLES_FRACTION):
    #         # Remove delayed calls that were cancelled if their number
    #         # is too high
    #         new_scheduled = []
    #         for handle in self._scheduled:
    #             if handle._cancelled:
    #                 handle._scheduled = False
    #             else:
    #                 new_scheduled.append(handle)

    #         heapq.heapify(new_scheduled)
    #         self._scheduled = new_scheduled
    #         self._timer_cancelled_count = 0
    #     else:
    #         # Remove delayed calls that were cancelled from head of queue.
    #         while self._scheduled and self._scheduled[0]._cancelled:
    #             self._timer_cancelled_count -= 1
    #             handle = heapq.heappop(self._scheduled)
    #             handle._scheduled = False

    #     timeout = None
    #     if self._ready or self._stopping:
    #         timeout = 0
    #     elif self._scheduled:
    #         # Compute the desired timeout.
    #         when = self._scheduled[0]._when
    #         timeout = min(max(0, when - self.time()), MAXIMUM_SELECT_TIMEOUT)
    #     event_list = self._selector.select(timeout)
    #     self._process_events(event_list)

    #     # Handle 'later' callbacks that are ready.
    #     end_time = self.time() + self._clock_resolution
    #     while self._scheduled:
    #         handle = self._scheduled[0]
    #         if handle._when >= end_time:
    #             break
    #         handle = heapq.heappop(self._scheduled)
    #         handle._scheduled = False
    #         self._ready.append(handle)

    #     # This is the only place where callbacks are actually *called*.
    #     # All other places just add them to ready.
    #     # Note: We run all currently scheduled callbacks, but not any
    #     # callbacks scheduled by callbacks run this time around --
    #     # they will be run the next time (after another I/O poll).
    #     # Use an idiom that is thread-safe without using locks.
    #     ntodo = len(self._ready)
    #     for i in range(ntodo):
    #         handle = self._ready.popleft()
    #         if handle._cancelled:
    #             continue
    #         # if self._debug:
    #         #     try:
    #         #         self._current_handle = handle
    #         #         t0 = self.time()
    #         #         handle._run()
    #         #         dt = self.time() - t0
    #         #         import unreal
    #         #         unreal.log('#3 Executing callback {:.3f} seconds'.format(dt))
    #         #     finally:
    #         #         self._current_handle = None
    #         # else:
    #         handle._run()
    #     handle = None  # Needed to break cycles when an exception occurs.
