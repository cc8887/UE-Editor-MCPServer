import asyncio
import time
from unreal import log


class Manager:
    # guard task prevent asyncio event loop block
    @staticmethod
    async def guard_task():
        while True:
            await asyncio.sleep(0.0001)

    @staticmethod
    async def heart_fun():
        while True:
            log(time.time())
            await asyncio.sleep(1)
            log(time.time())

    def __init__(self):
        log("Manager init")
        from CustomEventLoop import WinCustomEventLoop
        self._loop = WinCustomEventLoop()
        asyncio.set_event_loop(self._loop)
        self._loop.slow_callback_duration = 0
        self._callback_handle = None
        self._regist_tick(self._loop)
    
    def run_until_complete(self,*coroutines,use_heart=False):
        if use_heart:
            self._loop.run_until_complete(asyncio.gather(Manager.guard_task(),Manager.heart_fun(),*coroutines))
        else:
            self._loop.run_until_complete(asyncio.gather(Manager.guard_task(),*coroutines))
    
    def _regist_tick(self,loop):
        from _unreal_slate import register_slate_pre_tick_callback
        log("Manager _regist_tick")
        self._loop = loop
        self._callback_handle = register_slate_pre_tick_callback(self.tick)
        log(self._callback_handle)

    def _unregist_tick(self):
        from _unreal_slate import unregister_slate_pre_tick_callback
        log("Manager unregist_tick")
        if self._callback_handle is not None:
            unregister_slate_pre_tick_callback(self._callback_handle)
        else:
            log("Manager unregist_tick _callback_handle is None")
        self._loop = None
        self._callback_handle = None

    # register_slate_pre_tick_callback needs delta_time
    def tick(self, delta_time:float):
        self._loop.tick()
    # clean resources
    def destroy(self):
        log("Manager destroy")
        self._unregist_tick()
        if self._loop is not None:
            self._loop.close()
            self._loop = None
    def __del__(self):
        log("Manager __del__")
