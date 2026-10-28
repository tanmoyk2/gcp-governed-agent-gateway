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
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from models import (
    AgentInput,
    AgentOutput,
    AgentState,
    GetSantizedRecordToolArgs,
)


def test_agent_input_success() -> None:
    """Test that AgentInput parses valid payload successfully."""
    payload = {"message": "Hello World", "user_id": "admin-01"}
    agent_input = AgentInput.model_validate(payload)
    assert agent_input.message == "Hello World"
    assert agent_input.user_id == "admin-01"


def test_agent_input_missing_fields() -> None:
    """Test that AgentInput raises ValidationError on missing fields."""
    with pytest.raises(ValidationError):
        AgentInput.model_validate({"message": "Hello"})


def test_agent_output_success() -> None:
    """Test that AgentOutput parses valid payload successfully."""
    payload = {"response": "Agent synthesized response"}
    agent_output = AgentOutput.model_validate(payload)
    assert agent_output.response == "Agent synthesized response"


def test_agent_state_defaults() -> None:
    """Test that AgentState initializes with correct defaults."""
    state = AgentState()
    assert state.current_step == "initialize"
    assert state.resolved_tool_uri is None
    assert state.tool_output is None


def test_get_santized_record_tool_args_success() -> None:
    """Test that GetSantizedRecordToolArgs validates valid payload successfully."""
    payload = {"record": "123-45-6789"}
    args = GetSantizedRecordToolArgs.model_validate(payload)
    assert args.record == "123-45-6789"
