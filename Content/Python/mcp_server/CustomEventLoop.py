from asyncio import ProactorEventLoop
import time
import traceback



class WinCustomEventLoop(ProactorEventLoop):
    def __init__(self, proactor=None, debug: bool = False):
        # asyncio internals (e.g. BaseEventLoop.call_soon) rely on self._debug
        # potentially during base __init__ (UE4.27 Python 3.7 proactor loop).
        self._debug = bool(debug)
        super().__init__(proactor)
        self.stop()
        self._pending_stop = False
        self._regist_tick = None
        self._unregist_tick = None
        self._future = None
        self._is_new_task = False
        self._handle = None
        self._old_agen_hooks = None
        self._in_tick = False
        self.debug = bool(debug)
        self._last_reentry_warning_time = 0.0

    def set_debug(self, enabled: bool = True):
        enabled = bool(enabled)
        try:
            super().set_debug(enabled)
        except Exception:
            self._debug = enabled
        self.debug = enabled

    def run_until_complete(self, future):
        from asyncio import futures
        from asyncio import tasks
        self._check_closed()
        # _check_running 在 Python 3.7 中不存在
        if hasattr(self, '_check_running'):
            self._check_running()
        elif self.is_running():
            raise RuntimeError('This event loop is already running')
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
            # _check_running 在 Python 3.7 中不存在
            if hasattr(self, '_check_running'):
                self._check_running()
            elif self.is_running():
                raise RuntimeError('This event loop is already running')
            # _set_coroutine_origin_tracking 在 Python 3.7 中不存在
            if hasattr(self, '_set_coroutine_origin_tracking'):
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
        if self._in_tick:
            if self.debug:
                now = time.time()
                if now - self._last_reentry_warning_time >= 1.0:
                    self._last_reentry_warning_time = now
                    stack = "".join(traceback.format_stack(limit=25))
                    try:
                        from unreal import log_warning
                        log_warning("[MCP] WinCustomEventLoop.tick re-entered; skipping nested tick\n" + stack)
                    except Exception:
                        print("[MCP] WinCustomEventLoop.tick re-entered; skipping nested tick\n" + stack)
            return
        self._in_tick = True
        if self._stopping:
            self._in_tick = False
            return
        if self._pending_stop:
            self._stopping = True
            self.on_tick_end()
            self._in_tick = False
            return
        try:
            self._run_once()
            if self._stopping:
                self.on_tick_end()
                self._in_tick = False
                return
        except Exception as ex:
            self._pending_stop = True
        finally:
            self._in_tick = False
    def on_tick_end(self):
        import sys
        from asyncio import events

        self._stopping = False
        self._thread_id = None
        events._set_running_loop(None)
        # _set_coroutine_origin_tracking 在 Python 3.7 中不存在
        if hasattr(self, '_set_coroutine_origin_tracking'):
            self._set_coroutine_origin_tracking(False)
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
