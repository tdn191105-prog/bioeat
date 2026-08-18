"""Обработка фотографий блюд.

Общий модуль для скрипта массовой загрузки (`scripts/fetch_dish_images.py`)
и для выгрузки фото из админ-панели — правила кропа, размеры и формат
должны совпадать, иначе меню начнёт выглядеть разнородно.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# Единый формат карточки: 4:3, WebP.
ASPECT = (4, 3)
FULL_SIZE = (800, 600)
THUMB_SIZE = (400, 300)
WEBP_QUALITY = 82

# Что принимаем от администратора
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_PILLOW_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 МБ
# Слишком маленький исходник растянется в кашу
MIN_SOURCE_SIDE = 200


class ImageError(ValueError):
    """Понятная человеку ошибка обработки изображения."""


@dataclass(frozen=True)
class ProcessedImage:
    full: bytes          # 800×600 WebP
    thumb: bytes         # 400×300 WebP
    placeholder: str     # HEX доминирующего цвета, например «#3a2b1f»
    source_size: tuple[int, int]


def _open(data: bytes) -> Image.Image:
    """Открывает изображение и проверяет, что это действительно картинка.

    Проверяем реальный формат через Pillow, а не по расширению файла
    и не по заголовку Content-Type — их подделать ничего не стоит.
    """
    if not data:
        raise ImageError("Файл пустой")
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()  # verify() «расходует» объект, поэтому открываем заново
        image = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError("Не удалось прочитать изображение — файл повреждён или это не фото") from exc

    if image.format not in ALLOWED_PILLOW_FORMATS:
        raise ImageError(
            f"Формат {image.format or 'неизвестный'} не поддерживается. Нужен JPEG, PNG или WebP."
        )
    if min(image.size) < MIN_SOURCE_SIDE:
        raise ImageError(
            f"Слишком маленькое фото {image.width}×{image.height}. "
            f"Минимум {MIN_SOURCE_SIDE} px по короткой стороне."
        )
    return image


def _flatten(image: Image.Image) -> Image.Image:
    """Приводит к RGB: прозрачность кладём на белый фон, а не в чёрный."""
    image = ImageOps.exif_transpose(image) or image
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert("RGB")


def crop_to_aspect(image: Image.Image, aspect: tuple[int, int] = ASPECT) -> Image.Image:
    """Кроп по центру до нужного соотношения сторон."""
    target = aspect[0] / aspect[1]
    width, height = image.size
    current = width / height

    if abs(current - target) < 0.001:
        return image
    if current > target:                       # шире, чем нужно — режем по бокам
        new_width = int(round(height * target))
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = int(round(width / target))    # выше, чем нужно — режем сверху и снизу
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def dominant_color(image: Image.Image) -> str:
    """HEX доминирующего цвета — усреднение по уменьшенной копии.

    Этим цветом заливаем место под фото, пока оно грузится: страница
    не мигает серым прямоугольником и не «прыгает».
    """
    tiny = image.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR)
    pixels = list(tiny.getdata())
    count = len(pixels)
    r = sum(p[0] for p in pixels) // count
    g = sum(p[1] for p in pixels) // count
    b = sum(p[2] for p in pixels) // count
    # слегка притемняем: фото почти всегда темнее своего среднего по краям
    r, g, b = (int(c * 0.82) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _encode(image: Image.Image, size: tuple[int, int]) -> bytes:
    resized = image.resize(size, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=5)
    return buffer.getvalue()


def process(data: bytes) -> ProcessedImage:
    """Из произвольного фото делает пару WebP 800×600 и 400×300."""
    image = _open(data)
    source_size = image.size
    image = _flatten(image)
    cropped = crop_to_aspect(image)
    return ProcessedImage(
        full=_encode(cropped, FULL_SIZE),
        thumb=_encode(cropped, THUMB_SIZE),
        placeholder=dominant_color(cropped),
        source_size=source_size,
    )


def save_pair(processed: ProcessedImage, directory: Path, slug: str) -> tuple[Path, Path]:
    """Пишет `<slug>.webp` и `<slug>-thumb.webp` в указанную папку."""
    directory.mkdir(parents=True, exist_ok=True)
    full_path = directory / f"{slug}.webp"
    thumb_path = directory / f"{slug}-thumb.webp"
    full_path.write_bytes(processed.full)
    thumb_path.write_bytes(processed.thumb)
    return full_path, thumb_path
