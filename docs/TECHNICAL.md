# Technical notes

How Priston Tale's `.smd` / `.smb` / `.inx` files work, what the game does with them, and how the converter and the
3ds Max / Blender plug-ins were checked against it. For using the tools, see the [README](../README.md) and the guides.

The findings come from the game client's `char\` and `Field\` folders, compared with original developer `.ASE` files
(2012 maps, and a set of character/armour sources) and the `.smd` / `.smb` files the game built from them.
- `char\tmABCD\`: character bodies, heads and armours.
- `char\monster\`: one folder per monster.
- `Field\`: maps and the objects placed on them.

---

## How `.smd` and `.smb` fit together

A Priston Tale character is built from two kinds of file. Neither works without the other.

| File | Contains |
|---|---|
| `.smd` (mesh) | The skin: vertices, faces, UVs, materials. Each vertex also carries the **name of one bone** (`Bip01 L Clavicle`, `Bip01 Spine1`…), and its position is stored **relative to that bone**, not in world space. |
| `.smb` (skeleton) | The bones: names, hierarchy, the bind pose (each bone's resting transform) and the animation keys for every frame of every motion, laid out on one long timeline. |

The game builds the character at run time:

```
vertex position (frame f) = vertex position in bone space  ×  bone's transform at frame f
```

That's why a character mesh can't be converted or exported on its own.

1. **The mesh has no shape without the skeleton.** Its vertices are stored relative to bones. The old converter needed the `.smb`
   to place them anywhere at all, and failed when the right skeleton wasn't found. The PT-World-Map converter does the same
   for skinned map props: it finds the matching `.smb` by name.
2. **"Static bones in the model"** means the ASE you export back must contain the bones too. In the original artist files
   (for example `tmbA01.ASE`), the biped bones are ordinary objects in the same scene, and every mesh has a
   `*PHYSIQUE` block that names one bone per vertex:
   ```
   *PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE  0  "Bip01 L Clavicle"
   ```
   The game's ASE loader splits that one ASE into the `.smd` (mesh + bone names) and the `.smb` (bones + animation). If the
   ASE has no bones, there's nothing to bind the vertices to and nothing for the `.smb` to drive.
3. **The bone names must match the skeleton exactly.** An armour made for the Knight must use the Knight skeleton's bone
   names (`m1.smb`). The motion files (`M1-motion1.smb` … `M1-motion11.smb`) only drive bones whose names they know.
4. **Skinning is rigid: one bone per vertex.** Priston Tale has no blended weights. A vertex is either on the forearm or on
   the upper arm, never in between. Models made in Max or Blender must follow that rule, or the game will snap each vertex
   to a single bone.

### How a model knows its skeleton and motions

Every character and monster has an `.ini` file. They're written in Korean, CP949 encoding:

| Key | Meaning | Example |
|---|---|---|
| `*모양파일` | shape file: the mesh | `worldtogo.ASE` → `.smd` |
| `*정밀모양` / `*보통모양` / `*저질모양` | high / medium / low detail object names | `"TAHA01"` |
| `*동작파일` | motion file: skeleton + animation | `worldtogo.ASE` → `.smb` |
| `*동작모음` | motion collection | `"hopy.ASE"` |
| `*서있기동작 41 111 반복` | stand: frames 41–111, loop | |
| `*걷는동작` / `*뛰는동작` | walk / run | |
| `*타격동작` / `*공격동작` | hit / attack (the 3rd number is the impact frame) | `140 176 146` |
| `*죽기동작` / `*죽는동작` | death | |
| `*보조동작파일` | extra motions in another file | `worldtogo_attack.ini` |
| `*파일연결` | (characters) link to a class skeleton / motion set | `M1Bip.in` |

Monsters normally compile one ASE into both their `.smd` and `.smb`. Characters share one skeleton per class:

```
m1.smb  Knight, Mechanician, Fighter        (64 bones, 10 238 frames of motion)
m2.smb  Atalanta, Archer                    (67 bones)
m3.smb  Magician                            (102 bones)
m4.smb  Pikeman                             (58 bones)
m5.smb  Priestess                           (95 bones)
m6–m8   Assassin, Shaman, Martial Artist    (not in this char folder; newer clients)
```

---

## Findings so far

Run `python scripts\survey_models.py` and `python scripts\survey_skeletons.py`.

- **All 990 character and monster `.smd` files and all 48 `.smb` files parse** with the current reader. None of them
  fail the way they did in the old converter.
- **Monsters:** 262 of 266 have their own `.smb` that contains every bone the mesh uses. The remaining 4 have no `.smb` of
  their own and must borrow one:
  - `Monplant\Plant-b/c/d.smd`, which probably use `Plant-a`'s skeleton;
  - `Monshadow\Monshadow-01.smd`.
- **Characters:** 719 of the 724 meshes have no same-name `.smb`; they use the class skeletons.
  - Every one fits at least one of `m1`–`m5`.
  - 471 fit **all** of them, because the biped bone names are shared.
  - The bind poses (bone lengths and proportions) differ per class, so the class must come from the `.ini` or the file
    name, not from "the first skeleton that fits".
- Likely reasons the old converter failed on some newer monsters:
  - It only looked for an `.smb` with the same name.
  - It assumed one object per file.
  - It sized the physique records inconsistently: it stepped 0x32 per vertex in one place and 0x20 in another, so
    multi-object skinned files read past the end.

  The current reader computes every record size from the file header. It reads all 990 files and lands exactly on the end of each.

## Animation data, decoded

- **Keys.** `.smb` rotation keys are deltas: orientation_i = orientation_(i-1) turned by key i (the first key is absolute).
  Position keys are parent-relative, scale keys absolute. 160 ticks a frame, 30 fps. They are identical to the
  `*TM_ANIMATION` samples of the original 3ds Max motion files (`scripts\verify_motion.py`: difference 0).
- **TmPrevRot cache** (64 bytes per rotation key): the rotation the game actually uses at every key. Glued motion files
  restart *some* bones at the first key of each piece, so the converter rebuilds every delta from this cache.
- **Glued timelines.** `m1.smb` etc. are several motion ASE files glued end to end. The `.smb` header (count at 0x28,
  entries at 0x2C) holds each piece's (start tick, end tick); every bone has three 32-entry tables at object offset
  696 (rotation, position, scale): {start, end, first key, key count} per piece. The game only looks at the keys of the
  piece being played, and a piece without keys shows the bone's static transform.
- **`.inx`** = compiled `.ini` (`smMODELINFO`): model file, motion file, death sub-model, three LOD name groups, then
  512 motion records (120 bytes in 2012 files, 172 now) starting at 0x18C; the count follows the array. A record holds the
  state code (0x40 stand, 0x50 walk, 0x60 run, 0x100 attack, 0x110 damage, 0x120 die, 0x150 skill …), start/end frames
  stored as byte0 | byte2 << 8, event frames in ticks, loop flag and the 1-based piece number.
- **Quirks handled:** a few keys store "no turn" as w = -1 (taken the shortest way round); tiny turns need
  `atan2(|xyz|, w)`, not `acos(w)`; Python 3.12's compensated `sum()` is avoided so C# and Python stay byte-identical.

- **Original artist character ASEs** (e.g. `Martial Artist ASE\`) hold bones in the bind pose and no animation. The game
  skins them on the **class skeleton**, not on the bones saved in the file: costume files (`Ctfb…`) carry older bones
  (~1 unit off, up to 2.3) and even a different parent (`Bip01 L Thigh` under `Spine` instead of `Pelvis`), yet the game's
  `.smd` equals the artist vertices placed on the class bones (`scripts\check_costume_bind.py`). The importers therefore
  take rest pose + hierarchy from the class motions file when animating; extra costume bones (hair, tails) keep their
  offset from their parent. Result: original files animate like the game (≤ 0.12 units, `scripts\blender_artist_test.py`,
  `scripts\max_anim_compare.py --nn`).

- **What the game's own ASE → SMD/SMB builder keeps** (`scripts\probe_game_reader.py`, from the developers' ASE files and
  the .smd/.smb the game built from them): meshes **with** a material → the model (.smd, with *PHYSIQUE); meshes
  **without** a material → the skeleton (.smb, with their *TM_ANIMATION); helper objects → ignored. So bones are
  written as small material-less meshes (Biped's diamond, or the bone's own shape when the .smb still has it).
- Monster layouts in the client (`scripts\survey_monster_files.py`): 264 keep model and animation in one file
  (Tees.ase → Tees.smd + Tees.smb); ~165 use a separate motion file (MonGknight-model + mGknight), ~100 of them glued
  from several motion ASEs listed in the original .ini (the client only ships the compiled .inx).

## Map objects (v1.3.0)

A stage `.smd` is one merged mesh with no object names, but the game builds it by appending every ASE object's
vertex list as is (including unused vertices) and keeping the faces in object order (`scripts\probe_stage_ranges.py`
on village-1: 48 objects, 48 separate vertex ranges in order). So a real object boundary always sits where every
vertex used before a face is lower than every vertex used from it on. Those cuts are found exactly
(`probe_stage_split.py`: 47/47), but the same test also cuts between loose parts inside one object (243 extra cuts
on village-1; 50 000 pieces for 7 549 objects over the 26 maps whose faces did not change since 2012). Materials,
UV records and vertex fields hold nothing per object (`probe_stage_mats.py`, `probe_stage_texlinks.py`).

The converter (`_stage_parts` / `StageParts`) joins a part to the object before it when they share a material and
lie within 300 units, or to the one before that (taking the one in between along). Rules compared with
`probe_stage_rules.py` and `sweep_stage_parts.py`; scored with `score_stage_parts.py`: 7 611 objects for 7 787
originals, 87% of faces in an object that is mostly one original, 83% of each original in one object. Objects are
named `<map>_NNN_<main texture>` and get their pivot in the middle of their box, rounded to whole units (editors keep
vertices in single precision relative to the pivot; a whole-unit pivot keeps every world position exact); `--one-mesh` / the GUI tick box gives the v1.0 output (byte-identical).

## Broken mesh matrices in newer monsters (v1.3.2)

Some newer monster files (d_SH\DSH, Ebonhoof, SpiritHead, Headless) carry junk in the mesh object's
`TmInvert` (huge numbers, or all zeros). The game never uses it for a skinned mesh, since every vertex rides on
its bone, so the monsters look fine in game, but the converter turned it into a flat or squashed `*NODE_TM` and both
importers then placed the mesh with it. The converter now checks the matrix (last column 0 0 0 256, sensible size,
not flat) and falls back to the stored world matrix (`_sane_tm`). Both importers also clean up a pivot before
using it: a flat one becomes identity, and a skewed one (rows not at right angles, such as the inverse of an 8.8
fixed-point matrix in GrimHorn or DAS) gets square axes, because object transforms in Blender and 3ds Max can't hold
skew. Files converted with an older version therefore import correctly too. Checks: `scripts\check_ase_vs_game.py`
(converter vs game), `blender_anim_test.py` and `max_anim_compare.py` (both now compare every skinned mesh by
name).

## Export (v1.2.0)

Both exporters (Blender `ase_export_rig.py`, 3ds Max `PT_ASE_Exporter.ms` + `RigWriter` in `PT_ASE_Reader.cs`) write
skinned models in the developers' layout: mesh in its rest pose with *PHYSIQUE (strongest bone per vertex), bones as
material-less meshes with the exact rest numbers of the imported file, and *TM_ANIMATION (pos parent-relative,
rotation as a turn from the previous key, 9 decimals).  Animation: *Auto* writes a model's own keys (monsters) but not
a shared class animation (player armour) nor a monster's separate motion file (`*PT_MOTION_FILE`).
Round trips (`scripts\roundtrip_check.py`, `static_check.py`, `blender_roundtrip.py`, `max_roundtrip.py`):

| Model | Blender | 3ds Max |
|---|---|---|
| Tees (monster, own animation) | bones exact, skin exact, poses ≤ 0.016 | exact (≤ 0.00001) |
| MonGknight-model (separate motion file) | exact | exact |
| MmbA34 (player armour, class animation) | exact | exact |
| CtfbF12 original artist costume vs the game's model | ≤ 0.009 | ≤ 0.009 |
| fore-3 map, itWA105 weapon | exact | ≤ 0.000001 |

Blender keeps faces that share their three vertices with another face (back faces of two-sided parts, doubled
overlays) by giving them their own vertex copies; only zero-area faces are dropped.

## Status (v1.3.2)

Done and verified (see `src\README_SOURCE.md` for the check list):
1. Converter (C# exe + Python reference, byte-identical): skeleton lookup (`.inx`/`.ini` → class skeleton from the file
   name → same-name `.smb` → any `.smb` with all bones), textures found from any copy of the game folder, high-detail
   LOD only, bones as material-less meshes, `*PHYSIQUE`, `*TM_ANIMATION`, `*PT_ANIMATION` motion list, maps split into
   objects. Player classes share `m1_motions.ase` … `m8_motions.ase`.
2. 3ds Max: Point-helper bones, Skin (one bone per vertex), linear keys, time tags, PT Motions dialog; export with
   bones, skin and animation.
3. Blender: Armature, vertex groups + Armature modifier, linear action, timeline markers, PT tab motion list; export
   with bones, skin and animation.

Not done:
- Replacing the animation of monsters that keep it in a separate (often glued) motion file: their model and skin can
  be exported, the motion file stays the game's own.
- The game's own ASE → SMD/SMB rebuild can only be tested in the game.
