import base64
import io
import os

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/ttf-dejavu/DejaVuSansMono.ttf",
]

INK = (16, 20, 16)
PANEL = (26, 33, 28)
LINE = (44, 56, 47)
TEXT = (231, 236, 223)
MUTED = (139, 151, 136)
RED = (227, 107, 90)
GREEN = (125, 206, 160)
AMBER = (230, 177, 90)


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _bar(draw, box, frac, fill):
    x, y, w, h = box
    draw.rectangle([x, y, x + w, y + h], outline=LINE)
    width = int(w * max(0.0, min(1.0, frac)))
    if width > 0:
        draw.rectangle([x, y, x + width, y + h], fill=fill)


def render_snapshot(snapshot):
    font = _font(15)
    small = _font(13)
    image = Image.new("RGB", (1040, 560), INK)
    draw = ImageDraw.Draw(image)
    anomaly = bool(snapshot.get("anomaly"))
    banner = RED if anomaly else GREEN
    draw.rectangle([0, 0, 1040, 46], fill=banner)
    title = "ANOMALY" if anomaly else "HEALTHY"
    draw.text((16, 14), f"LIVE CONSOLE   {title}   score {snapshot.get('score', 0):.4f}", fill=INK, font=font)

    services = snapshot.get("services") or []
    for index, service in enumerate(services[:3]):
        x = 16 + index * 338
        draw.rounded_rectangle([x, 62, x + 322, 250], radius=8, fill=PANEL, outline=LINE)
        name = service["name"].replace("-service", "")
        status = "DOWN" if not service.get("reachable") else service.get("status", "up").upper()
        draw.text((x + 12, 74), f"{name}  :{service['port']}  {status}", fill=TEXT, font=font)
        latency = min(1.0, service.get("avg_latency_ms", 0) / 2000)
        error = min(1.0, service.get("error_rate", 0))
        rps = min(1.0, service.get("rps", 0) / 6)
        draw.text((x + 12, 108), f"latency {service.get('avg_latency_ms', 0):.0f} ms", fill=MUTED, font=small)
        _bar(draw, (x + 12, 128, 298, 12), latency, AMBER if latency > 0.25 else GREEN)
        draw.text((x + 12, 150), f"errors {error * 100:.0f}%", fill=MUTED, font=small)
        _bar(draw, (x + 12, 170, 298, 12), error, RED if error > 0.2 else GREEN)
        draw.text((x + 12, 192), f"rate {service.get('rps', 0):.2f} rps", fill=MUTED, font=small)
        _bar(draw, (x + 12, 212, 298, 12), rps, GREEN)

    draw.text((16, 266), "recent logs", fill=MUTED, font=small)
    y = 290
    for entry in snapshot.get("log_lines") or []:
        color = RED if entry.startswith("ERROR") or " 500 " in entry or " 502 " in entry or " 503 " in entry else TEXT
        if entry.startswith("WARN"):
            color = AMBER
        draw.text((16, y), entry[:110], fill=color, font=small)
        y += 18
        if y > 536:
            break

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
