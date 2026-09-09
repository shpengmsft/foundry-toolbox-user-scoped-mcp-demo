from typing import Any
from urllib.parse import parse_qs

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import authenticate
from .config import get_settings
from .oauth_provider import get_fake_oauth_provider
from .tools import call_tool, visible_tools

PROTOCOL_VERSION = "2025-06-18"

app = FastAPI(
    title="User-scoped MCP demo",
    description="Returns a different MCP tool manifest for different authenticated users.",
    version="0.1.0",
)


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


def _fake_oauth_provider():
    settings = get_settings()
    if settings.auth_mode != "fake_oauth":
        raise StarletteHTTPException(status_code=404, detail="Not found")
    return get_fake_oauth_provider(settings)


@app.get("/.well-known/openid-configuration")
async def oauth_discovery() -> dict[str, Any]:
    return _fake_oauth_provider().discovery_document()


@app.get("/.well-known/jwks.json")
async def oauth_jwks() -> dict[str, Any]:
    return _fake_oauth_provider().jwks_document()


@app.get("/oauth/authorize")
async def oauth_authorize(
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query("mcp.access offline_access"),
    state: str | None = Query(None),
    test_user: str | None = Query(None),
    code_challenge: str | None = Query(None),
    code_challenge_method: str | None = Query(None),
) -> Response:
    return _fake_oauth_provider().authorize(
        response_type=response_type,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
        identity_key=test_user,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


@app.post("/oauth/token")
async def oauth_token(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        raise StarletteHTTPException(
            status_code=415,
            detail="Content-Type must be application/x-www-form-urlencoded",
        )
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    form = {key: values[-1] for key, values in parsed.items()}
    return JSONResponse(_fake_oauth_provider().exchange_token(form))


@app.post("/mcp")
async def mcp(request: Request) -> Response:
    settings = get_settings()
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        raise StarletteHTTPException(status_code=403, detail="Origin is not allowed")

    actor = await authenticate(request, settings)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse(
            _error(None, -32600, "The JSON-RPC request must be an object"),
            status_code=400,
        )

    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if payload.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return JSONResponse(_error(request_id, -32600, "Invalid JSON-RPC request"))
    if not isinstance(params, dict):
        return JSONResponse(_error(request_id, -32602, "Params must be an object"))

    if request_id is None:
        return Response(status_code=202)

    if method == "initialize":
        return JSONResponse(
            _result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "instructions": (
                        "Use only data returned by these tools. For a risk question, call the "
                        "role-specific search tool and answer in no more than three bullets. "
                        "Call a mitigation-plan tool only when the user explicitly requests a "
                        "plan. Do not add recommendations or ask a follow-up question. For "
                        "incidents, a lower severity number means higher priority."
                    ),
                    "serverInfo": {
                        "name": "user-scoped-mcp-demo",
                        "version": "0.1.0",
                    },
                },
            )
        )

    if method == "ping":
        return JSONResponse(_result(request_id, {}))

    if method == "tools/list":
        return JSONResponse(
            _result(
                request_id,
                {"tools": [tool.manifest() for tool in visible_tools(actor)]},
            )
        )

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return JSONResponse(_error(request_id, -32602, "Tool name is required"))
        if not isinstance(arguments, dict):
            return JSONResponse(_error(request_id, -32602, "Tool arguments must be an object"))
        try:
            result = call_tool(actor, name, arguments)
        except LookupError as exc:
            return JSONResponse(_error(request_id, -32602, str(exc)))
        except ValueError as exc:
            return JSONResponse(_error(request_id, -32602, str(exc)))
        except PermissionError as exc:
            return JSONResponse(_error(request_id, -32003, str(exc)))
        return JSONResponse(_result(request_id, result))

    return JSONResponse(_error(request_id, -32601, f"Method not found: {method}"))


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "user_scoped_mcp.app:app",
        host=settings.server_host,
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
