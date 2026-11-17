"""Regenerates assets/icon.ico and assets/icon.png. Needs Pillow (pip install pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=(229, 56, 59, 255))
white = (255, 255, 255, 255)
# arrow shaft + head
d.rounded_rectangle((452, 200, 572, 560), radius=40, fill=white)
d.polygon([(292, 500), (732, 500), (512, 740)], fill=white)
# tray
d.rounded_rectangle((262, 790, 762, 860), radius=35, fill=white)

out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
