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

import sys
from pathlib import Path
if "models" in sys.modules:
    del sys.modules["models"]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from pydantic import ValidationError
from models import MCPRequest, MCPToolSpec


def test_mcp_request_success() -> None:
    """Test that MCPRequest validates valid JSON-RPC 2.0 payloads."""
    payload = {
        "jsonrpc": "2.0",
        "id": "req-01",
        "method": "tools/call",
        "params": {"name": "get_capital", "arguments": {"location": "France"}},
    }
    req = MCPRequest.model_validate(payload)
    assert req.jsonrpc == "2.0"
    assert req.id == "req-01"
    assert req.params.name == "get_capital"
    assert req.params.arguments == {"location": "France"}


def test_mcp_request_invalid_method() -> None:
    """Test that MCPRequest rejects payloads with invalid JSON-RPC method names."""
    payload = {
        "jsonrpc": "2.0",
        "id": "req-01",
        "method": "invalid/method",
        "params": {"name": "get_capital", "arguments": {}},
    }
    with pytest.raises(ValidationError):
        MCPRequest.model_validate(payload)


def test_mcp_tool_spec_success() -> None:
    """Test that MCPToolSpec validates valid specs successfully."""
    payload = {
        "name": "get_capital",
        "description": "Retrieve capitals.",
        "inputSchema": {
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
        },
    }
    spec = MCPToolSpec.model_validate(payload)
    assert spec.name == "get_capital"
    assert spec.inputSchema.type == "object"
    assert "location" in spec.inputSchema.properties
