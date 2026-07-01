import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="BVR Nexus Public Site", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

VERSION = "2.0.0"
CEO_URL = os.getenv("CEO_URL", "https://ceo.bvrinfra.in")
OPS_URL = os.getenv("OPS_URL", "https://ops.bvrinfra.in")
API_URL = os.getenv("API_URL", "https://api.bvrinfra.in")


def _ctx(request: Request, **kwargs) -> dict:
    return {"request": request, "version": VERSION, "ceo_url": CEO_URL, "ops_url": OPS_URL, "api_url": API_URL, **kwargs}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "public-site", "version": VERSION}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _ctx(request))


@app.get("/products", response_class=HTMLResponse)
async def products(request: Request):
    return templates.TemplateResponse(request, "products.html", _ctx(request))


@app.get("/support", response_class=HTMLResponse)
async def support(request: Request):
    return templates.TemplateResponse(request, "support.html", _ctx(request))


@app.get("/login")
async def login():
    return RedirectResponse(url=CEO_URL, status_code=302)
