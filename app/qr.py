"""QR-коды в SVG: масштабируются без потерь на любом экране."""
from __future__ import annotations

import io

import qrcode
import qrcode.image.svg


def qr_svg(text: str) -> str:
    qr = qrcode.QRCode(box_size=10, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")
    # пролог <?xml?> не нужен ни файлу, ни SVG, вставленному прямо в страницу
    svg = svg[svg.index("<svg"):]
    # белый фон + чёрный код читается сканерами лучше всего
    return svg.replace("<svg ", '<svg style="background:#fff" ', 1)
