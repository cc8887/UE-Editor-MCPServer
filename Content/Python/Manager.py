import asyncio
import time
from unreal import log


class Manager:

    @staticmethod
    async def guard_task():
        while True:
            await asyncio.sleep(0.0001)

    @staticmethod
    async def heart_fun():
        while True:
            #打印当前时间
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
    def tick(self, delta_time:float):
        self._loop.tick()
    # 销毁时需要清理资源
    def destroy(self):
        log("Manager destroy")
        self._unregist_tick()
        if self._loop is not None:
            self._loop.close()
            self._loop = None
    def __del__(self):
        log("Manager __del__")


# m:Manager = None

# def start_starlette():
# from StarletteServer import start_starlette_server, stop_starlette_server,run_server
#     global m
#     unreal.log("Starting Starlette server...")
    
#     loop.slow_callback_duration = 0
#     asyncio.set_event_loop(loop)
#     # success, _guard_task, _starlette_server_task = start_starlette_server(existing_loop=current_loop)
#     # if success:
#     #     unreal.log("Starlette server started successfully")
#     # else:
#     #     unreal.log_error("Failed to start Starlette server")
#     loop.run_until_complete(asyncio.gather(Manager.guard_task(),heart_fun(),run_server()))
#     # 需要通过Manager把Event挂到manager上使之生效
#     m = Manager(loop)
#     unreal.log("Starlette server started successfully")


# def stop_starlette():
#     unreal.log("Stopping Starlette server...")
#     stop_starlette_server()
#     unreal.log("Starlette server stopped successfully")
