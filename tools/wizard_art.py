"""Create restrained installer artwork from the user-selected app icon."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
icon = Image.open(ROOT / 'nexus.png').convert('RGBA')
assets = ROOT / 'assets'
assets.mkdir(exist_ok=True)
bg = '#f4f8f9'
ink = '#173543'
muted = '#66818b'
main = Image.new('RGB', (164, 314), bg)
draw = ImageDraw.Draw(main)
draw.rectangle((0, 0, 4, 313), fill='#079c92')
small = icon.resize((116, 116), Image.Resampling.LANCZOS)
main.paste(small, (24, 42), small)
font_file = Path('C:/Windows/Fonts/msyhbd.ttc')
regular_file = Path('C:/Windows/Fonts/msyh.ttc')
font = ImageFont.truetype(str(font_file), 27) if font_file.exists() else ImageFont.load_default()
caption = ImageFont.truetype(str(regular_file), 12) if regular_file.exists() else ImageFont.load_default()
draw.text((44, 190), '衡势', fill=ink, font=font)
draw.text((29, 240), '市场 · 估值 · 决策', fill=muted, font=caption)
main.save(assets / 'wizard.bmp', format='BMP')
mini = Image.new('RGB', (55, 55), bg)
mini_icon = icon.resize((45, 45), Image.Resampling.LANCZOS)
mini.paste(mini_icon, (5, 5), mini_icon)
mini.save(assets / 'wizard-small.bmp', format='BMP')
print(assets / 'wizard.bmp')
