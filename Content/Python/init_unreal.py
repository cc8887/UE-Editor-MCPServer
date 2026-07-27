import unreal

if "-NoMCPServer" in unreal.SystemLibrary.get_command_line():
    print("MCP Server startup skipped by -NoMCPServer")
else:
    from mcp_server import Start as ue_mcp
    print("Starting MCP Server")
    ue_mcp.start()
