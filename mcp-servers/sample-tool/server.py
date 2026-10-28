# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cloud Run MCP Server implementation using FastMCP."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import socket
from pathlib import Path
from typing import Optional, Union
from pydantic import BaseModel, Field, ValidationError
from mcp.server.fastmcp import FastMCP
from anyio import run

import importlib.util


# Dynamically load local models.py to avoid sys.modules caching conflicts
def _load_local_models():
    """Dynamically load the models.py module from the local directory."""
    models_path = Path(__file__).resolve().parent / "models.py"
    spec = importlib.util.spec_from_file_location("sample_tool_models", models_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


models = _load_local_models()
JSONRPCError = models.JSONRPCError
MCPErrorResponse = models.MCPErrorResponse
MCPRequest = models.MCPRequest
MCPResponse = models.MCPResponse
MCPResult = models.MCPResult
TextContent = models.TextContent

# Initialize FastMCP
mcp = FastMCP("Sample Tool Server")


@mcp.tool(name="get_capital")
def execute_get_capital(location: str) -> str:
    """Retrieves the capital city of a specified country.

    Args:
        location: The country for which to find the capital.
    """
    location_lower = location.lower()
    if "japan" in location_lower:
        capital = "Tokyo"
    elif "france" in location_lower:
        capital = "Paris"
    else:
        capital = "Unknown"
    return json.dumps({"capital": capital})


@mcp.tool(name="get_hostname")
def execute_get_hostname() -> str:
    """Retrieves the hostname of the server running the tool."""
    hostname = socket.gethostname()
    return json.dumps({"hostname": hostname})


@mcp.tool(name="get_santized_record")
def execute_get_santized_record(record: str) -> str:
    """Returns the santized message received from the user after model armor applys the dlp template.

    Args:
        record: The user message or record containing sensitive data/PII.
    """
    return json.dumps({"santized_record": record})


class ServerConfig(BaseModel):
    """Server configuration settings loaded from environment variables."""

    port: int = Field(
        default=8080, description="The HTTP port for the server to listen on."
    )
    log_level: str = Field(default="INFO", description="The logging severity level.")


def get_config() -> ServerConfig:
    """Load and explicitly validate required runtime configuration."""
    return ServerConfig(
        port=int(os.environ.get("PORT", "8080")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


class MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for processing JSON-RPC MCP requests."""

    def _send_response(self, status_code: int, payload: BaseModel) -> None:
        """Send an HTTP response with a serialized Pydantic model payload."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.model_dump_json().encode("utf-8"))

    def do_POST(self) -> None:
        """Process incoming POST requests containing JSON-RPC MCP payloads."""
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return

        content_length_header = self.headers.get("Content-Length")
        if not content_length_header:
            self.send_response(411)  # Length Required
            self.end_headers()
            return

        try:
            content_length = int(content_length_header)
            raw_body = self.rfile.read(content_length).decode("utf-8")
        except Exception as e:
            logging.error(f"Failed to read request body: {e}")
            self.send_response(400)
            self.end_headers()
            return

        req_id: Optional[Union[str, int]] = None
        try:
            body_json = json.loads(raw_body)
            if isinstance(body_json, dict):
                req_id = body_json.get("id")
        except Exception:
            pass

        try:
            mcp_request = MCPRequest.model_validate_json(raw_body)
        except (ValidationError, ValueError) as e:
            logging.error(f"Validation error: {e}")
            error_resp = MCPErrorResponse(
                id=req_id,
                error=JSONRPCError(
                    code=-32600,
                    message="Invalid Request: Payload does not match MCP JSON-RPC 2.0 schema.",
                ),
            )
            self._send_response(400, error_resp)
            return

        tool_name = mcp_request.params.name
        try:

            async def _execute():
                tools = await mcp.list_tools()
                if tool_name in [tool.name for tool in tools]:
                    return await mcp.call_tool(tool_name, mcp_request.params.arguments)
                return None

            result = run(_execute)

            if result is not None:
                # Extract text from the first block
                result_text = ""
                if result and len(result) > 0:
                    result_text = getattr(result[0], "text", str(result[0]))

                response = MCPResponse(
                    id=mcp_request.id,
                    result=MCPResult(content=[TextContent(text=result_text)]),
                )
                self._send_response(200, response)
            else:
                error_resp = MCPErrorResponse(
                    id=mcp_request.id,
                    error=JSONRPCError(
                        code=-32601,
                        message=f"Tool not found: {tool_name}",
                    ),
                )
                self._send_response(404, error_resp)
        except Exception as e:
            logging.error(f"Execution error: {e}")
            error_resp = MCPErrorResponse(
                id=mcp_request.id,
                error=JSONRPCError(
                    code=-32603,
                    message=f"Internal Error during tool execution: {e}",
                ),
            )
            self._send_response(500, error_resp)


def run_server() -> None:
    """Initialize and start the HTTP server."""
    config = get_config()
    logging.basicConfig(level=config.log_level)
    server_address = ("", config.port)
    httpd = HTTPServer(server_address, MCPRequestHandler)
    logging.info(f"Starting Cloud Run MCP Server on port {config.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
