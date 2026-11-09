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

## What the game does with animation, and how the plug-ins follow it (v1.3.3)

Engine rules (`smObj3d.cpp` `TmAnimation` / `GetRotFrame`, `smRead3d.cpp`), all modelled in `scripts\game_pose.py`
and `scripts\ase_pose.py`, which the test suites compare against:

- **A channel without keys** while others have some: the node's stored local value, read from `*TM_POS` and
  `*TM_ROTAXIS` / `*TM_ROTANGLE`, which 3ds Max writes relative to the parent. The rows are world space and rounded,
  so a helper scaled to 0.017 is far off there. No scale.
- **A node without keys at all:** `Tm × parent->TmInvert`, scale and skew included. A mirrored one (IceSerpent's wing
  bones) is written by the converter as a negative scale next to a proper rotation.
- **Glued files:** a motion piece counts as keyed by rotation or position keys, or by scale keys that do not start at
  the first one (`NumTmScale > 0`). frost's weapon scale keys therefore never play; the converter now leaves them out.
- **Between two keys** the game slerps from a zero quaternion towards the key's turn, i.e. it blends the matrix towards
  the turn: the short way round. 3ds Max writes a windmill turning 0.34 rad a frame as "5.94 rad about −z"; readers that
  turn 5.94 rad spin the long way between frames.
- Before the first key the first key's value holds; from a channel's last key on, the stored value (the last key itself
  is never shown, and some files carry junk there: Grangium scales a bone to 0 at its last tick).
- **Skinning** uses each bone's bind pose as written (bones scaled 0.89 in many monsters, 8.8 noise in all). Blender
  moves the skinned vertices once by `rigid rest × written bind⁻¹` (`ase_anim.bind_maps`, undone on export); 3ds Max
  binds the Skin with the bones at the written bind pose and then puts them back, so the mesh itself is unchanged.
- **Rigid parts of characters** with their own keys and an empty `*PHYSIQUE` (Deius' Circle001, FlameMaiden's
  `bip01 Bone00x`) ride on their bone and play their keys; the empty `*PHYSIQUE` is written back (it marks a mesh,
  not a bone).

Program limits worked around:

- 3ds Max: a linear rotation controller turns the way the stored quaternions say, so keys are kept on one side
  (a sign flip spun bones 180°); Auto Key's extra frame-0 key is removed (salon's keys start at frame −30); keys are
  read from the controllers rather than world matrices (32-bit floats lose 0.004 at map coordinates); a Multi/Sub
  material holds at most 1000 sub-materials (lost.ASE has a 3467-slot one: the used ids are packed); a skewed pivot is
  squared (a node holds skew only approximately); Skin weights are read through the SDK (`PT_ASE_Skin.cs`), because
  skinOps needs the Modify panel (a second per mesh: a 45-mesh armour exported in minutes, now 0.2 s).
- Blender: a bone pointing along −Y has an ill-conditioned roll, which far from the origin came out 13° off on the Bip
  props of the Iron maps; such bones point the other way (`ase_anim.AXIS_FLIP`). Fine turns are sampled at whole
  ticks, and "the bone is unchanged" checks allow for float steps far from the origin.

Test suites: `scripts\bltest\run_suite.py` (Blender) and `scripts\maxtest\run_max_suite.py` (3ds Max) import every
file, check placement, the pose against the game (characters/monsters) or the ASE's own animation (props), export,
compare with the original (geometry, UVs, materials, bones, skin, poses) and import the export again
(`scripts\maxtest\summary.py` sums a run up). Last runs:

| | Blender, all 4509 files | 3ds Max, 1337 files (all monsters, NPCs, props, originals) |
|---|---|---|
| Errors | 0 | 0 |
| Pose vs the game, median / typical worst | 0.0055 / 0.3 | 0.015 / 0.3 |
| Moving props vs their ASE, worst | 0.018 | 0.0095 |
| Export → same poses, worst | 0.045 (an original Bip prop) | 0.007 |
| Files flagged | 38 | 26 |

What is still flagged is game data, not the plug-ins: 17 monsters where the converter's ASE is 0.5–1.1 off the
game's 8.8 maths (Monsliver, Monnazz …), R_Ground at its very last tick, i1-ani05_Bip (a bone whose stored matrices
put it 130 000 units out), objects of original maps parented to 3ds Max groups (the game ignores groups), big maps at
float precision (0.01–0.03), and artist files whose bones are missing (CtfbF40, TfbF06).

Before this work, 3ds Max was up to 13.8 off the game (monavelrisk-sword: a quaternion sign flip), 5.2 (spider:
scaled bind poses) and 2.6 (salon: keys before frame 0); Blender flagged 257 of the 4509 files.

## The rest of the client (v1.4.0)

`smdanim/clientfiles.py` (reference) and `src/PTSmd/ClientFiles.cs` + `ClientConvert.cs` (the exe). A survey of a
current client (5.4 GB): 12 646 `.bmp`, 5 441 `.tga`, 4 306 `.smd`, 2 825 `.wav`, 2 455 `.inx`, 1 025 `.smb`, 823 `.inf`,
645 `.part`, 541 `.sin`, 263 `.ini`, 237 `.msg`, 11 `.bgm`.

**Sounds.** 2 720 of the `.wav` files start with `JODO` where a wave file has `RIFF`; nothing else differs (the sizes
in the header are right); 105 are plain `RIFF` already. `.bgm` music files are ordinary waves; the readable copy is
`Name.bgm.wav` (it plays anywhere, and goes back as `Name.bgm` - `wav\Sod\BGM` holds music and sound effects side by
side, so the folder can't tell them apart).

**Text.** `.inf .ini .in .sin .msg .txt .lua .cht` are Korean in code page 949 (none are UTF-8; `.part` particle
scripts are ASCII). The readable copies are UTF-8 with a byte-order mark; ASCII files and anything that isn't clean
CP949 are left as they are.

**`.inx`** is the compiled `smMODELINFO` (`fileread.cpp` `AddModelDecode`) that the game writes from a model's
`.ini` (monsters, NPCs), `.inf` (player armour and heads) or `.in` (the class motion files `M1Bip` … `M8Bip`):

| Offset | Contents |
|---|---|
| 0x000, 0x040, 0x080 | model file, motion file, sub-motion file (64 bytes each, with the `.ini`'s folder in front) |
| 0x0C0 | three detail levels (`*정밀모양` / `*보통모양` / `*저질모양`): count + 4 × 16-byte names |
| 0x18C | 512 motions: 120 bytes each in 2012 clients (one-byte item codes; 21 files of 67 084 bytes still ship), 172 in later ones (two-byte item codes; 95 268-byte files) |
| then | motion count, two path-checksum words, link file (`*파일연결`), face files, 30 face motions, the NPC / face motion rates |

A motion: state (`CHRMOTION_STATE_*`), start and end frame, four key events (ticks from the start, 160 per frame;
can be negative), the weapons it is for (`*착용무기`, indexes into `sItem[]`), classes (`*적용직업` bit mask; Assassin
0x100, Shaman 0x200, Martial Artist 0x400 came after the 2012 source), skills (`*적용기술`, indexes into
`SkillDataCode[]`), map position, repeat, key letter and which `*동작모음` file it is in.

The start/end frames of slots 10 and up are mixed with `GetSpeedSum` of the `.inx`'s own path, upper-cased
(`MotionKeyWordEncode`), when there are more than 10 motions and at most 10 face motions; the two checksum words
(`ModelKeyWordEncode`) also mix in the `*파일연결` file's checksum. So an `.inx` has to be rebuilt for the path it is
used at. What the compiler does that a rebuild has to copy exactly:
- the keywords are checked in a fixed order and a later match wins (`뛰는` → run … `만세`); stand, walk and run repeat by
  themselves; a death motion's end frame is stored 8 frames early;
- after the frames: key events, then one token (a key letter, or `반복` = repeat), then `(n)` = the motion's share
  of the NPC's idle animations, which is balanced to 100 and expanded into a 100-entry table;
- body and face motions count the `*동작모음` files together (a face motion's file number is one less);
- a detail-level name of 16+ characters runs on into the next slot (`lstrcpy`); a weapon list of 53 runs on into the
  class bits (then overwritten by `*적용직업` if there is one).

The rebuilt text uses the source's item and skill names (`smdanim/data/*.txt`, from `scripts/make_name_tables.py`);
codes the 2012 tables don't have, or have twice, are written `#n`, which the rebuild reads back. Names of the glued
`*동작모음` files aren't stored in the `.inx`, so they come out as `<motion file>_01.ASE`, `_02` ….

Checked on the whole client (`scripts/check_inx.py`, `smd2ase --check-inx`): all 2 455 `.inx` decompile and compile
back byte for byte; 839 of the 847 shipped `.ini` / `.inf` / `.in` compile to their `.inx` exactly (the other 8 are
`M1Bip.in` … `M8Bip.in`, older than their `.inx`; the converter writes the rebuilt one and keeps those as
`.shipped.in`). `scripts/compare_clientfiles.py` checks the C# whole-folder output against Python (9 486 files, all
identical, .NET Framework 4.8 and .NET 8). Through the readable UTF-8 copies and back (`--to-game`), 2 369 files come out
identical; the rest differ only in the stored folder's upper/lower case (the game ignores it; the checksum is
case-blind), in using the current 172-byte layout for the 21 old ones (`--inx-layout 120` keeps it), or (`Lilly.inx`)
in having been copied from another NPC's folder.

### Back to game format: what the game's loaders accept

The game's loaders (2012 source) are much stricter than image and sound editors, so `--to-game` / ENCODE puts edited
files into the one layout each loader reads, and says so in a note when it changes something or when the game will
not read a file as meant:
- **TGA** (`smTexture.cpp` `cTGA::LoadTga`): reads the 18-byte header and then raw pixels - it ignores the image type,
  the image ID and the colour map, and has no RLE. Editors often save RLE (GIMP does by default): RLE is unpacked, an ID
  field / colour map is left out, grey images become 24/32-bit. 16, 24 and 32-bit only.
- **BMP** (`LoadDib`): reads `bfSize` bytes and takes the pixels right after the info header and palette - it ignores
  `bfOffBits`, and reads rows bottom-up. `bfSize` is set, pixels are moved behind the header (BI_BITFIELDS 32-bit with
  the usual masks included), top-down files are flipped. 8, 24 and 32-bit, uncompressed.
- **WAV** (`Dxwav.cpp` `CreateBufferFromWaveFile`): ignores the first 4 bytes and doesn't walk the RIFF chunks - it
  wants the 16-byte `fmt ` at byte 12, then `data` (or one `fact` chunk; or an 18-byte `fmt ` + `fact`). Files with
  `LIST` / `bext` / `JUNK` chunks or `WAVE_FORMAT_EXTENSIBLE` (most editors) are rewritten to `fmt` + `data`; it always
  plays PCM, so float or 24-bit sound gets a note.
- **Text**: UTF-8 and UTF-16 (Notepad's "Unicode") are read; characters code page 949 has no place for are named
  in a note (they become `?`). The `.ini` compiler names what the game would skip silently: unknown weapons, classes,
  skills, commands, and `// comments` after a motion's frames (the game reads them as the key letter `/`).
- Inside a dropped output folder, `_server\` (the decoder's unedited copy of the model info) and `game_format\` are
  left out - before, the `_server` copy came last and overwrote the edited `.ini` and its `.inx`.

Whole client through the readable copies and back: the `.bmp` / `.tga` / `.wav` / `.bgm` / text files come back byte
for byte, apart from what the game can't read as shipped (the twice-scrambled textures and RLE TGAs below, a wave with
a `PAD ` chunk), the 105 `RIFF` waves (now `JODO`, which the loader ignores) and 5 BMPs that were unscrambled (`BM`) or
had a wrong `bfSize` (only the 14-byte file header differs).

**Twice-scrambled textures.** 131 TGAs in `Field\castle`, `Field\Fall_Game` and `Field\Iron` (`do01.tga`,
`eye_door01.tga` … used by `crystal_ani*.smd`) had their header scrambled twice: undone once, the header still makes
no sense (type 6, 43 280 × 58 052 pixels); undone twice it is a normal TGA. Two BMPs too
(`StartImage\Opening\GameServerSelect\Mokoba.BMP`, `Mokoba_U.BMP`: once undone, the pixels would start 2.8 GB into a
10 KB file). The decoders (converter, both importers) undo it again when the first pass gives no sane header. 9 TGAs
are RLE, which the 2012 loader can't read either.

**Game folder.** Paths are kept from the nearest folder that looks like a game folder (two or more of `char`,
`Field`, `image`, `Effect`, `wav` …): the client has folders named like top ones inside others (`Effect\Sky\Field`,
`image\Sinimage\Effect`, `StartImage\sky`), and `Effect\Sky\Field\Lost\lostisland.smd` used to be written over the
real `Field\Lost\lostisland.ase`. Textures found next to a model (when the path in the `.smd` is wrong) keep their
place below the game folder too: 18 names are used by different pictures in different folders (`eveninghill.tga` in
six sky folders), and the first one used to stand in for all of them.

## Status (v1.4.1)

Done and verified (see `src\README_SOURCE.md` for the check list):
1. Converter (C# exe + Python reference, byte-identical): skeleton lookup (`.inx`/`.ini` → class skeleton from the file
   name → same-name `.smb` → any `.smb` with all bones), textures found from any copy of the game folder, high-detail
   LOD only, bones as material-less meshes, `*PHYSIQUE`, `*TM_ANIMATION`, `*PT_ANIMATION` motion list, maps split into
   objects. Player classes share `m1_motions.ase` … `m8_motions.ase`.
2. 3ds Max: Point-helper bones, Skin (one bone per vertex), linear keys, time tags, PT Motions dialog; export with
   bones, skin and animation.
3. Blender: Armature, vertex groups + Armature modifier, linear action, timeline markers, PT tab motion list; export
   with bones, skin and animation.
4. Whole game folder: textures, sounds, text and `.inx` model info both ways (above); the window finds 3ds Max
   (registry) and Blender 4.2+ and installs or updates the plug-ins (Max: the user's own startup scripts folder, or an
   older copy in Max's folder where it is; Blender: `blender -c extension install-file -r user_default -e`).

Not done:
- Replacing the animation of monsters that keep it in a separate (often glued) motion file: their model and skin can
  be exported, the motion file stays the game's own.
- The game's own ASE → SMD/SMB rebuild can only be tested in the game.
