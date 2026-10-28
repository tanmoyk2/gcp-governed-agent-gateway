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

"""FastAPI server wrapper for the hello_agent.

Provides a containerized Web API endpoint mapping Vertex AI agent engine payloads.
"""

import inspect
import json
import logging
import os
import sys
import uvicorn
import vertexai
from fastapi import FastAPI, Request, encoders, responses
from pydantic import BaseModel, Field
from vertexai import agent_engines

_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

import agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# Set dynamic defaults for reasoning engine
project = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
if not project:
    raise ValueError("Neither PROJECT_ID nor GOOGLE_CLOUD_PROJECT is set in the environment.")
location = os.environ.get("LOCATION", "us-central1")
vertexai.init(project=project, location=location)

os.environ.setdefault(
    "AGENT_REGISTRY_ENDPOINT",
    f"https://agentregistry.googleapis.com/v1alpha/projects/{project}/locations/{location}"
)

root_agent = agent.root_agent
if root_agent is None:
    from agent import RootAgent
    root_agent = RootAgent()

app = FastAPI()


class QueryRequest(BaseModel):
    """Request payload wrapping input parameters for the agent query."""

    input: dict | None = None
    class_method: str | None = Field(default=None, alias="classMethod")

    model_config = {
        "populate_by_name": True
    }


# Workaround while in autopush. Can remove when in prod.
def _session_service_builder():
    """Instantiate InMemorySessionService for ADK Engine environment."""
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    return InMemorySessionService()


adk_app = agent_engines.AdkApp(
    agent=root_agent,
    session_service_builder=_session_service_builder, # Workaround for autopush.
)


# Override project_id on adk_app to prevent gRPC lookup failures during container startup
# when routed through zero-trust egress gateways or in isolated environments.
def _safe_project_id() -> str | None:
    return os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")


adk_app.project_id = _safe_project_id


def _encode_chunk_to_json(chunk):
    """Encode a chunk to a JSON string with a newline."""
    try:
        json_chunk = encoders.jsonable_encoder(chunk)
        return json.dumps(json_chunk) + "\n"
    except Exception:
        logging.exception("Failed to encode chunk")
        return None


async def json_generator(output):
    """Yield serialized execution chunks for streaming responses."""
    if hasattr(output, "__aiter__"):
        async for chunk in output:
            encoded_chunk = _encode_chunk_to_json(chunk)
            if encoded_chunk is None:
                break
            yield encoded_chunk
    else:
        for chunk in output:
            encoded_chunk = _encode_chunk_to_json(chunk)
            if encoded_chunk is None:
                break
            yield encoded_chunk

async def _invoke_callable_or_raise(invocation_callable, invocation_payload):
    """Invoke a callable with parameters safely supporting both sync and async."""
    if inspect.iscoroutinefunction(invocation_callable):
        return await invocation_callable(**invocation_payload)
    else:
        return invocation_callable(**invocation_payload)


@app.post("/api/reasoning_engine")
async def query(request: Request) -> responses.JSONResponse:
    """Invoke reasoning engine queries synchronously."""
    body_bytes = await request.body()
    try:
        body_json = json.loads(body_bytes)
    except Exception as e:
        logger.error(f"Failed to parse body as JSON: {e}")
        return responses.JSONResponse(status_code=400, content={"error": f"Invalid JSON body: {e}"})

    try:
        payload = QueryRequest.model_validate(body_json)
    except Exception as e:
        logger.error(f"Validation failed for QueryRequest: {e} with body: {body_json}")
        return responses.JSONResponse(status_code=422, content={"error": f"Validation error: {e}"})

    # Robustly handle fallback & formatting
    method_name = payload.class_method or "query"
    if method_name in ("streamQuery", "async_stream_query"):
        method_name = "stream_query"

    logger.info(f"Invoking method_name: {method_name} with input: {payload.input}")

    # We want to be resilient if the client calls create_session
    if method_name == "create_session":
        return responses.JSONResponse(content={"output": {"id": "dummy-session-id"}})

    agent_obj = adk_app
    if hasattr(adk_app, "_tmpl_attrs") and "agent" in adk_app._tmpl_attrs:
        agent_obj = adk_app._tmpl_attrs["agent"]
    elif hasattr(adk_app, "agent"):
        agent_obj = adk_app.agent
    method = getattr(agent_obj, method_name)
    output = await _invoke_callable_or_raise(method, payload.input or {})

    try:
        json_serialized_content = encoders.jsonable_encoder({"output": output})
    except ValueError as encoding_error:
        logging.exception(
            "FastAPI could not JSON-encode the response from invocation method"
            " %s. Error: %s. Invocation method's original response: %r",
            method_name, encoding_error, output,
        )
        raise encoding_error
    return responses.JSONResponse(content=json_serialized_content)


@app.post("/api/stream_reasoning_engine")
async def stream_query(request: Request) -> responses.StreamingResponse:
    """Stream reasoning engine execution outputs."""
    body_bytes = await request.body()
    try:
        body_json = json.loads(body_bytes)
    except Exception as e:
        logger.error(f"Failed to parse body as JSON: {e}")
        return responses.JSONResponse(status_code=400, content={"error": f"Invalid JSON body: {e}"})

    try:
        payload = QueryRequest.model_validate(body_json)
    except Exception as e:
        logger.error(f"Validation failed for QueryRequest: {e} with body: {body_json}")
        return responses.JSONResponse(status_code=422, content={"error": f"Validation error: {e}"})

    method_name = payload.class_method or "query"
    if method_name in ("streamQuery", "async_stream_query"):
        method_name = "stream_query"

    logger.info(f"Streaming method_name: {method_name} with input: {payload.input}")

    # For streaming endpoints
    agent_obj = adk_app
    if hasattr(adk_app, "_tmpl_attrs") and "agent" in adk_app._tmpl_attrs:
        agent_obj = adk_app._tmpl_attrs["agent"]
    elif hasattr(adk_app, "agent"):
        agent_obj = adk_app.agent
    method = getattr(agent_obj, method_name)
    output = await _invoke_callable_or_raise(method, payload.input or {})
    return responses.StreamingResponse(
        content=json_generator(output),
        media_type="application/json",
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log incoming HTTP requests and outbound response statuses."""
    logger.info(f"Incoming request: {request.method} {request.url.path} Headers: {dict(request.headers)}")
    try:
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logger.exception(f"Exception during request handling: {e}")
        raise


from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body_str = ""
    if isinstance(exc.body, bytes):
        body_str = exc.body.decode("utf-8", errors="ignore")
    else:
        body_str = str(exc.body)
    logger.error(f"Validation error details: {exc.errors()} with body: {body_str}")
    return responses.JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body_str},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
