# PT SMD → ASE: source code (v1.3.2)

Everything needed to rebuild the release:
- the converter, in C# (shipped) and in Python (reference);
- the 3ds Max import and export scripts;
- the Blender import and export add-on;
- the user guide.

```
src\                         C# solution (PTTools.sln)
  PTSmd\                     library: SMD/SMB reader, motion tables + skeleton lookup (Motion.cs),
                             texture codec, ASE writer, batch runner
  PT_SMD2ASE\                WinForms app (drag & drop), net48 + net8.0-windows
  smd2ase\                   command-line app, net48 + net8.0
  Guide\                     Guide_3dsMax.html, Guide_Blender.html + Guide_images\ (+ capture_scripts\ used to make the screenshots)
  build_release.cmd          builds ..\release\PT_SMD2ASE_v<ver>\ and the zip
  README_release.txt         README that ships in the release

smdanim\                     Python reference implementation (the C# port is byte-identical to it)
  smdfile.py                 SMD / SMB reader (incl. TmPrevRot cache and per-piece key tables)
  motion.py                  .inx / .ini motion tables, skeleton (.smb) lookup
  convert.py                 scene builder + ASE writer
char2ase.py                  Python CLI converter
scripts\                     verification and probe scripts (see README_SMD-ANIM.md)

tools\
  build_blender_addon.py     builds tools\dist\pt_ase_importer.zip
  blender\io_scene_pt_ase\   Blender extension (ase_import.py, ase_anim.py, ase_export.py)
  max\                       3ds Max: PT_ASE_Importer.ms, PT_ASE_Exporter.ms, PT_ASE_Reader.cs
```

## Building

| What | Requirement | Command |
|---|---|---|
| Release folder and zip | .NET 8 SDK (it also builds the net48 targets) and Python 3 | `src\build_release.cmd` |
| Self-contained .NET 8 exe as well | same | `src\build_release.cmd standalone` |
| Blender add-on only | Python 3 | `python tools\build_blender_addon.py` |
| Python converter | Python 3, no packages | `python char2ase.py <file or folder> -o out` |

The 3ds Max scripts need no build step. `PT_ASE_Importer.ms` compiles `PT_ASE_Reader.cs` itself at load time.

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

None of the game data is included; the tools read the game client's files.
