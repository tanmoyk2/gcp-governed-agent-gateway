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

"""Pydantic schemas for Model Context Protocol (MCP) over JSON-RPC 2.0."""

from typing import Any, Dict, List, Literal, Union
from pydantic import BaseModel, Field


class ToolCallParams(BaseModel):
    """Parameters for a tools/call method request."""

    name: str = Field(description="The name of the tool to execute.")
    arguments: Dict[str, Any] = Field(
        description="The arguments to pass to the tool."
    )


class MCPRequest(BaseModel):
    """JSON-RPC 2.0 Request object for executing an MCP tool."""

    jsonrpc: Literal["2.0"] = Field(
        default="2.0",
        description="The JSON-RPC protocol version, must be exactly '2.0'.",
    )
    id: Union[str, int] = Field(
        description="Unique identifier for the JSON-RPC request."
    )
    method: Literal["tools/call"] = Field(
        default="tools/call",
        description="The MCP method name, explicitly enforcing 'tools/call'.",
    )
    params: ToolCallParams = Field(
        description="Parameters specifying the tool name and arguments."
    )


class TextContent(BaseModel):
    """A text content block within an MCP tool execution result."""

    type: Literal["text"] = Field(
        default="text", description="The content block type, must be 'text'."
    )
    text: str = Field(description="The textual result output from the tool execution.")


class MCPResult(BaseModel):
    """The encapsulated result payload inside a JSON-RPC response."""

    content: List[TextContent] = Field(
        description="Array of content blocks representing the tool's output."
    )


class MCPResponse(BaseModel):
    """JSON-RPC 2.0 Response object returning the tool execution result."""

    jsonrpc: Literal["2.0"] = Field(
        default="2.0",
        description="The JSON-RPC protocol version, must be exactly '2.0'.",
    )
    id: Union[str, int] = Field(
        description="Unique identifier matching the associated request."
    )
    result: MCPResult = Field(
        description="The successful execution result returned by the tool."
    )


class JSONRPCError(BaseModel):
    """Details of a JSON-RPC execution error."""

    code: int = Field(description="An integer indicating the error type.")
    message: str = Field(description="A short description of the error.")


class MCPErrorResponse(BaseModel):
    """JSON-RPC 2.0 Error Response object."""

    jsonrpc: Literal["2.0"] = Field(
        default="2.0",
        description="The JSON-RPC protocol version, must be exactly '2.0'.",
    )
    id: Union[str, int, None] = Field(
        description="Unique identifier matching the request, or None if parsing failed."
    )
    error: JSONRPCError = Field(description="The error details object.")


class InputSchema(BaseModel):
    """JSON Schema describing the tool's input arguments."""

    type: Literal["object"] = Field(
        default="object", description="The schema root type, must be 'object'."
    )
    properties: Dict[str, Any] = Field(
        description="Map of parameter names to their schema definitions."
    )
    required: List[str] = Field(
        default=[], description="List of required parameter names."
    )


class MCPToolSpec(BaseModel):
    """A single tool's capability specification under the One MCP standard."""

    name: str = Field(description="The unique name of the tool.")
    description: str = Field(
        description="A human-readable description of what the tool does."
    )
    inputSchema: InputSchema = Field(
        description="The JSON Schema defining the tool's input parameters."
    )


class MCPToolListResponse(BaseModel):
    """The expected payload schema for the tools/list capability response."""

    tools: List[MCPToolSpec] = Field(
        description="Array of available tool specifications."
    )
