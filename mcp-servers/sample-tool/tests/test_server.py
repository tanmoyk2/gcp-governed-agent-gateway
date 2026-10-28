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

"""Unit tests for Sample Tool Server using FastMCP."""

import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock

# Add src/sample-tool to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from server import (
    MCPRequestHandler,
    execute_get_capital,
    execute_get_hostname,
    execute_get_santized_record,
    get_config,
    run_server,
)


def test_get_config_default(mocker):
    """Test get_config with default environment variables."""
    mocker.patch.dict(os.environ, {}, clear=True)
    config = get_config()
    assert config.port == 8080
    assert config.log_level == "INFO"


def test_get_config_custom(mocker):
    """Test get_config with custom environment variables."""
    mocker.patch.dict(os.environ, {"PORT": "9090", "LOG_LEVEL": "DEBUG"}, clear=True)
    config = get_config()
    assert config.port == 9090
    assert config.log_level == "DEBUG"


def test_execute_get_capital():
    """Test execute_get_capital returns expected output."""
    result_japan = json.loads(execute_get_capital("Japan"))
    assert result_japan["capital"] == "Tokyo"
    result_france = json.loads(execute_get_capital("France"))
    assert result_france["capital"] == "Paris"
    result_unknown = json.loads(execute_get_capital("Mars"))
    assert result_unknown["capital"] == "Unknown"


def test_execute_get_hostname(mocker):
    """Test execute_get_hostname returns system hostname."""
    mocker.patch("socket.gethostname", return_value="test-host")
    result = json.loads(execute_get_hostname())
    assert result["hostname"] == "test-host"


def test_execute_get_santized_record():
    """Test execute_get_santized_record returns expected output."""
    result = json.loads(execute_get_santized_record("123-45-6789"))
    assert result["santized_record"] == "123-45-6789"


@pytest.fixture
def mock_handler():
    """Fixture providing a bare MCPRequestHandler instance for do_POST testing."""
    handler = MCPRequestHandler.__new__(MCPRequestHandler)
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.wfile = io.BytesIO()
    return handler


def test_do_post_wrong_path(mock_handler):
    """Test POST on a path other than / returns 404."""
    mock_handler.path = "/invalid"
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(404)


def test_do_post_missing_content_length(mock_handler):
    """Test POST without Content-Length header returns 411."""
    mock_handler.path = "/"
    mock_handler.headers = {}
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(411)


def test_do_post_read_error(mock_handler):
    """Test POST handling read exception returns 400."""
    mock_handler.path = "/"
    mock_handler.headers = {"Content-Length": "100"}
    mock_handler.rfile = MagicMock()
    mock_handler.rfile.read.side_effect = Exception("Read failure")
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(400)


def test_do_post_validation_error(mock_handler):
    """Test POST with invalid JSON-RPC payload returns 400."""
    mock_handler.path = "/"
    body = json.dumps({"invalid": "payload"}).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(400)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert response_payload["error"]["code"] == -32600


def test_do_post_tool_not_found(mock_handler):
    """Test POST requesting unknown tool returns 404."""
    mock_handler.path = "/"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {"location": "Japan"}},
        }
    ).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(404)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert response_payload["error"]["code"] == -32601


def test_do_post_success_capital(mock_handler):
    """Test successful get_capital tool execution returns 200 OK."""
    mock_handler.path = "/"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-123",
            "method": "tools/call",
            "params": {
                "name": "get_capital",
                "arguments": {"location": "France"},
            },
        }
    ).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(200)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert response_payload["jsonrpc"] == "2.0"
    assert response_payload["id"] == "req-123"
    assert "Paris" in response_payload["result"]["content"][0]["text"]


def test_do_post_success_hostname(mock_handler, mocker):
    """Test successful get_hostname tool execution returns 200 OK."""
    mocker.patch("socket.gethostname", return_value="mock-host")
    mock_handler.path = "/"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-456",
            "method": "tools/call",
            "params": {
                "name": "get_hostname",
                "arguments": {},
            },
        }
    ).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(200)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert "mock-host" in response_payload["result"]["content"][0]["text"]


def test_do_post_success_santized_record(mock_handler):
    """Test successful get_santized_record tool execution returns 200 OK."""
    mock_handler.path = "/"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-789",
            "method": "tools/call",
            "params": {
                "name": "get_santized_record",
                "arguments": {"record": "123-45-6789"},
            },
        }
    ).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)
    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(200)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert "123-45-6789" in response_payload["result"]["content"][0]["text"]


def test_do_post_execution_exception(mock_handler, mocker):
    """Test internal exception during execution returns 500."""
    mock_handler.path = "/"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "req-123",
            "method": "tools/call",
            "params": {"name": "get_capital", "arguments": {"location": "Japan"}},
        }
    ).encode("utf-8")
    mock_handler.headers = {"Content-Length": str(len(body))}
    mock_handler.rfile = io.BytesIO(body)

    # Mock call_tool to fail
    mocker.patch("server.mcp.call_tool", side_effect=Exception("Internal failure"))

    mock_handler.do_POST()
    mock_handler.send_response.assert_called_once_with(500)
    response_payload = json.loads(mock_handler.wfile.getvalue().decode("utf-8"))
    assert response_payload["error"]["code"] == -32603


def test_run_server(mocker):
    """Test run_server starts and cleanly halts on KeyboardInterrupt."""
    mock_httpd = MagicMock()
    mock_httpd.serve_forever.side_effect = KeyboardInterrupt
    mocker.patch("server.HTTPServer", return_value=mock_httpd)
    run_server()
    mock_httpd.server_close.assert_called_once()
