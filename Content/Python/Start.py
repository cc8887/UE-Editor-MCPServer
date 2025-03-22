import importlib
# import unreal

# unreal.log("加载完成Manager")
modular_Manager = None
modular_MCPServer = None

def start():
    global modular_Manager,modular_MCPServer
    modular_Manager = importlib.import_module("Manager")
    modular_MCPServer = importlib.import_module("MCPServer")
    event_manager = modular_Manager.Manager()
    server = modular_MCPServer.MCPServer()
    event_manager.run_until_complete(server.run_server(),use_heart=False)

def reload():
    global modular_Manager,modular_MCPServer
    if modular_Manager is None or modular_MCPServer is None:
        modular_Manager = importlib.reload(modular_Manager)
        modular_MCPServer = importlib.reload(modular_MCPServer)
    if server is not None:
        server.destroy()
    if event_manager is not None:
        event_manager.destroy()
    event_manager = modular_Manager.Manager()
    server = modular_MCPServer.MCPServer()
    event_manager.run_until_complete(server.run_server(),use_heart=False)