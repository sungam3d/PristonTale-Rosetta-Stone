"""Turn the raw screenshots into guide images (crop, scale, annotate, blur personal paths)."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = r'X:\Projects\PT-World-Map\work'
G = os.path.join(W, 'guide')
B = os.path.join(W, 'blender')
P = r'X:\Projects\PT-World-Map\preview'
OUT = r'X:\Projects\PT-World-Map\src\Guide\Guide_images'
os.makedirs(OUT, exist_ok=True)

RED = (230, 40, 40)
try:
    FONT = ImageFont.truetype(r'C:\Windows\Fonts\segoeuib.ttf', 22)
except OSError:
    FONT = ImageFont.load_default()


def save(im, name, max_w=1400):
    im = im.convert('RGB')
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(os.path.join(OUT, name), optimize=True)
    print('wrote', name, im.size)


def box(im, rect, label=None, width=4):
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = rect
    d.rounded_rectangle((x0 - 4, y0 - 4, x1 + 4, y1 + 4), radius=8, outline=RED, width=width)
    if label:
        r = 15
        cx, cy = x0 - 4, y0 - 4
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED)
        d.text((cx, cy), label, fill='white', font=FONT, anchor='mm')
    return im


def blur(im, rect, radius=6):
    region = im.crop(rect).filter(ImageFilter.GaussianBlur(radius))
    im.paste(region, rect[:2])
    return im


def pad(im, px=20):
    """Leave room around an image so callout badges at the edge are not cut off."""
    out = Image.new('RGB', (im.width + 2 * px, im.height + 2 * px), (30, 30, 30))
    out.paste(im, (px, px))
    return out


# ---------------------------------------------------------------- converter
save(Image.open(os.path.join(G, 'cs_gui_0_start.png')), 'conv_1_start.png')
im = Image.open(os.path.join(G, 'cs_gui_1_warning.png')).convert('RGB')
box(im, (30, 485, 192, 501), '1')          # I understand, continue
box(im, (25, 526, 122, 558), '2')          # Convert
save(im, 'conv_2_folder_warning.png')
save(Image.open(os.path.join(G, 'cs_gui_2_done.png')), 'conv_3_done.png')
save(Image.open(os.path.join(G, 'cs_gui_3_single.png')), 'conv_4_single_file.png')

# ---------------------------------------------------------------- 3ds Max
im = pad(Image.open(os.path.join(G, 'max_1_dialog.png')).convert('RGB'))
box(im, (30 + 20, 274 + 20, 287 + 20, 300 + 20), '1')     # Import ASE file(s)
save(im, 'max_1_dialog.png')

im = Image.open(os.path.join(G, 'max_2_progress.png')).convert('RGB')
blur(im, (1438, 56, 1680, 84))                              # project path in toolbar
w, h = im.size
strip = im.crop((0, h - 60, int(w * 0.55), h))
save(strip, 'max_2_progress_bar.png', max_w=1400)

im = Image.open(os.path.join(G, 'max_3_after_import.png')).convert('RGB')
blur(im, (1438, 56, 1680, 84))
save(im, 'max_3_after_import.png', max_w=1600)
save(Image.open(os.path.join(G, 'max_4_render.png')), 'max_4_render.png', max_w=1200)

# ---------------------------------------------------------------- Blender
im = pad(Image.open(os.path.join(G, 'bl_1_prefs.png')).convert('RGB'))
box(im, (8 + 20, 177 + 20, 151 + 20, 198 + 20), '1')        # Get Extensions
box(im, (812 + 20, 9 + 20, 830 + 20, 27 + 20), '2')         # last v menu
save(im, 'blender_1_prefs.png')

im = pad(Image.open(os.path.join(G, 'bl_2_prefs_menu.png')).convert('RGB'))
box(im, (650 + 20, 137 + 20, 826 + 20, 155 + 20), '3')      # Install from Disk...
save(im, 'blender_2_install_from_disk.png')

im = Image.open(os.path.join(G, 'bl_3_import_menu.png')).convert('RGB').crop((0, 0, 700, 420))
im = pad(im)
box(im, (865 - 830 + 20 + 0, 203 + 20, 1095 - 830 + 20, 221 + 20), None)
save(im, 'blender_3_import_menu.png')

im = Image.open(os.path.join(G, 'bl_4_file_browser.png')).convert('RGB').crop((240, 0, 1060, 600))
box(im, (588, 47, 818, 326), '1')                            # options panel
box(im, (550, 567, 677, 591), '2')                           # Import PT ASE
save(pad(im), 'blender_4_file_browser.png')

save(Image.open(os.path.join(B, 'gui_mid_status.png')), 'blender_5_progress_bar.png', max_w=1400)
im = Image.open(os.path.join(B, 'gui_after_import.png')).convert('RGB')
save(im.crop((0, 0, int(im.width * 0.82), im.height)), 'blender_6_after_import.png', max_w=1600)

# ---------------------------------------------------------------- export
im = pad(Image.open(os.path.join(G, 'max_1_dialog.png')).convert('RGB'))
box(im, (30 + 20, 333 + 20, 287 + 20, 353 + 20), '1')     # Export selected as ASE
box(im, (20 + 20, 361 + 20, 287 + 20, 375 + 20), '2')     # copy textures checkbox
save(im, 'max_5_export.png')
im = Image.open(os.path.join(G, 'bl_7_export_menu.png')).convert('RGB').crop((0, 0, 700, 460))
im = pad(im)
box(im, (35 + 20, 203 + 20, 245 + 20, 221 + 20), None)
save(im, 'blender_7_export_menu.png')
im = Image.open(os.path.join(G, 'bl_8_export_browser.png')).convert('RGB').crop((240, 0, 1060, 600))
box(im, (588, 75, 812, 220), '1')
box(im, (548, 567, 675, 591), '2')
save(pad(im), 'blender_8_export_options.png')

# ---------------------------------------------------------------- results
im = Image.open(os.path.join(P, 'world_overview_terrain.png'))
bg = Image.new('RGB', im.size, (24, 24, 28))
bg.paste(im, (0, 0), im if im.mode == 'RGBA' else None)
save(bg, 'world_overview.png', max_w=1100)
save(Image.open(os.path.join(P, 'village-1_original_ASE_vs_from_SMD.png')), 'compare_original_vs_converted.png')
save(Image.open(os.path.join(P, 'Mcave_with_props_3dsmax.png')), 'max_props_example.png', max_w=1200)
save(Image.open(os.path.join(P, 'SeaA_blender.png')), 'blender_lightmaps_example.png', max_w=1200)
