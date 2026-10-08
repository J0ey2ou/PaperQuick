from pathlib import Path
from PIL import Image, ImageDraw
root = Path(__file__).resolve().parents[1]
for size in [16, 48, 128]:
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), 48, fill="#215cce")
    draw.rounded_rectangle((58, 44, 180, 210), 12, fill="white")
    for y in (84, 110, 136):
        draw.line((82, y, 152, y), fill="#215cce", width=10)
    draw.line((130, 183, 211, 102), fill="#7bbaff", width=20)
    draw.line((168, 102, 211, 102, 211, 145), fill="#7bbaff", width=17)
    image.resize((size, size), Image.Resampling.LANCZOS).save(root / "browser-extension" / f"icon{size}.png")
image.save(root / "browser-extension" / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
