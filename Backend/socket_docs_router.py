"""Socket.IO documentation routes — AsyncAPI UI + interactive tester."""

import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

DOCS_YAML_PATH = os.path.join(os.path.dirname(__file__), "docs", "asyncapi.yaml")


def make_docs_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(tags=["documentation"])

    @router.get("/asyncapi", response_class=HTMLResponse, include_in_schema=False)
    async def asyncapi_ui(request: Request):
        return templates.TemplateResponse("asyncapi.html", {"request": request})

    @router.get("/api/docs/asyncapi.yaml", include_in_schema=False)
    async def asyncapi_yaml():
        try:
            with open(DOCS_YAML_PATH, "rb") as f:
                content = f.read()
            return Response(content=content, media_type="application/yaml",
                            headers={"Cache-Control": "no-cache"})
        except FileNotFoundError:
            return Response("AsyncAPI spec not found", status_code=404)

    @router.get("/socket-docs", response_class=HTMLResponse, include_in_schema=False)
    async def socket_docs(request: Request):
        return templates.TemplateResponse("socket_docs.html", {"request": request})

    return router
