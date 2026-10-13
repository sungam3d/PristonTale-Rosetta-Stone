# SMD-ANIM

Convert Priston Tale **characters and monsters** (skinned `.smd` meshes and `.smb` skeleton/animation files) to ASE with
bones and animation. The ASE files then go into 3ds Max and Blender, and can be exported back to the game.

This is a separate project. It started from a copy of the PT-World-Map converter (`smdanim/` is a copy of
`PT-World-Map/tools/ptsmd`), and nothing in PT-World-Map is changed by it.

Data used: `X:\Projects\PT-World-Map\char\char`
- `tmABCD\`: character bodies, heads and armours. It also has 742 original artist `.ASE` files to verify against.
- `monster\`: one folder per monster.

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

## Roadmap

1. **Animation reader:** rotation, position and scale keys per bone, already parsed by `smdanim/smdfile.py`. Verify them against the
   original `.ASE` files' `*TM_ANIMATION` blocks in `tmABCD` and the monster folders.
2. **Motion tables:** parse the `.ini` files (CP949) into named frame ranges, and work out the `.inx` / `.in` link files.
3. **Character / monster → ASE:**
   - the mesh in bind pose, with `*PHYSIQUE` blocks;
   - the bones as objects with hierarchy;
   - `*TM_ANIMATION` for the whole timeline, or one named motion.

   Skeleton choice: own `.smb` → class skeleton from `.ini` / name → manual override.
4. **3ds Max:** import bones and Skin (one bone per vertex) plus animation. Export back with `*PHYSIQUE` and bones.
5. **Blender:**
   - import an armature, with one vertex group per bone and an action per motion (or markers on one timeline);
   - export back with the rigid-skinning rule enforced.
6. **Verification:** compare against the 742 original character ASE files and the monster ASE files, the same way
   PT-World-Map was verified against the 2012 map files.
