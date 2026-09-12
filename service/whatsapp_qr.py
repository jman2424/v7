"""Generate a standard WhatsApp click-to-chat QR locally, without a tracking service."""
from __future__ import annotations

import base64
import re
from urllib.parse import quote

import qrcode
from qrcode.image.svg import SvgPathFillImage


def create_whatsapp_qr(phone: object, message: object = "") -> dict[str, str]:
    if not isinstance(phone, str) or len(phone) > 40:
        raise ValueError("Enter the full WhatsApp number with its country code.")
    number = re.sub(r"[ ()-]", "", phone.strip())
    if not re.fullmatch(r"\+?[1-9][0-9]{6,14}", number):
        raise ValueError("Use an international number, for example +44 7700 900123; omit the local leading zero.")
    if not isinstance(message, str) or len(message) > 160 or any(ord(char) < 32 and char != "\n" for char in message):
        raise ValueError("The optional message must be plain text of 160 characters or fewer.")
    link = "https://wa.me/" + number.lstrip("+")
    if message.strip():
        link += "?text=" + quote(message.strip(), safe="")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=10)
    qr.add_data(link)
    qr.make(fit=True)
    svg = qr.make_image(image_factory=SvgPathFillImage).to_string()
    return {"link": link, "image": "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")}
