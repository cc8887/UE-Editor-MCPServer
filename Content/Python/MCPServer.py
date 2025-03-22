import mcp.types as types

class MCPServer:
    def __init__(self,host:str="127.0.0.1", port:int=8099):
        import uvicorn
        from unreal import log
        from mcp.server.lowlevel import Server
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        self._mcp_app = Server("UE-MCP")
        self._sse = SseServerTransport("/messages/")
        
        @self._mcp_app.call_tool()
        async def call_tools(
            name: str, arguments: dict
        ) -> list[types.TextContent]:
            log(f"call_tool name: {name} arg:{arguments}")
            return [types.TextContent(type="text",text="Call Tools Success")]
        
        @self._mcp_app.list_tools()
        async def list_tools() -> list[types.Tool]:
            log("try list_tools")
            return [
                types.Tool(
                    name="ue tools",
                    description="UE Tools",
                    inputSchema={"type": "object", "properties": {}}
                )
            ]
        
        async def handle_sse(request):
            log("handle_sse - starting")
            initialization_options = self._mcp_app.create_initialization_options()
            
            async with self._sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                log("handle_sse - connected")
                try:
                    await self._mcp_app.run(
                        streams[0],
                        streams[1],
                        initialization_options,
                    )
                    log("MCP server initialized successfully")
                except Exception as e:
                    log(f"Error in MCP server: {str(e)}")
                    raise
        
        self._web_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=self._sse.handle_post_message),
            ]
        )
        config = uvicorn.Config(self._web_app, host=host, port=port, log_level="trace")
        self._server = uvicorn.Server(config)
        
    async def run_server(self):
        await self._server.serve()
    
    async def destroy(self):
        await self._server.shutdown()
