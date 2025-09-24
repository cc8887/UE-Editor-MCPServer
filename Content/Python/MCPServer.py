try:
    import mcp.types as types
    MCP_AVAILABLE = True
except ImportError:
    from mcp_types import MCPTypes
    types = MCPTypes
    MCP_AVAILABLE = False

class MCPServer:
    """MCP Server implementation"""
    def __init__(self, host: str = "127.0.0.1", port: int = 8099):
        from unreal import log
        
        self.host = host
        self.port = port
        self._server = None
        
        if MCP_AVAILABLE:
            self._init_full_mcp_server(host, port, log)
        else:
            self._init_simple_server(host, port, log)
    
    def _init_full_mcp_server(self, host, port, log):
        """Initialize full MCP server with external dependencies"""
        try:
            import uvicorn
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
                if(name == "execute_command"):
                    # Execute in current thread
                    try:
                        exec(arguments['code'])
                        return [types.TextContent(type="text", text="Success")]
                    except SyntaxError as e:
                        return [types.TextContent(type="text", text=f"Syntax error: {e}")]
                return [types.TextContent(type="text", text="Failed")]
            
            @self._mcp_app.list_tools()
            async def list_tools() -> list[types.Tool]:
                log("try list_tools")
                return [
                    types.Tool(
                        name="execute_command",
                        description="execute python code in unreal engine",
                        inputSchema={"type": "object", 
                            "properties": {
                                "code": {
                                    "type": "string",
                                    "description": "python code to execute"
                                }
                            }
                        }
                    ),
                    types.Tool(
                        name="excute_file",
                        description="execute python script file in unreal engine",
                        inputSchema={"type": "object", 
                            "properties": {
                                "file": {
                                    "type": "string",
                                    "description": "python scripts file path"
                                }
                             }
                        }
                    ),
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
                    Route("/SSE", endpoint=handle_sse),
                    Mount("/messages/", app=self._sse.handle_post_message),
                ]
            )
            config = uvicorn.Config(self._web_app, host=host, port=port, log_level="trace")
            self._server = uvicorn.Server(config)
            log("Full MCP server initialized")
            
        except Exception as e:
            log(f"Failed to initialize full MCP server: {str(e)}")
            self._init_simple_server(host, port, log)
    
    def _init_simple_server(self, host, port, log):
        """Initialize simple HTTP server as fallback"""
        log("Initializing simple MCP server (fallback mode)")
        
        # Simple HTTP server implementation
        import asyncio
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import json
        import threading
        
        class MCPHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/health':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = {"status": "ok", "server": "UE-MCP-Simple"}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def do_POST(self):
                if self.path == '/tools':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    response = {
                        "tools": [
                            {
                                "name": "ue_tools",
                                "description": "Unreal Engine Tools",
                                "inputSchema": {"type": "object", "properties": {}}
                            }
                        ]
                    }
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
            
            def log_message(self, format, *args):
                # Suppress default logging
                pass
        
        self._simple_server = HTTPServer((host, port), MCPHandler)
        log(f"Simple MCP server ready on {host}:{port}")
        
    async def run_server(self):
        from unreal import log
        
        if hasattr(self, '_server') and self._server:
            # Full MCP server
            log("Starting full MCP server")
            await self._server.serve()
        elif hasattr(self, '_simple_server'):
            # Simple fallback server
            log("Starting simple MCP server")
            import asyncio
            import threading
            
            def run_simple_server():
                try:
                    self._simple_server.serve_forever()
                except Exception as e:
                    log(f"Simple server error: {str(e)}")
            
            # Run simple server in a separate thread
            server_thread = threading.Thread(target=run_simple_server, daemon=True)
            server_thread.start()
            
            # Keep the async function running
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                log("MCP server cancelled")
                self._simple_server.shutdown()
                raise
        else:
            log("No server initialized")
    
    async def destroy(self):
        from unreal import log
        
        if hasattr(self, '_server') and self._server:
            log("Shutting down full MCP server")
            await self._server.shutdown()
        elif hasattr(self, '_simple_server'):
            log("Shutting down simple MCP server")
            self._simple_server.shutdown()
            self._simple_server.server_close()
