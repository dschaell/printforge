import ast
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from printforge.application.service import render, sample
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
    assert response.headers["cache-control"] == "no-store"
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


# --- UX review 2026-11-09 (#10, #12, #13, #15, #16) ---


def test_max_ppi_stays_within_pixel_budget():
    from printforge.domain.planning import MAX_PIXELS, max_ppi

    ppi = max_ppi(84.1, 118.9)
    spec = PrintSpec(84.1, 118.9, ppi)
    assert spec.width_px * spec.height_px <= MAX_PIXELS
    assert ppi < 300
    with pytest.raises(PrintError):
        PrintSpec(84.1, 118.9, ppi + 1)
    assert max_ppi(10, 10) == 600


def test_limit_error_names_concrete_ppi(client):
    response = client.post(
        "/api/plan?width_cm=84.1&height_cm=118.9&ppi=300",
        content=picture(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 422
    body = response.json()
    assert f"höchstens {body['suggested_ppi']} PPI" in body["detail"]
    assert 72 <= body["suggested_ppi"] < 300


def test_plan_suggests_ppi_when_more_than_4x_needed():
    plan = plan_print(100, 100, PrintSpec(10, 10, 300))
    assert plan.required_scale > 4
    assert plan.suggested_ppi is not None
    again = plan_print(100, 100, PrintSpec(10, 10, plan.suggested_ppi))
    assert again.required_scale <= 4
    assert plan_print(1000, 1000, PrintSpec(10, 10, 300)).suggested_ppi is None


@pytest.mark.parametrize(
    "source_ppi,rating",
    [(300, "gut"), (150, "ausreichend"), (100, "grenzwertig"), (60, "kritisch")],
)
def test_quality_rating(source_ppi, rating):
    from printforge.domain.planning import rate_quality

    assert rate_quality(source_ppi) == rating
    plan = plan_print(1000, 1000, PrintSpec(2.54, 2.54, 100))
    assert plan.quality == "gut"
    assert plan.quality_text


def test_presets_sorted_small_to_large_and_unique():
    from printforge.domain.planning import PRESETS

    a_series = [name for name in PRESETS if name.startswith("A")]
    assert a_series == ["A6", "A5", "A4", "A3", "A2", "A1", "A0"]
    areas = [PRESETS[name][0] * PRESETS[name][1] for name in a_series]
    assert areas == sorted(areas)
    assert {"30×40", "50×70", "B2"} <= set(PRESETS)


def test_health_serves_presets_for_the_ui(client):
    data = client.get("/api/health").json()
    assert data["presets"]["A4"] == [21.0, 29.7]
    assert list(data["presets"])[0] == "A6"


def test_bleed_adds_pixels_and_keeps_white_margin_for_contain(client):
    # 2.54 cm trim + 2 x 10 mm bleed at 100 PPI
    response = client.post(
        "/api/render?width_cm=2.54&height_cm=2.54&ppi=100&bleed_mm=10",
        content=picture((100, 100)),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        # 2.54 + 2.0 cm = 4.54 cm -> ceil(178.7) = 179 px
        assert image.size == (179, 179)
        rgb = image.convert("RGB")
        assert rgb.getpixel((2, 2)) == (255, 255, 255)  # bleed stays white
        assert rgb.getpixel((89, 89))[1] < 10  # image in the middle


def test_bleed_filled_by_cover_and_validated(client):
    response = client.post(
        "/api/render?width_cm=2.54&height_cm=2.54&ppi=100&bleed_mm=10&fit=cover",
        content=picture((400, 400)),  # downscale only: no Upscayl needed (CI has none)
        headers={"content-type": "application/octet-stream"},
    )
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.convert("RGB").getpixel((2, 2))[1] < 10  # red reaches the edge
    too_much = client.post(
        "/api/plan?bleed_mm=11",
        content=picture(),
        headers={"content-type": "application/octet-stream"},
    )
    assert too_much.status_code == 422


def test_bleed_counts_towards_pixel_limit():
    with pytest.raises(PrintError, match="höchstens"):
        PrintSpec(100, 100, 300, "contain", 10)


def test_sample_window_is_centered_and_inside_printed_area():
    from printforge.domain.planning import sample_window

    spec = PrintSpec(2.54, 2.54, 100)
    box, size = sample_window(1000, 500, spec, 2.0)
    assert box[0] >= 0 and box[2] <= 1000 and box[1] >= 0 and box[3] <= 500
    assert (box[0] + box[2]) / 2 == 500 and (box[1] + box[3]) / 2 == 250
    assert size == (round((box[2] - box[0]) * 2), round((box[3] - box[1]) * 2))
    # cover crops the left/right: the window must not reach into the cropped part
    cover = PrintSpec(2.54, 2.54, 100, "cover")
    plan = plan_print(1000, 500, cover)
    box, _ = sample_window(1000, 500, cover, plan.required_scale)
    assert box[2] - box[0] <= 500


def test_sample_plain_and_ai_use_gpu_only_on_the_crop(tmp_path):
    source = tmp_path / "input"
    source.write_bytes(picture((300, 200)))
    fake = FakeUpscaler()
    spec = PrintSpec(2.54, 2.54, 200, "contain")  # 200 px target from 300x200 -> downscale
    plain = sample(source, tmp_path, spec, "plain", fake, PillowImages())
    assert fake.calls == 0 and plain.exists()
    small = tmp_path / "small"
    small.write_bytes(picture((100, 100)))
    spec = PrintSpec(2.54, 2.54, 200)
    out = sample(small, tmp_path, spec, "ai", fake, PillowImages())
    assert fake.calls == 1
    with Image.open(out) as image:
        assert image.size == (200, 200)
    with pytest.raises(PrintError, match="Vergleichsmethode"):
        sample(small, tmp_path, spec, "x", fake, PillowImages())
    with pytest.raises(PrintError, match="4×"):
        sample(small, tmp_path, PrintSpec(10, 10, 300), "ai", fake, PillowImages())
    assert fake.calls == 1


def test_sample_endpoint_returns_cleaned_up_png(client, monkeypatch):
    import tempfile

    original = tempfile.TemporaryDirectory
    directories = []

    def tracked(*args, **kwargs):
        result = original(*args, **kwargs)
        directories.append(Path(result.name))
        return result

    monkeypatch.setattr(tempfile, "TemporaryDirectory", tracked)
    response = client.post(
        "/api/sample?width_cm=2.54&height_cm=2.54&ppi=100&method=plain",
        content=picture((400, 200)),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size[0] <= 900 and image.size[1] <= 600
    assert not directories[-1].exists()
    assert (
        client.post(
            "/api/sample?method=evil",
            content=picture(),
            headers={"content-type": "application/octet-stream"},
        ).status_code
        == 422
    )


# --- White border trim (#19) ---


def barred(size=(400, 300), bar=50, fmt="PNG", **kwargs):
    """Red picture with white bars at top and bottom."""
    image = Image.new("RGB", size, "white")
    image.paste(Image.new("RGB", (size[0], size[1] - 2 * bar), "red"), (0, bar))
    data = io.BytesIO()
    image.save(data, format=fmt, **kwargs)
    return data.getvalue()


def test_content_box_finds_bars_and_tolerates_noise(tmp_path):
    from printforge.infrastructure.images import content_box

    source = tmp_path / "bars"
    source.write_bytes(barred())
    assert content_box(source) == (0, 50, 400, 250)
    noisy = Image.open(io.BytesIO(barred())).convert("RGB")
    noisy.putpixel((5, 5), (252, 253, 251))  # faint JPEG-like noise inside the white bar
    data = io.BytesIO()
    noisy.save(data, format="PNG")
    source.write_bytes(data.getvalue())
    assert content_box(source) == (0, 50, 400, 250)


def test_content_box_treats_transparency_as_white_and_rejects_all_white(tmp_path):
    from printforge.infrastructure.images import content_box

    rgba = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    rgba.paste(Image.new("RGBA", (20, 20), (255, 0, 0, 255)), (40, 30))
    source = tmp_path / "t"
    data = io.BytesIO()
    rgba.save(data, format="PNG")
    source.write_bytes(data.getvalue())
    assert content_box(source) == (40, 30, 60, 50)
    source.write_bytes(_white())
    with pytest.raises(PrintError, match="nur aus Weiß"):
        content_box(source)


def _white():
    data = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(data, format="PNG")
    return data.getvalue()


def test_fit_paper_keeps_aspect_inside_chosen_format():
    from printforge.domain.planning import fit_paper

    assert fit_paper(1.0, 50, 70) == (50, 50.0)  # wider than paper: keep width
    assert fit_paper(0.5, 50, 70) == (35.0, 70)  # narrower: keep height
    assert fit_paper(50 / 70, 50, 70) is None  # same aspect: nothing to suggest
    plan = plan_print(400, 200, PrintSpec(50, 70, 150))
    assert plan.fitted_paper_cm == (50, 25.0)


def test_plan_with_trim_uses_trimmed_size(client):
    headers = {"content-type": "application/octet-stream"}
    plain = client.post(
        "/api/plan?width_cm=10&height_cm=10&ppi=100", content=barred(), headers=headers
    )
    trimmed = client.post(
        "/api/plan?width_cm=10&height_cm=10&ppi=100&trim_white=true",
        content=barred(),
        headers=headers,
    )
    assert plain.json()["plan"]["source_height"] == 300
    body = trimmed.json()
    assert (body["plan"]["source_width"], body["plan"]["source_height"]) == (400, 200)
    assert body["image"]["trim_box"] == [0, 50, 400, 250]
    assert body["image"]["height"] == 300  # original size stays visible
    assert body["plan"]["fitted_paper_cm"] == [10, 5.0]


def test_render_with_trim_has_no_white_bars_on_fitted_paper(client):
    response = client.post(
        "/api/render?width_cm=4&height_cm=2&ppi=100&trim_white=true",
        content=barred(),
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text[:200]
    with Image.open(io.BytesIO(response.content)) as image:
        rgb = image.convert("RGB")
        assert rgb.getpixel((rgb.width // 2, 0))[1] < 10  # red up to the very top
        assert rgb.getpixel((rgb.width // 2, rgb.height - 1))[1] < 10
    untrimmed = client.post(
        "/api/render?width_cm=4&height_cm=2&ppi=100",
        content=barred(),
        headers={"content-type": "application/octet-stream"},
    )
    with Image.open(io.BytesIO(untrimmed.content)) as image:
        assert image.convert("RGB").getpixel((image.width // 2, 0)) == (255, 255, 255)


def test_sample_with_trim_stays_inside_content(tmp_path):
    source = tmp_path / "bars"
    source.write_bytes(barred())
    out = sample(
        source, tmp_path, PrintSpec(4, 2, 100), "plain", FakeUpscaler(), PillowImages(), True
    )
    with Image.open(out) as image:
        rgb = image.convert("RGB")
        assert all(
            rgb.getpixel((x, y))[1] < 10 for x in (0, rgb.width - 1) for y in (0, rgb.height - 1)
        )
