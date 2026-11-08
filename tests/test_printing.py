import ast
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from printforge.application.service import render
from printforge.domain.planning import PrintError, PrintSpec, plan_print
from printforge.infrastructure.images import PillowImages, inspect_image
from printforge.presentation.api import create_app


def picture(size=(400, 200), fmt="PNG", **kwargs):
    data = io.BytesIO()
    Image.new("RGB", size, "red").save(data, format=fmt, **kwargs)
    return data.getvalue()


@pytest.fixture
def client():
    with TestClient(create_app()) as instance:
        yield instance


def test_a1_geometry_and_original_ppi():
    p = plan_print(3508, 4967, PrintSpec(59.4, 84.1, 300, "cover"))
    assert (p.target_width, p.target_height) == (7016, 9934)
    assert p.source_ppi == 150
    assert p.required_scale == 2


def test_contain_and_cover_have_different_scale_and_crop():
    contained = plan_print(1000, 500, PrintSpec(25.4, 25.4, 100, "contain"))
    covered = plan_print(1000, 500, PrintSpec(25.4, 25.4, 100, "cover"))
    assert contained.required_scale == 1
    assert covered.required_scale == 2
    assert covered.crop_percent == 50
    assert contained.crop_percent == 0


@pytest.mark.parametrize(
    "width,height,ppi", [(float("nan"), 10, 300), (0, 10, 300), (201, 10, 300), (200, 200, 600)]
)
def test_invalid_or_excessive_dimensions(width, height, ppi):
    with pytest.raises(PrintError):
        PrintSpec(width, height, ppi)


def test_original_with_exif_orientation(tmp_path):
    source = tmp_path / "image"
    exif = Image.Exif()
    exif[274] = 6
    source.write_bytes(picture((400, 200), "JPEG", exif=exif))
    info = inspect_image(source)
    assert (info["width"], info["height"]) == (200, 400)


def test_corrupt_and_animated_files_rejected(client):
    headers = {"content-type": "application/octet-stream"}
    response = client.post("/api/plan", content=b"<svg>not a photo</svg>", headers=headers)
    assert response.status_code == 422
    data = io.BytesIO()
    Image.new("RGB", (10, 10)).save(
        data, format="PNG", save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")]
    )
    assert client.post("/api/plan", content=data.getvalue(), headers=headers).status_code == 422


def test_input_pixel_limit_before_processing(tmp_path):
    source = tmp_path / "big.png"
    source.write_bytes(picture((6000, 5001)))
    with pytest.raises(PrintError, match="30 Mega"):
        inspect_image(source)


@pytest.mark.parametrize("fmt", ["png", "jpeg", "tiff"])
def test_export_pixels_ppi_color_and_privacy(client, fmt):
    exif = Image.Exif()
    exif[270] = "private original description"
    response = client.post(
        f"/api/render?width_cm=2.54&height_cm=2.54&ppi=100&output_format={fmt}",
        content=picture(exif=exif),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ""
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (100, 100)
        assert image.info["dpi"][0] == pytest.approx(100, abs=0.1)
        assert image.info.get("icc_profile")
        assert 270 not in image.getexif()
        assert 34853 not in image.getexif()
        assert image.convert("RGB").getpixel((50, 0))[0] > 245  # white margin
        assert image.convert("RGB").getpixel((50, 50))[1] < 10  # red image


def test_cmyk_without_profile_fails_closed(client):
    data = io.BytesIO()
    Image.new("CMYK", (100, 100)).save(data, format="JPEG")
    response = client.post(
        "/api/render?width_cm=1&height_cm=1&ppi=72",
        content=data.getvalue(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 422
    assert "ICC" in response.json()["detail"]


class FakeUpscaler:
    def __init__(self):
        self.calls = 0

    def upscale(self, source, destination):
        self.calls += 1
        with Image.open(source) as image:
            image.resize((image.width * 4, image.height * 4)).save(destination)


def test_upscaler_called_only_when_required(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(picture((100, 100)))
    fake = FakeUpscaler()
    render(source, tmp_path, PrintSpec(2.54, 2.54, 72), "png", fake, PillowImages())
    assert fake.calls == 0
    output = render(source, tmp_path, PrintSpec(2.54, 2.54, 200), "png", fake, PillowImages())
    assert fake.calls == 1
    with Image.open(output) as image:
        assert image.size == (200, 200)


def test_excessive_upscale_never_invokes_gpu(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(picture((100, 100)))
    fake = FakeUpscaler()
    with pytest.raises(PrintError, match="4×"):
        render(source, tmp_path, PrintSpec(10, 10, 300), "png", fake, PillowImages())
    assert fake.calls == 0


def test_invalid_upscaler_output_rejected(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(picture((100, 100)))

    class BrokenUpscaler:
        def upscale(self, source, destination):
            destination.write_bytes(picture((110, 110)))

    with pytest.raises(PrintError, match="unerwartete"):
        render(
            source, tmp_path, PrintSpec(2.54, 2.54, 200), "png", BrokenUpscaler(), PillowImages()
        )


def test_http_safety(client, monkeypatch):
    import printforge.presentation.api as api

    headers = {"content-type": "application/octet-stream"}
    assert client.post("/api/plan", content=picture()).status_code == 415
    assert (
        client.post(
            "/api/plan", content=picture(), headers={**headers, "origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/", headers={"host": "attacker.example"}).status_code == 400
    assert (
        client.post(
            "/api/render?output_format=../../secret", content=picture(), headers=headers
        ).status_code
        == 422
    )
    monkeypatch.setattr(api, "MAX_BYTES", 10)
    assert client.post("/api/plan", content=b"a" * 11, headers=headers).status_code == 413
    response = client.get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-embedder-policy"] == "require-corp"
    assert response.headers["cache-control"] == "public, max-age=300"
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_layers_do_not_import_outer_layers():
    base = Path(__file__).parents[1] / "src/printforge"
    for layer, forbidden in (
        (
            "domain",
            (
                "fastapi",
                "PIL",
                "printforge.application",
                "printforge.infrastructure",
                "printforge.presentation",
            ),
        ),
        ("application", ("fastapi", "PIL", "printforge.infrastructure", "printforge.presentation")),
    ):
        for path in (base / layer).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [n.name for n in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                assert not any(m.startswith(forbidden) for m in modules), path


def test_cli_timeout_is_safe_error(tmp_path, monkeypatch):
    import subprocess

    from printforge.infrastructure.upscayl import Upscayl

    binary = tmp_path / "binary"
    binary.touch(mode=0o700)
    for ext in ("bin", "param"):
        (tmp_path / f"test-4x.{ext}").touch()
    adapter = Upscayl(binary, tmp_path, "test-4x")

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 600
        assert "shell" not in kwargs
        raise subprocess.TimeoutExpired("private-path", 600)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(PrintError, match="Zeitlimit"):
        adapter.upscale(tmp_path / "input", tmp_path / "output")


def test_intermediate_image_budget_blocks_before_gpu(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(picture((3000, 3000)))
    fake = FakeUpscaler()
    with pytest.raises(PrintError, match="Zwischenbild"):
        render(source, tmp_path, PrintSpec(25.4, 25.4, 310), "png", fake, PillowImages())
    assert fake.calls == 0


def test_cover_crops_edges_without_stretching(client):
    data = io.BytesIO()
    image = Image.new("RGB", (400, 200), "red")
    from PIL import ImageDraw

    ImageDraw.Draw(image).rectangle((100, 0, 299, 199), fill="blue")
    image.save(data, format="PNG")
    response = client.post(
        "/api/render?width_cm=2.54&height_cm=2.54&ppi=100&fit=cover",
        content=data.getvalue(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.getpixel((50, 50)) == (0, 0, 255)
        assert result.getpixel((5, 50)) == (0, 0, 255)


def test_temp_files_removed_after_analysis_and_download(client, monkeypatch):
    import tempfile

    original = tempfile.TemporaryDirectory
    directories = []

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        directories.append(Path(result.name))
        return result

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracked)
    for action in ("plan", "render"):
        response = client.post(
            f"/api/{action}?width_cm=1&height_cm=1&ppi=72",
            content=picture(),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
        assert not directories[-1].exists()
