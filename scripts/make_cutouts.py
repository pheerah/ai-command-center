"""Remove the background from assets/sec_* portraits into assets/cutout/*.png.

Usage: python scripts/make_cutouts.py [name ...]
Needs: pip install "rembg[cpu]" pillow  (downloads a ~170MB model on first run)
"""
import sys
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'assets'
OUT = SRC / 'cutout'


def main():
    OUT.mkdir(exist_ok=True)
    wanted = set(sys.argv[1:])
    session = new_session('isnet-general-use')
    for path in sorted(SRC.glob('sec_*')):
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            continue
        if wanted and path.stem not in wanted:
            continue
        img = Image.open(path).convert('RGB')
        cut = remove(img, session=session)
        bbox = cut.getchannel('A').getbbox()
        if bbox:
            cut = cut.crop(bbox)
        target = OUT / f'{path.stem}.png'
        cut.save(target)
        print(f'{path.name} -> {target.relative_to(ROOT)} {cut.size}')


if __name__ == '__main__':
    main()
