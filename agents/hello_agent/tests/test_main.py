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

"""Unit tests for the hello_agent/main.py FastAPI web application."""

import sys
import json
from pathlib import Path
from typing import Any, AsyncGenerator, List
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

# Add src/hello_agent to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import main


@pytest.fixture
def client() -> TestClient:
    """FastAPI testing client fixture."""
    return TestClient(main.app)


def test_query_create_session(client: TestClient) -> None:
    """Test create_session lifecycle call returns dummy session ID."""
    payload = {"classMethod": "create_session"}
    response = client.post("/api/reasoning_engine", json=payload)
    assert response.status_code == 200
    assert response.json() == {"output": {"id": "dummy-session-id"}}


def test_query_execution_success(client: TestClient, mocker: Any) -> None:
    """Test a standard non-stream query successfully runs on adk_app."""
    mock_method = MagicMock(return_value="Synthesized Agent response")
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "query", mock_method)

    payload = {
        "class_method": "query",
        "input": {"message": "Test Message", "user_id": "test-user"},
    }
    response = client.post("/api/reasoning_engine", json=payload)
    assert response.status_code == 200
    assert response.json() == {"output": "Synthesized Agent response"}
    mock_method.assert_called_once_with(message="Test Message", user_id="test-user")


def test_query_execution_camelcase(client: TestClient, mocker: Any) -> None:
    """Test camelCase classMethod field works correctly."""
    mock_method = MagicMock(return_value="Camel response")
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "query", mock_method)

    payload = {"classMethod": "query", "input": {"message": "Hello"}}
    response = client.post("/api/reasoning_engine", json=payload)
    assert response.status_code == 200
    assert response.json() == {"output": "Camel response"}


def test_stream_query_execution(client: TestClient, mocker: Any) -> None:
    """Test stream_query endpoint correctly yields stream chunks."""

    async def mock_generator(**kwargs) -> AsyncGenerator[str, None]:
        yield "chunk1"
        yield "chunk2"

    mock_method = MagicMock(return_value=mock_generator())
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "stream_query", mock_method, create=True)

    payload = {"class_method": "stream_query", "input": {"message": "Stream this"}}
    response = client.post("/api/stream_reasoning_engine", json=payload)
    assert response.status_code == 200

    content = response.content.decode("utf-8")
    chunks = [json.loads(c) for c in content.strip().split("\n") if c]
    assert chunks == ["chunk1", "chunk2"]


def test_session_service_builder() -> None:
    """Test the session service builder instantiates InMemorySessionService."""
    service = main._session_service_builder()
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    assert isinstance(service, InMemorySessionService)


def test_encode_chunk_to_json_failure() -> None:
    """Test that _encode_chunk_to_json handles non-serializable chunk gracefully."""
    result = main._encode_chunk_to_json(object())
    assert result is None


def test_json_generator_break() -> None:
    """Test that json_generator breaks early if encoding fails."""

    async def dummy_output() -> AsyncGenerator[Any, None]:
        yield "valid_chunk"
        yield object()
        yield "should_not_reach_this"

    import asyncio

    async def run_gen() -> List[Any]:
        res = []
        async for chunk in main.json_generator(dummy_output()):
            res.append(json.loads(chunk))
        return res

    chunks = asyncio.run(run_gen())
    assert chunks == ["valid_chunk"]


def test_invoke_callable_synchronous(mocker: Any) -> None:
    """Test _invoke_callable_or_raise handles a standard synchronous function."""

    def sync_func(x: int) -> int:
        return x * 2

    import asyncio

    res = asyncio.run(main._invoke_callable_or_raise(sync_func, {"x": 5}))
    assert res == 10


def test_query_encoding_failure(client: TestClient, mocker: Any) -> None:
    """Test query endpoint handles non-serializable response gracefully and raises ValueError."""
    mock_method = MagicMock(return_value=object())
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "query", mock_method)

    payload = {"classMethod": "query", "input": {"message": "Hello"}}
    with pytest.raises(ValueError):
        client.post("/api/reasoning_engine", json=payload)


def test_stream_query_alias(client: TestClient, mocker: Any) -> None:
    """Test stream_query maps class_method streamQuery properly."""

    async def mock_generator(**kwargs) -> AsyncGenerator[str, None]:
        yield "streamed"

    mock_method = MagicMock(return_value=mock_generator())
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "stream_query", mock_method, create=True)

    payload = {"classMethod": "streamQuery", "input": {"message": "Hello"}}
    response = client.post("/api/stream_reasoning_engine", json=payload)
    assert response.status_code == 200
    assert "streamed" in response.content.decode("utf-8")


def test_middleware_exception_logging(client: TestClient, mocker: Any) -> None:
    """Test middleware logs exceptions raised during execution."""
    mock_method = MagicMock(side_effect=RuntimeError("Custom error"))
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "query", mock_method)

    payload = {"classMethod": "query", "input": {"message": "Hello"}}
    with pytest.raises(RuntimeError):
        client.post("/api/reasoning_engine", json=payload)


def test_stream_response_sync_iterable() -> None:
    """Test json_generator handles synchronous generators and iterables."""
    import asyncio

    def sync_gen():
        yield {"text": "chunk1"}
        yield {"text": "chunk2"}
        yield object()

    async def run_stream():
        res = []
        async for chunk in main.json_generator(sync_gen()):
            res.append(json.loads(chunk))
        return res

    chunks = asyncio.run(run_stream())
    assert len(chunks) == 2


def test_invoke_callable_coroutine() -> None:
    """Test _invoke_callable_or_raise handles async coroutine functions."""
    import asyncio

    async def async_func(x: int) -> int:
        return x + 10

    res = asyncio.run(main._invoke_callable_or_raise(async_func, {"x": 5}))
    assert res == 15


def test_query_stream_query_alias(client: TestClient, mocker: Any) -> None:
    """Test query endpoint with classMethod streamQuery."""
    mock_method = MagicMock(return_value="streamed-res")
    agent_obj = getattr(main.adk_app, "agent", main.adk_app)
    if hasattr(main.adk_app, "_tmpl_attrs") and "agent" in main.adk_app._tmpl_attrs:
        agent_obj = main.adk_app._tmpl_attrs["agent"]
    target_class = agent_obj.__class__ if agent_obj is not None else main.adk_app.__class__
    mocker.patch.object(target_class, "stream_query", mock_method, create=True)

    payload = {"classMethod": "streamQuery", "input": {"message": "Hello"}}
    response = client.post("/api/reasoning_engine", json=payload)
    assert response.status_code == 200


