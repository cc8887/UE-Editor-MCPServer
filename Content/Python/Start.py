import importlib
# import unreal

modular_Manager = None
modular_MCPServer = None
mcp_server = None
event_manager = None

def start():
    global modular_Manager,modular_MCPServer
    modular_Manager = importlib.import_module("Manager")
    modular_MCPServer = importlib.import_module("MCPServer")
    event_manager = modular_Manager.Manager()
    mcp_server = modular_MCPServer.MCPServer()
    event_manager.run_until_complete(mcp_server.run_server(),use_heart=False)

def reload():
    global modular_Manager,modular_MCPServer,mcp_server,event_manager
    if modular_Manager is None or modular_MCPServer is None:
        modular_Manager = importlib.reload(modular_Manager)
        modular_MCPServer = importlib.reload(modular_MCPServer)
    if mcp_server is not None:
        mcp_server.destroy()
    if event_manager is not None:
        event_manager.destroy()
    event_manager = modular_Manager.Manager()
    mcp_server = modular_MCPServer.MCPServer()
    event_manager.run_until_complete(mcp_server.run_server(),use_heart=False)