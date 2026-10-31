"""Build the Blender extension zip.

    python tools\\build_blender_addon.py
    -> tools\\dist\\pt_ase_importer.zip
       Blender: Edit > Preferences > Get Extensions > (last v menu, right of "Repositories")
                > Install from Disk...

The add-on only imports .ase files (made by the PT SMD -> ASE Converter); it bundles
the two small helper modules it needs from ptsmd: the ASE parser and the texture decoder
(for any still-encrypted game textures an ASE may point at).
"""
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'blender', 'io_scene_pt_ase')
PTSMD = os.path.join(os.path.dirname(HERE), 'smdanim')
DIST = os.path.join(HERE, 'dist')
ZIP_NAME = 'pt_ase_importer.zip'


def sync_helpers():
    for name in ('aseparse.py', 'textures.py'):
        shutil.copy2(os.path.join(PTSMD, name), os.path.join(SRC, name))
    old = os.path.join(SRC, 'ptsmd')
    if os.path.isdir(old):
        shutil.rmtree(old)


def build():
    sync_helpers()
    os.makedirs(DIST, exist_ok=True)
    for stale in ('pt_ase_smd_importer.zip',):
        p = os.path.join(DIST, stale)
        if os.path.exists(p):
            os.remove(p)
    out = os.path.join(DIST, ZIP_NAME)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk(SRC):
            dn[:] = [d for d in dn if d != '__pycache__']
            for f in fn:
                if f.endswith('.pyc'):
                    continue
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, SRC))   # manifest at zip root (extension layout)
    print('built', out)
    return out


if __name__ == '__main__':
    build()
