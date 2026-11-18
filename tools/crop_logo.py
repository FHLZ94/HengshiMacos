"""Crop transparent margins from the approved mark and build app icon files."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
source_path = ROOT / 'assets' / 'LOGO-衡势app.png'
source = Image.open(source_path).convert('RGBA')
bounds = source.getchannel('A').getbbox()
if bounds is None:
    raise ValueError(f'Logo image has no visible pixels: {source_path}')
mark = source.crop(bounds)
side = max(mark.size)
square = Image.new('RGBA', (side, side), (0, 0, 0, 0))
square.alpha_composite(mark, ((side - mark.width) // 2, (side - mark.height) // 2))
icon = square.resize((1024, 1024), Image.Resampling.LANCZOS)
icon.save(ROOT / 'nexus.png')
icon.save(ROOT / 'frontend' / 'app-logo.png')
icon.save(ROOT / 'nexus.ico', format='ICO', sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
print(ROOT / 'nexus.png')
