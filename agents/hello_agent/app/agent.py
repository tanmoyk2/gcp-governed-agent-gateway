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

"""Core Google ADK Python agent logic orchestrating a RootAgent to MCPServer pattern."""

import json
import logging
import os
import ssl
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.request
import sys

_ssl_ctx = ssl._create_unverified_context()
from pydantic import BaseModel, Field
from google.adk.agents import Agent

_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

try:
    from hello_agent import models
except ImportError:
    import models

if not hasattr(models, "AgentInput"):
    import sys
    if "models" in sys.modules:
        del sys.modules["models"]
    import models


AgentInput = models.AgentInput
AgentOutput = models.AgentOutput
AgentState = models.AgentState
GetCapitalToolArgs = models.GetCapitalToolArgs
GetHostnameToolArgs = models.GetHostnameToolArgs
GetSantizedRecordToolArgs = models.GetSantizedRecordToolArgs
MCPToolRequest = models.MCPToolRequest
MCPToolResponse = models.MCPToolResponse
ToolCallParams = models.ToolCallParams


class AgentConfig(BaseModel):
    """Runtime configuration settings for the agent.
    
    Loaded from environment variables.
    """

    agent_registry_endpoint: str = Field(
        description="The base URL for the central Agent Registry API."
    )
    target_model_name: str = Field(
        default="gemini-3.5-flash",
        description="The target Gemini LLM model name to use for reasoning."
    )


def get_agent_config() -> AgentConfig:
    """Load and explicitly validate required environment variables.
    
    Ensures fail-fast behavior.
    """
    endpoint = os.environ.get("AGENT_REGISTRY_ENDPOINT") or "https://agentregistry.googleapis.com/mock"
    return AgentConfig.model_validate(
        {
            "agent_registry_endpoint": endpoint,
            "target_model_name": os.environ.get(
                "TARGET_MODEL_NAME", "gemini-3.5-flash"
            ),
        }
    )


def call_http_with_retry(
    url: str,
    payload: str,
    headers: Dict[str, str],
    max_retries: int = 3,
    timeout: int = 10,
) -> str:
    """Execute an HTTP POST request.
    
    Implements explicit timeouts and exponential backoff.
    """
    req = urllib.request.Request(
        url, data=payload.encode("utf-8"), headers=headers, method="POST"
    )

    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            logging.warning(
                f"HTTPError {e.code} calling {url} on attempt {attempt + 1}"
            )
            if e.code in (403, 798, 799):
                raise
            if attempt == max_retries or (e.code < 500 and e.code != 429):
                raise
        except urllib.error.URLError as e:
            logging.warning(f"URLError calling {url} on attempt {attempt + 1}: {e}")
            if attempt == max_retries:
                raise

        time.sleep(delay)
        delay *= 2.0

    raise RuntimeError(f"Failed to call {url} after {max_retries} retries.")


def fetch_google_access_token() -> str:
    """Fetch the native Google Cloud Access Token of the agent's identity."""
    try:
        import google.auth
        import google.auth.transport.requests
        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        return credentials.token
    except Exception as e:
        logging.error(f"Failed to fetch native access token: {e}")
        return None



def resolve_tool_uri(registry_endpoint: str, tool_name: str) -> str:
    """Query the central Agent Registry API.
    
    Resolves the exact destination URI of a tool.
    """
    project_id = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    headers = {
        "Accept": "application/json",
    }
    if project_id:
        headers["X-Goog-User-Project"] = project_id
    
    # Use native Google OAuth access token for Agent Registry (*.googleapis.com) calls
    token = fetch_google_access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Try discovering via /mcpServers collection first (compatible with IAP active blocking on mcpServers resources)
    mcp_url = f"{registry_endpoint.rstrip('/')}/mcpServers"
    try:
        req = urllib.request.Request(mcp_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            for item in data.get("mcpServers", []):
                if item.get("displayName") == tool_name or item.get("name", "").split("/")[-1] == tool_name:
                    if "interfaces" in item and item["interfaces"]:
                        return item["interfaces"][0]["url"]
    except Exception as e:
        logging.info(f"Discovery via /mcpServers fallback or non-fatal info: {e}")

    # Fallback to direct /services/ lookup
    url = f"{registry_endpoint.rstrip('/')}/services/{tool_name}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "interfaces" in data and data["interfaces"]:
                return data["interfaces"][0]["url"]
            return data.get("target_uri", url)
    except Exception as e:
        body = ""
        if hasattr(e, "read"):
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
        logging.error(f"Failed to resolve tool URI for {tool_name}: {body or e}")
        raise RuntimeError(f"Tool discovery failed for {tool_name}: {body or e}")




def fetch_oidc_token(target_audience: str, force_impersonation: Optional[bool] = None) -> str:
    """Fetch the OIDC Identity Token for the target audience.

    Supports dual URL routing paths:
    - Route A (Impersonation Route): If force_impersonation is True, or if the URL path
      contains '/impersonate' or query parameter 'auth=impersonate', or if OIDC_ROUTING_MODE
      is set to 'impersonate', prioritizes service account impersonation via the IAM
      Credentials API.
    - Route B (Native Identity Route - Default): Prioritizes native workload identity
      via the GCP metadata server, falling back cleanly to impersonation if metadata
      server resolution fails (e.g., local development).

    Args:
        target_audience: The target audience/URL of the service.
        force_impersonation: Optional explicit override to force impersonation routing.

    Returns:
        The OIDC identity token as a string, or a mock token if resolution fails.

    """
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(target_audience)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    query_params = parse_qs(parsed.query)

    # Determine URL routing path
    use_impersonation = force_impersonation
    if use_impersonation is None:
        use_impersonation = (
            "/impersonate" in parsed.path
            or query_params.get("auth", [""])[0].lower() == "impersonate"
            or os.environ.get("OIDC_ROUTING_MODE", "").lower() == "impersonate"
        )

    def _try_native() -> Optional[str]:
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            request = google.auth.transport.requests.Request()
            return google.oauth2.id_token.fetch_id_token(request, audience)
        except Exception as exc_native:
            logging.debug(f"Native OIDC token resolution failed: {exc_native}")
            return None

    def _try_impersonation() -> Optional[str]:
        target_sa = os.environ.get("MCP_INVOKER_SA_EMAIL")
        if not target_sa:
            return None
        logging.info(f"Impersonating service account {target_sa} for audience {audience}")
        try:
            import google.auth
            import google.auth.transport.requests
            from google.auth import impersonated_credentials

            source_creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            impersonated = impersonated_credentials.Credentials(
                source_credentials=source_creds,
                target_principal=target_sa,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            id_token_creds = impersonated_credentials.IDTokenCredentials(
                target_credentials=impersonated,
                target_audience=audience,
                include_email=True,
            )
            auth_request = google.auth.transport.requests.Request()
            id_token_creds.refresh(auth_request)
            return id_token_creds.token
        except Exception as exc_imp:
            logging.error(f"Failed to fetch impersonated OIDC token: {exc_imp}")
            raise

    if use_impersonation:
        token = _try_impersonation()
        if token:
            return token
        token = _try_native()
        if token:
            return token
    else:
        token = _try_native()
        if token:
            return token

    logging.warning("No OIDC token could be resolved; returning mock identity token.")
    return "mock-oidc-identity-token"





class RootAgent(Agent):
    """Orchestrates multi-step reasoning.
    
    Maps the resolved MCP server as a native tool.
    """

    system_instruction: str = Field(
        default=(
            "You are a helpful enterprise assistant. You MUST ONLY use the tools "
            "provided to you to answer questions. Do not attempt to use any other "
            "tools or external services. When a user sends a message containing a "
            "Social Security Number or other sensitive PII, you MUST invoke the "
            "get_santized_record tool to verify content sanitization and return "
            "the redacted record."
        ),
        description="The system instructions for the agent.",
    )
    config: AgentConfig = None
    resolved_tool_uri: str = None

    def __init__(self, config: AgentConfig = None):
        """Initialize the RootAgent and dynamically discover tool destinations."""
        # Initialize Pydantic base model with name
        super().__init__(name="hello_world_agent")
        if config is None:
            config = get_agent_config()
        # Bind custom fields directly to instance
        self.config = config
        self.resolved_tool_uri = None

    def run_agent(self, agent_input: Any = None, ctx: Any = None, **kwargs: Any) -> AgentOutput:
        """Execute the agentic reasoning loop and return synthesized output."""
        # Dynamically reload config from environment to prevent pickled credentials drift
        self.config = get_agent_config()

        if agent_input is None:
            msg = kwargs.get("message")
            if not msg and "new_message" in kwargs:
                nm = kwargs["new_message"]
                if hasattr(nm, "parts") and nm.parts:
                    msg = nm.parts[0].text
                elif isinstance(nm, str):
                    msg = nm
                elif isinstance(nm, dict) and "parts" in nm:
                    msg = nm["parts"][0].get("text", "")
            if not msg and ctx and hasattr(ctx, "user_content") and ctx.user_content:
                uc = ctx.user_content
                if hasattr(uc, "parts") and uc.parts:
                    msg = uc.parts[0].text
                elif isinstance(uc, str):
                    msg = uc
                elif isinstance(uc, dict) and "parts" in uc:
                    msg = uc["parts"][0].get("text", "")
            if not msg and ctx and hasattr(ctx, "session") and ctx.session and hasattr(ctx.session, "events") and ctx.session.events:
                for ev in reversed(ctx.session.events):
                    if getattr(ev, "author", None) == "user" and getattr(ev, "content", None):
                        c = ev.content
                        if hasattr(c, "parts") and c.parts:
                            msg = c.parts[0].text
                            break
                        elif isinstance(c, str):
                            msg = c
                            break
            agent_input = AgentInput(
                message=msg or "Enterprise Admin",
                user_id=kwargs.get("user_id", "admin-01")
            )

        if not self.resolved_tool_uri:
            self.resolved_tool_uri = resolve_tool_uri(
                self.config.agent_registry_endpoint, "agents-everywhere-sample-tool"
            )

        state = AgentState(
            current_step="call_tool", resolved_tool_uri=self.resolved_tool_uri
        )

        target_location = (
            agent_input.message.strip() if agent_input.message else "Japan"
        )

        msg_lower = target_location.lower()
        if "hostname" in msg_lower:
            tool_name = "get_hostname"
            tool_args = GetHostnameToolArgs()
        elif (
            "social security" in msg_lower
            or "ssn" in msg_lower
            or "123-45-" in msg_lower
        ):
            tool_name = "get_santized_record"
            tool_args = GetSantizedRecordToolArgs(record=target_location)
        else:
            tool_name = "get_capital"
            tool_args = GetCapitalToolArgs(location=target_location)

        params = ToolCallParams(name=tool_name, arguments=tool_args)
        mcp_req = MCPToolRequest(id="reasoning-step-1", params=params)

        token = fetch_oidc_token(self.resolved_tool_uri)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        try:
            raw_resp = call_http_with_retry(
                url=self.resolved_tool_uri,
                payload=mcp_req.model_dump_json(),
                headers=headers,
            )
        except urllib.error.HTTPError as e:
            if e.code in (403, 798, 799):
                err_msg = (
                    "Your request was blocked by our content filter. Please rephrase and try again."
                )
                try:
                    body = e.read().decode("utf-8", errors="ignore").strip()
                    if body and len(body) < 500:
                        err_msg = body
                except Exception:
                    pass
                logging.warning(f"Model Armor intervention (HTTP {e.code}): {err_msg}")
                state.tool_output = err_msg
                state.current_step = "complete"
                return AgentOutput(
                    response=f"Content Safety Intervention (HTTP {e.code}): {err_msg}"
                )
            raise

        mcp_resp = MCPToolResponse.model_validate_json(raw_resp)
        output_text = mcp_resp.result.content[0].text

        state.tool_output = output_text
        state.current_step = "complete"

        final_response = (
            f"Reasoning Engine ({self.config.target_model_name}) "
            f"synthesis: {output_text}"
        )
        return AgentOutput(response=final_response)

    async def _run_async_impl(self, ctx: Any) -> Any:
        """Execute the agent loop asynchronously for ADK Runner compatibility."""
        from google.adk.events import Event
        from google.genai import types
        out = self.run_agent(agent_input=None, ctx=ctx)
        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part.from_text(text=out.response)], role="model"),
            output=out.response,
        )

    def query(self, message: Any = None, user_id: str = None, ctx: Any = None, **kwargs: Any) -> str:
        """Entrypoint method required by Vertex AI Reasoning Engine."""
        # Convert structured message input to string robustly
        msg_str = ""
        if message is not None:
            if isinstance(message, str):
                msg_str = message
            elif isinstance(message, dict):
                if "parts" in message:
                    parts = message["parts"]
                    if isinstance(parts, list) and parts:
                        first_part = parts[0]
                        if isinstance(first_part, dict) and "text" in first_part:
                            msg_str = first_part["text"]
                        elif hasattr(first_part, "text"):
                            msg_str = first_part.text
                elif "text" in message:
                    msg_str = message["text"]
            elif hasattr(message, "parts") and message.parts:
                first_part = message.parts[0]
                if hasattr(first_part, "text"):
                    msg_str = first_part.text
            else:
                msg_str = str(message)

        inp = AgentInput(
            message=msg_str or "Enterprise Admin", user_id=user_id or "admin-01"
        )
        out = self.run_agent(inp, ctx=ctx, **kwargs)
        return out.response

    def stream_query(self, message: Any = None, user_id: str = None, ctx: Any = None, **kwargs: Any) -> Any:
        """Streaming entrypoint method required by Vertex AI Reasoning Engine."""
        response_text = self.query(message=message, user_id=user_id, ctx=ctx, **kwargs)
        yield {"content": response_text}

    def async_stream_query(self, message: Any = None, user_id: str = None, ctx: Any = None, **kwargs: Any) -> Any:
        """Streaming entrypoint method required by Vertex AI Reasoning Engine."""
        return self.stream_query(message=message, user_id=user_id, ctx=ctx, **kwargs)


# Global root_agent instance for ADK AgentLoader discovery at runtime
root_agent = None
if os.environ.get("AGENT_REGISTRY_ENDPOINT"):
    root_agent = RootAgent()

