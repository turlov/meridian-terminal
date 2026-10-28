"""Render the app icon (amber price line forming an M, green last-price dot, black tile)
to PNG, macOS .icns and Windows .ico. Run: python packaging/icons/make_icons.py"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S = 2048            # draw large, then downsample for smooth edges
AMBER = (255, 163, 26, 255)
GREEN = (43, 217, 100, 255)


def render(size: int = 1024, inset: float = 0.098) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(S * inset)                      # macOS-style margin around the tile
    tile = (pad, pad, S - pad, S - pad)
    w = tile[2] - tile[0]
    d.rounded_rectangle(tile, radius=int(w * 0.225), fill=(5, 7, 11, 255),
                        outline=(31, 42, 58, 255), width=max(4, S // 256))
    x0, y0 = tile[0], tile[1]
    u = w / 64                                 # same coordinate system as icon.svg
    for gy in (29, 41):
        d.line([(x0 + 10 * u, y0 + gy * u), (x0 + 54 * u, y0 + gy * u)], fill=(18, 26, 38, 255),
               width=max(2, int(1.5 * u)))
    pts = [(12, 47), (22, 20), (32, 38), (42, 20), (52, 47)]
    pts = [(x0 + x * u, y0 + y * u) for x, y in pts]
    lw = int(5.5 * u)
    for p0, p1 in zip(pts, pts[1:]):
        d.line([p0, p1], fill=AMBER, width=lw)
    r = lw / 2
    for x, y in pts[:1] + pts[1:4]:
        d.ellipse((x - r, y - r, x + r, y + r), fill=AMBER)
    gx, gy = pts[-1]
    gr = 4 * u
    d.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=GREEN)
    return img.resize((size, size), Image.LANCZOS)


def main():
    png = render(1024)
    png.save(HERE / "meridian.png")
    render(512, inset=0.0).save(HERE / "meridian-512.png")
    png.save(HERE / "meridian.icns")
    full = render(256, inset=0.0)
    full.save(HERE / "meridian.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                             (128, 128), (256, 256)])
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
