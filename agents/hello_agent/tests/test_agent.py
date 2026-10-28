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

"""Unit tests for hello_agent/agent.py."""

import os
import io
import json
from pathlib import Path
import sys
import urllib.error
from unittest.mock import MagicMock

# Add src/hello_agent to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from agent import (
    AgentInput,
    RootAgent,
    call_http_with_retry,
    fetch_google_access_token,
    fetch_oidc_token,
    get_agent_config,
    resolve_tool_uri,
)


def test_get_agent_config_success(mocker):
    """Test get_agent_config succeeds when environment variables are present."""
    mocker.patch.dict(
        os.environ,
        {
            "AGENT_REGISTRY_ENDPOINT": "https://registry.example.com",
            "TARGET_MODEL_NAME": "gemini-pro",
        },
        clear=True,
    )
    config = get_agent_config()
    assert config.agent_registry_endpoint == "https://registry.example.com"
    assert config.target_model_name == "gemini-pro"


def test_call_http_with_retry_success(mocker):
    """Test call_http_with_retry successfully returns decoded payload."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"result": "success"}'
    mock_urlopen = mocker.patch("urllib.request.urlopen", return_value=MagicMock())
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    res = call_http_with_retry("https://example.com", "payload", {})
    assert res == '{"result": "success"}'


def test_call_http_with_retry_server_error(mocker):
    """Test call_http_with_retry retries on server error (5xx)."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"result": "success"}'

    err_500 = urllib.error.HTTPError(
        "https://example.com", 500, "Internal Error", {}, None
    )

    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_resp

    mock_urlopen = mocker.patch(
        "urllib.request.urlopen", side_effect=[err_500, mock_ctx]
    )
    mocker.patch("time.sleep")

    res = call_http_with_retry("https://example.com", "payload", {})
    assert res == '{"result": "success"}'
    assert mock_urlopen.call_count == 2


def test_call_http_with_retry_client_error(mocker):
    """Test call_http_with_retry raises immediately on client error.

    Fails immediately on 4xx errors other than 429.
    """
    err_400 = urllib.error.HTTPError(
        "https://example.com", 400, "Bad Request", {}, None
    )
    mocker.patch("urllib.request.urlopen", side_effect=err_400)

    with pytest.raises(urllib.error.HTTPError):
        call_http_with_retry("https://example.com", "payload", {})


def test_call_http_with_retry_url_error(mocker):
    """Test call_http_with_retry retries on URLError and eventually fails."""
    err_url = urllib.error.URLError("Connection refused")
    mocker.patch("urllib.request.urlopen", side_effect=err_url)
    mocker.patch("time.sleep")

    with pytest.raises(urllib.error.URLError):
        call_http_with_retry("https://example.com", "payload", {}, max_retries=1)


def test_resolve_tool_uri_success(mocker):
    """Test resolve_tool_uri successfully decodes and returns targetUri."""
    mocker.patch("agent.fetch_google_access_token", return_value="mock-token")
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"target_uri": "https://tool.example.com"}'
    mock_urlopen = mocker.patch("urllib.request.urlopen", return_value=MagicMock())
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    uri = resolve_tool_uri("https://registry.example.com", "get_capital")
    assert uri == "https://tool.example.com"


def test_resolve_tool_uri_failure(mocker):
    """Test resolve_tool_uri raises RuntimeError when discovery fails."""
    mocker.patch("agent.fetch_google_access_token", return_value="mock-token")
    mocker.patch("urllib.request.urlopen", side_effect=Exception("Network down"))
    with pytest.raises(RuntimeError):
        resolve_tool_uri("https://registry.example.com", "get_capital")


def test_fetch_oidc_token_fallback(mocker):
    """Test fetch_oidc_token returns mock token on library failure."""
    mocker.patch(
        "google.oauth2.id_token.fetch_id_token", side_effect=Exception("Offline")
    )
    token = fetch_oidc_token("https://audience.example.com")
    assert token == "mock-oidc-identity-token"


def test_fetch_oidc_token_success(mocker):
    """Test fetch_oidc_token success flow."""
    mock_request = MagicMock()
    mocker.patch(
        "google.auth.transport.requests.Request", return_value=mock_request, create=True
    )
    mocker.patch(
        "google.oauth2.id_token.fetch_id_token", return_value="real-token", create=True
    )

    token = fetch_oidc_token("https://audience.example.com")
    assert token == "real-token"


def test_fetch_oidc_token_impersonation(mocker):
    """Test fetch_oidc_token uses impersonation when OIDC_ROUTING_MODE=impersonate is set."""
    mocker.patch(
        "google.oauth2.id_token.fetch_id_token", side_effect=Exception("Offline")
    )
    mocker.patch.dict(os.environ, {"MCP_INVOKER_SA_EMAIL": "sa@example.com", "OIDC_ROUTING_MODE": "impersonate"})
    mocker.patch("google.auth.default", return_value=(MagicMock(), "test-proj"), create=True)
    mock_id_creds = mocker.patch("google.auth.impersonated_credentials.IDTokenCredentials", create=True)
    mock_id_creds.return_value.token = "impersonated-token"
    mocker.patch("google.auth.transport.requests.Request", create=True)

    token = fetch_oidc_token("https://audience.example.com")
    assert token == "impersonated-token"


def test_fetch_oidc_token_native_no_impersonate_fallback(mocker):
    """Test Route B (Default) strictly does not fall back to impersonation when native fails."""
    mocker.patch(
        "google.oauth2.id_token.fetch_id_token", side_effect=Exception("Offline")
    )
    mocker.patch.dict(os.environ, {"MCP_INVOKER_SA_EMAIL": "sa@example.com"})
    mock_imp = mocker.patch("google.auth.impersonated_credentials.IDTokenCredentials", create=True)

    token = fetch_oidc_token("https://audience.example.com")
    assert token == "mock-oidc-identity-token"
    mock_imp.assert_not_called()


def test_fetch_oidc_token_impersonation_url_routing(mocker):
    """Test URL routing path containing /impersonate prioritizes impersonation."""
    mock_native = mocker.patch("google.oauth2.id_token.fetch_id_token", return_value="native-token", create=True)
    mocker.patch.dict(os.environ, {"MCP_INVOKER_SA_EMAIL": "sa@example.com"})
    mocker.patch("google.auth.default", return_value=(MagicMock(), "test-proj"), create=True)
    mock_id_creds = mocker.patch("google.auth.impersonated_credentials.IDTokenCredentials", create=True)
    mock_id_creds.return_value.token = "impersonated-routed-token"
    mocker.patch("google.auth.transport.requests.Request", create=True)

    # Calling URL with /impersonate in path should trigger Route A (impersonation) first
    token = fetch_oidc_token("https://audience.example.com/impersonate/tool")
    assert token == "impersonated-routed-token"
    mock_native.assert_not_called()


def test_fetch_oidc_token_force_impersonation_override(mocker):
    """Test force_impersonation=True parameter overrides default routing."""
    mock_native = mocker.patch("google.oauth2.id_token.fetch_id_token", return_value="native-token", create=True)
    mocker.patch.dict(os.environ, {"MCP_INVOKER_SA_EMAIL": "sa@example.com"})
    mocker.patch("google.auth.default", return_value=(MagicMock(), "test-proj"), create=True)
    mock_id_creds = mocker.patch("google.auth.impersonated_credentials.IDTokenCredentials", create=True)
    mock_id_creds.return_value.token = "impersonated-override-token"
    mocker.patch("google.auth.transport.requests.Request", create=True)

    token = fetch_oidc_token("https://audience.example.com/services/tool", force_impersonation=True)
    assert token == "impersonated-override-token"
    mock_native.assert_not_called()


def test_root_agent_run(mocker):
    """Test RootAgent execution loop returns synthesized agent output."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    capital_resp = json.dumps({"capital": "Paris"})
    mcp_resp_payload = (
        f'{{"jsonrpc": "2.0", "id": "1", "result": {{"content": '
        f'[{{"type": "text", "text": {json.dumps(capital_resp)}}}]}}}}'
    )
    mocker.patch("agent.call_http_with_retry", return_value=mcp_resp_payload)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    inp = AgentInput(message="France", user_id="u123")
    out = agent.run_agent(inp)

    assert "Paris" in out.response
    assert "gemini-ultra" in out.response


def test_root_agent_run_hostname(mocker):
    """Test RootAgent execution loop with get_hostname tool."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    hostname_resp = json.dumps({"hostname": "server-01"})
    mcp_resp_payload = (
        f'{{"jsonrpc": "2.0", "id": "1", "result": {{"content": '
        f'[{{"type": "text", "text": {json.dumps(hostname_resp)}}}]}}}}'
    )
    mocker.patch("agent.call_http_with_retry", return_value=mcp_resp_payload)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    inp = AgentInput(message="What is your hostname?", user_id="u123")
    out = agent.run_agent(inp)
    assert "server-01" in out.response


def test_root_agent_run_santized_record(mocker):
    """Test RootAgent execution loop with get_santized_record tool."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    record_resp = json.dumps({"santized_record": "[US_SOCIAL_SECURITY_NUMBER]"})
    mcp_resp_payload = (
        f'{{"jsonrpc": "2.0", "id": "1", "result": {{"content": '
        f'[{{"type": "text", "text": {json.dumps(record_resp)}}}]}}}}'
    )
    mocker.patch("agent.call_http_with_retry", return_value=mcp_resp_payload)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    inp = AgentInput(
        message="My Social Security Number is 123-45-6789", user_id="u123"
    )
    out = agent.run_agent(inp)

    assert "[US_SOCIAL_SECURITY_NUMBER]" in out.response


def test_root_agent_query(mocker):
    """Test RootAgent query entrypoint method."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    capital_resp = json.dumps({"capital": "Paris"})
    mcp_resp_payload = (
        f'{{"jsonrpc": "2.0", "id": "1", "result": {{"content": '
        f'[{{"type": "text", "text": {json.dumps(capital_resp)}}}]}}}}'
    )
    mocker.patch("agent.call_http_with_retry", return_value=mcp_resp_payload)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    response = agent.query()

    assert "Paris" in response
    assert "gemini-ultra" in response


def test_root_agent_stream_query(mocker):
    """Test RootAgent stream_query entrypoint method yields matching dictionary."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    capital_resp = json.dumps({"capital": "Paris"})
    mcp_resp_payload = (
        f'{{"jsonrpc": "2.0", "id": "1", "result": {{"content": '
        f'[{{"type": "text", "text": {json.dumps(capital_resp)}}}]}}}}'
    )
    mocker.patch("agent.call_http_with_retry", return_value=mcp_resp_payload)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    stream = agent.stream_query(message="France", user_id="admin-01")
    results = list(stream)

    assert len(results) == 1
    assert "Paris" in results[0]["content"]
    assert "gemini-ultra" in results[0]["content"]


def test_call_http_with_retry_model_armor_block(mocker):
    """Test call_http_with_retry raises HTTP 799 immediately without retries."""
    err_799 = urllib.error.HTTPError("url", 799, "Model Armor Block", {}, None)
    mock_urlopen = mocker.patch("urllib.request.urlopen", side_effect=err_799)
    mock_sleep = mocker.patch("time.sleep")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        call_http_with_retry("https://example.com", "payload", {}, max_retries=3)
    assert exc_info.value.code == 799
    assert mock_urlopen.call_count == 1
    mock_sleep.assert_not_called()


def test_root_agent_run_model_armor_block(mocker):
    """Test RootAgent execution loop catches HTTPError 799 and returns safety message."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    err_799 = urllib.error.HTTPError("url", 799, "Blocked", {}, io.BytesIO(b"Blocked by content filter."))
    mocker.patch("agent.call_http_with_retry", side_effect=err_799)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    agent = RootAgent(config=mock_config)
    inp = AgentInput(message="My Social Security Number is 123-45-6789", user_id="u123")
    out = agent.run_agent(inp)

    assert "Content Safety Intervention (HTTP 799)" in out.response
    assert "Blocked by content filter." in out.response


def test_fetch_google_access_token(mocker):
    """Test fetch_google_access_token success and exception handling."""
    mock_creds = MagicMock()
    mock_creds.token = "mock-access-token"
    mocker.patch("google.auth.default", return_value=(mock_creds, "test-proj"), create=True)
    mocker.patch("google.auth.transport.requests.Request", create=True)

    token = fetch_google_access_token()
    assert token == "mock-access-token"

    mocker.patch("google.auth.default", side_effect=Exception("Auth failed"), create=True)
    assert fetch_google_access_token() is None


def test_fetch_oidc_token_impersonation_fallback_to_native(mocker):
    """Test fetch_oidc_token falls back to native when impersonation returns None or fails."""
    mocker.patch("google.oauth2.id_token.fetch_id_token", return_value="native-token", create=True)
    mocker.patch.dict(os.environ, {"MCP_INVOKER_SA_EMAIL": "sa@example.com"})
    mocker.patch("google.auth.default", side_effect=Exception("Impersonation failed"), create=True)

    token = fetch_oidc_token("https://audience.example.com")
    assert token == "native-token"


def test_root_agent_run_model_armor_799_body_error(mocker):
    """Test RootAgent handles unreadable error body in HTTPError 799."""
    mocker.patch.dict(os.environ, {"TARGET_MODEL_NAME": "gemini-ultra"})
    mocker.patch("agent.resolve_tool_uri", return_value="https://tool.example.com")
    mocker.patch("agent.fetch_oidc_token", return_value="test-token")

    mock_fp = MagicMock()
    mock_fp.read.side_effect = Exception("Read error")
    err_799 = urllib.error.HTTPError("url", 799, "Blocked", {}, mock_fp)
    mocker.patch("agent.call_http_with_retry", side_effect=err_799)

    mock_config = MagicMock()
    mock_config.agent_registry_endpoint = "https://registry.example.com"
    mock_config.target_model_name = "gemini-ultra"

    root_agent = RootAgent(config=mock_config)
    inp = AgentInput(message="My Social Security Number is 123-45-6789", user_id="u123")
    out = root_agent.run_agent(inp)
    assert "Your request was blocked by our content filter" in out.response


