import warnings
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageCms, ImageOps, UnidentifiedImageError

from printforge.domain.planning import MAX_PIXELS, PrintError, PrintSpec

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ALLOWED = {"JPEG", "PNG", "WEBP", "TIFF"}


def inspect_image(path: Path, max_pixels: int = 30_000_000) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in ALLOWED or getattr(image, "n_frames", 1) != 1:
                    raise PrintError(
                        "Nur einzelne JPEG-, PNG-, WebP- und TIFF-Bilder sind erlaubt."
                    )
                if image.width * image.height > max_pixels:
                    raise PrintError(f"Bild überschreitet {max_pixels // 1_000_000} Megapixel.")
                image.verify()
            with Image.open(path) as opened:
                oriented = ImageOps.exif_transpose(opened)
                return {
                    "width": oriented.width,
                    "height": oriented.height,
                    "mode": oriented.mode,
                    "has_icc": bool(oriented.info.get("icc_profile")),
                }
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise PrintError("Beschädigte, zu große oder unbekannte Bilddatei.") from exc


def normalize_image(source: Path, destination: Path) -> None:
    import io

    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original)
        icc = image.info.get("icc_profile")
        if icc:
            try:
                converted = ImageCms.profileToProfile(
                    image,
                    ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                    ImageCms.createProfile("sRGB"),
                    outputMode="RGBA" if "A" in image.mode else "RGB",
                )
                if converted is None:
                    raise PrintError("ICC-Konvertierung lieferte kein Bild.")
                image = converted
            except (ImageCms.PyCMSError, OSError, ValueError) as exc:
                raise PrintError("ICC-Profil kann nicht nach sRGB konvertiert werden.") from exc
        elif image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            raise PrintError("Für CMYK/Sonderfarbräume ist ein gültiges ICC-Profil erforderlich.")
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, "white")
        canvas.alpha_composite(rgba)
        # Fresh RGB image strips EXIF/GPS/XMP and prevents inherited orientation metadata.
        clean = Image.new("RGB", rgba.size)
        clean.paste(canvas.convert("RGB"))
        clean.save(destination, format="PNG")


def export_image(source: Path, destination: Path, spec: PrintSpec, fmt: str) -> None:
    with Image.open(source) as image:
        size = (spec.width_px, spec.height_px)
        if spec.fit == "cover":
            # The image fills the whole sheet including bleed.
            result = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
        else:
            # The whole image sits in the trim box; the bleed stays white.
            trim = (spec.trim_width_px, spec.trim_height_px)
            fitted = ImageOps.contain(image, trim, method=Image.Resampling.LANCZOS)
            result = Image.new("RGB", size, "white")
            result.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        options: dict[str, Any] = {"dpi": (spec.ppi, spec.ppi), "icc_profile": profile}
        if fmt == "jpeg":
            options.update(quality=95, subsampling=0)
        if fmt == "tiff":
            options.update(compression="tiff_lzw")
        result.save(destination, format=fmt.upper(), **options)


WHITE_TOLERANCE = 10  # per channel; absorbs JPEG noise and faint scanner tint


def content_box(path: Path) -> tuple[int, int, int, int]:
    """Bounding box of everything that is not (nearly) white; transparency counts as white."""
    with Image.open(path) as opened:
        rgba = ImageOps.exif_transpose(opened).convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, "white")
    canvas.alpha_composite(rgba)
    darkest = ImageChops.invert(canvas.convert("RGB"))
    r, g, b = darkest.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(
        lambda v: 255 if v > WHITE_TOLERANCE else 0
    )
    box = mask.getbbox()
    if box is None:
        raise PrintError("Das Bild besteht nur aus Weiß. Nichts zum Zuschneiden.")
    return box


def crop_image(source: Path, destination: Path, box: tuple[int, int, int, int]) -> None:
    with Image.open(source) as image:
        image.crop(box).save(destination, format="PNG")


def resize_image(source: Path, destination: Path, size: tuple[int, int]) -> None:
    with Image.open(source) as image:
        image.resize(size, Image.Resampling.LANCZOS).save(destination, format="PNG")


class PillowImages:
    inspect = staticmethod(inspect_image)
    normalize = staticmethod(normalize_image)
    export = staticmethod(export_image)
    crop = staticmethod(crop_image)
    content_box = staticmethod(content_box)
    resize = staticmethod(resize_image)
