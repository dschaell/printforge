import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from printforge.application.service import analyze, render, sample
from printforge.domain.planning import MAX_BLEED_MM, MAX_PIXELS, PRESETS, PrintError, PrintSpec
from printforge.infrastructure.images import PillowImages
from printforge.infrastructure.upscayl import Upscayl

MAX_BYTES = 40 * 1024 * 1024
STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.gate = asyncio.Lock()
        yield

    app = FastAPI(
        title="PrintForge", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )
    app.state.upscaler = Upscayl.from_environment()
    images = PillowImages()

    @app.middleware("http")
    async def security(request: Request, call_next: RequestResponseEndpoint) -> Response:

        origin = request.headers.get("origin")
        if request.method == "POST" and origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
                return JSONResponse({"detail": "Fremde Herkunft nicht erlaubt."}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store"
                if request.url.path.startswith("/api/")
                else "public, max-age=300",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cross-Origin-Embedder-Policy": "require-corp",
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
                "X-Frame-Options": "DENY",
            }
        )
        return response

    @app.exception_handler(PrintError)
    async def print_error(request: Request, exc: PrintError) -> JSONResponse:
        body: dict[str, object] = {"detail": str(exc)}
        if exc.suggested_ppi is not None:
            body["suggested_ppi"] = exc.suggested_ppi
        return JSONResponse(body, status_code=422)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "upscayl_available": app.state.upscaler.available,
            "presets": PRESETS,
            "max_upload_mb": 40,
            "max_input_megapixels": 30,
            "max_bleed_mm": MAX_BLEED_MM,
            "max_output_megapixels": MAX_PIXELS // 1_000_000,
        }

    @app.post("/api/{action}")
    async def process(
        action: Literal["plan", "render", "sample"],
        request: Request,
        width_cm: Annotated[float, Query(ge=1, le=200)] = 21,
        height_cm: Annotated[float, Query(ge=1, le=200)] = 29.7,
        ppi: Annotated[int, Query(ge=72, le=600)] = 300,
        fit: Literal["contain", "cover"] = "contain",
        output_format: Literal["png", "jpeg", "tiff"] = "png",
        bleed_mm: Annotated[float, Query(ge=0, le=MAX_BLEED_MM)] = 0,
        method: Literal["plain", "ai"] = "plain",
        trim_white: bool = False,
    ) -> Response:
        spec = PrintSpec(width_cm, height_cm, ppi, fit, bleed_mm)
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise HTTPException(415, "Bild als application/octet-stream senden.")
        if app.state.gate.locked():
            raise HTTPException(429, "Eine Bildverarbeitung läuft bereits. Bitte warten.")
        async with app.state.gate:
            work = tempfile.TemporaryDirectory(prefix="printforge-")
            handed_off = False
            try:
                directory = Path(work.name)
                source = directory / "upload"
                size = 0
                with source.open("wb") as stream:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, "Maximal 40 MiB pro Datei.")
                        stream.write(chunk)
                if action == "plan":
                    plan, info = await run_in_threadpool(analyze, source, spec, images, trim_white)
                    return JSONResponse({"plan": plan.to_dict(), "image": info})
                if action == "sample":
                    output = await run_in_threadpool(
                        sample,
                        source,
                        directory,
                        spec,
                        method,
                        app.state.upscaler,
                        images,
                        trim_white,
                    )
                else:
                    output = await run_in_threadpool(
                        render,
                        source,
                        directory,
                        spec,
                        output_format,
                        app.state.upscaler,
                        images,
                        trim_white,
                    )
                kind = "png" if action == "sample" else output_format
                response = FileResponse(
                    output,
                    filename=f"printforge-{ppi}ppi.{kind}",
                    media_type=f"image/{kind}",
                    background=BackgroundTask(work.cleanup),
                )
                handed_off = True
                return response
            finally:
                if not handed_off:
                    work.cleanup()

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="web")
    return app


app = create_app()
