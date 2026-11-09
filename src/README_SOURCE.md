# PristonTale - Rosetta Stone: source code (v1.5.0)

Everything needed to rebuild the release:
- the converter, in C# (shipped) and in Python (reference);
- the 3ds Max import and export scripts;
- the Blender import and export add-on;
- the user guide.

```
src\                         C# solution (PTTools.sln)
  PTSmd\                     library: SMD/SMB reader, motion tables + skeleton lookup (Motion.cs),
                             texture codec, ASE writer, batch runner; ClientFiles.cs (sounds, text,
                             .inx <-> .ini) and ClientConvert.cs (whole game folder, back to game format)
  PT_SMD2ASE\                WinForms app (drag & drop), net48 + net8.0-windows; Plugins.cs finds
                             3ds Max / Blender and installs the plug-ins
  smd2ase\                   command-line app, net48 + net8.0
  Guide\                     Guide_3dsMax.html, Guide_Blender.html + Guide_images\ (+ capture_scripts\ used to make the screenshots)
  build_release.cmd          builds ..\release\PT_RosettaStone_v<ver>\ and the zip
  README_release.txt         README that ships in the release

smdanim\                     Python reference implementation (the C# port is byte-identical to it)
  smdfile.py                 SMD / SMB reader (incl. TmPrevRot cache and per-piece key tables)
  motion.py                  .inx / .ini motion tables, skeleton (.smb) lookup
  convert.py                 scene builder + ASE writer
  clientfiles.py             sounds, text, .inx <-> .ini/.inf/.in (reference for ClientFiles.cs)
  data\items.txt, skills.txt item / skill names in the game's index order (scripts\make_name_tables.py);
                             embedded into the exes
char2ase.py                  Python CLI converter
scripts\                     verification and probe scripts (see TECHNICAL.md)

tools\
  build_blender_addon.py     builds tools\dist\pt_ase_importer.zip
  blender\io_scene_pt_ase\   Blender extension (ase_import.py, ase_anim.py, ase_export.py)
  max\                       3ds Max: PT_ASE_Importer.ms, PT_ASE_Exporter.ms, PT_ASE_Reader.cs, PT_ASE_Skin.cs
```

## Building

| What | Requirement | Command |
|---|---|---|
| Release folder and zip | .NET 8 SDK (it also builds the net48 targets) and Python 3 | `src\build_release.cmd` |
| Self-contained .NET 8 exe as well | same | `src\build_release.cmd standalone` |
| Blender add-on only | Python 3 | `python tools\build_blender_addon.py` |
| Python converter | Python 3, no packages | `python char2ase.py <file or folder> -o out` |

The 3ds Max scripts need no build step. `PT_ASE_Importer.ms` compiles `PT_ASE_Reader.cs` (and `PT_ASE_Skin.cs`, which reads Skin weights through the 3ds Max SDK) itself at load time.

## Checks used for this release

| Check | Script | Result |
|---|---|---|
| C# (net48 and net8) vs Python, byte for byte | `scripts\compare_cs_py.py` | identical |
| Maps (one-mesh mode) and static objects vs the v1.0 converter | `scripts\compare_with_v1.py` | identical |
| Split maps hold exactly the faces of the one-mesh map | `scripts\check_split_same.py` | identical |
| Map split vs the original 2012 map ASE files (26 maps with unchanged faces) | `scripts\score_stage_parts.py` | 7611 objects for 7787 originals; ~85% of faces in the right object |
| Skinned bodies/heads/monsters vs the artists' original ASE | `scripts\verify_players.py` | ≤ 0.01 units |
| .smb keys vs the original 3ds Max motion ASE | `scripts\verify_motion.py` | identical |
| Blender pose vs the game's own math, whole timeline | `scripts\blender_anim_test.py` | ~0.02 units median |
| 3ds Max pose vs the game's own math | `scripts\max_anim_compare.py` | ~0.02 units median |
| New monsters with broken mesh matrices (DSH, Ebonhoof, SpiritHead, Headless, GrimHorn …): converter, Blender, 3ds Max vs the game's math, new and old files | `scripts\check_ase_vs_game.py`, `blender_anim_test.py`, `max_anim_compare.py` | ≤ 0.06 units median |
| Every char\ file of the current client (2255) | `smd2ase.exe <char> -o out` | 0 failures |
| Every weapon/item file (1227) | `smd2ase.exe <DropItem> -o out` | 0 failures |
| Import → export round trip, Blender and 3ds Max (monster, player armour, original costume, map, weapon) | `scripts\roundtrip_check.py`, `static_check.py` | bones and skin exact, poses ≤ 0.016 |
| Split map (711 objects, own pivots) import → export, Blender and 3ds Max | `scripts\blender_split_map_test.py`, `max_split_map_test.ms`, `static_check.py` | every object exact |
| Exported layout vs the developers' files (what the game's builder reads) | `scripts\ase_structure.py`, `probe_game_reader.py` | same layout |
| Every .inx of the current client (2455): decompile → compile, Python and C# | `scripts\check_inx.py`, `smd2ase.exe --check-inx <client>` | all byte-identical |
| Shipped .ini / .inf / .in → .inx (847) | `scripts\check_inx.py` | 839 identical; the other 8 (M1Bip–M8Bip.in) are older than their .inx |
| Whole-folder output (sounds, text, model info, _server), C# (net48 and net8) vs Python | `scripts\compare_clientfiles.py` | 9486 files identical |
| Whole client → readable → `--to-game`, vs the client's own files; C# texture decode vs Python | `scripts\roundtrip_client.py` | textures, sounds, music, text byte-identical apart from what the game can't read as shipped; .inx apart from folder-name case / old 120-byte layout |
| Hand-made edited files (RLE / ID / grey TGAs, top-down / gapped / bitfield BMPs, waves with LIST / extensible / 18-byte fmt, UTF-16 .ini) → `--to-game`, read the way the game's loaders read | `scripts\check_to_game.py` | the game reads the right pixels and samples |
| The developers' 2012 map `.ase` → `.smd` (`--ase2smd`), vs the game's own builds, section by section | `scripts\check_ase2smd.py` | 31/41 exact up to float steps; positions, faces, areas, lights exact (village-2 is another version) |
| The developers' 2012 model `.ase` → `.smd` + `.smb` (`--ase2model`), object by object | `scripts\check_ase2model.py` | 337: positions, faces, UVs, keys, materials exact; 182 byte-equal (the rest: older normal form) |
| Every client map: decode → encode → compared as geometry | `scripts\roundtrip_maps.py` (+ `check_ase2smd_geo.py`, `diag_roundtrip_map.py`) | every face, winding, colour, normal, light back; 29/61 identical |
| Client models: decode → encode → decode | `scripts\stable_models.py` (`roundtrip_models.py` object by object) | same `.ase` apart from a merged `.smb`'s last key (1 tick) |
| Plug-in install: 3ds Max (fresh user folder, update in place), Blender (`-c extension install-file`, scratch profile) | manual | installed and enabled |

None of the game data is included; the tools read the game client's files.
