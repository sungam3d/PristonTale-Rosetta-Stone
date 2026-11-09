# PristonTale - Rosetta Stone

**Decode Priston Tale's game files into formats you can open and edit, then encode your work back for the game.**
Models and maps go to 3ds Max and Blender with their textures, skeletons and animation; textures, sounds, Korean text
and compiled model info come out as ordinary files any program reads.

**[⬇ Download the latest release](https://github.com/sungam3d/PristonTale-Rosetta-Stone/releases/latest)**
&nbsp;·&nbsp; Windows 10/11, nothing to install &nbsp;·&nbsp; free and open source

![The Rosetta Stone window with the whole game folder dropped on DECODE](docs/images/window.png)

*(Formerly "PT SMD → ASE Converter".)*

---

## Contents

- [What it does](#what-it-does)
- [Getting started](#getting-started)
- [DECODE: game files → readable](#decode-game-files--readable)
- [Models in 3ds Max and Blender](#models-in-3ds-max-and-blender)
- [The plug-ins: install, import, export](#the-plug-ins-install-import-export)
- [ENCODE: your edits → game files](#encode-your-edits--game-files)
- [Putting your work back into the game](#putting-your-work-back-into-the-game)
- [Command line](#command-line)
- [Problems?](#problems)
- [Credits](#credits) · [Source code](#source-code) · [Licence](#licence)

---

## What it does

| | |
|---|---|
| **Models and maps** | `.smd` / `.smb` → `.ase`, the 3ds Max format the game was made with. Maps in their real world position, split into objects; weapons and items; monsters skinned and animated; player armour, heads and costumes on their class skeleton with every class motion. |
| **Textures** | The game scrambles the header of every `.bmp` / `.tga`. They come out as normal images, including a few the developers scrambled twice. |
| **Sounds** | The game's `.wav` files start with `JODO` instead of `RIFF`. They come out playable, and so does the music (`.bgm`). |
| **Text** | `.ini` `.inf` `.in` `.sin` `.msg` `.txt` `.lua` … are Korean in code page 949. They come out as UTF-8, readable in any editor. |
| **Model info** | Every compiled `.inx` (monsters, NPCs, player models) is rebuilt as the `.ini` / `.inf` / `.in` it was made from: model files, detail levels, and every animation's frames and key events. |
| **3ds Max and Blender plug-ins** | Import with textures, skeletons and animation; export back to `.ase` in the same layout as the developers' own files, so the game can rebuild its `.smd` / `.smb`. Installed with one click. |
| **Back to the game** | Edited model info, textures, sounds and text go back into the exact forms the game reads. The `.inx` compiler gives byte for byte the game's own (checked on all 2 455 `.inx` files of a current client). |

<p>
  <img src="src/Guide/Guide_images/max_map.png" alt="A map split into its objects in 3ds Max" width="49%">
  <img src="src/Guide/Guide_images/blender_character.png" alt="A character with its motion list in Blender" width="49%">
</p>

---

## Getting started

1. **Download** the latest release and unzip it anywhere. Start **`PT_RosettaStone.exe`**.
   (If Windows says *"Windows protected your PC"*: **More info → Run anyway**. The program isn't signed.)
2. **Install the plug-in** for 3ds Max and/or Blender with the **Install** button in the window ([below](#install)).
3. **Drop** your Priston Tale folder, or any folder or file from it, on the blue **DECODE** box.
4. **Open** the `.ase` files in 3ds Max or Blender, and everything else in any image, sound or text editor.
5. **Edit**, export from 3ds Max / Blender, and drop your edited files on the orange **ENCODE** box.

> **Back up your game folder first**, and try one file at a time in the game.

The download also has an illustrated step-by-step guide for each program: `Guide_3dsMax.html` and `Guide_Blender.html`.

---

## DECODE: game files → readable

Drop files or folders on the **DECODE** box, click it, or use **Browse file(s)… / Browse folder…** under it.
There is nothing to choose: the window looks at what you dropped.

- **The whole game folder**, or any folder with sounds, text or `.inx` in it: every kind of file is converted into the
  output folder, in the game's own folder layout.
- **Only `.smd` files** (a map folder, a monster): the models are converted to `.ase`, with their textures.
- **One file** is converted straight away. For a folder the window first says what's in it and how long it will take:
  tick *I understand, continue* and click **Convert**.

| Game file | Becomes |
|---|---|
| `.smd` (+ `.smb`) models and maps | `.ase`, with its textures |
| `.bmp` / `.tga` textures | normal images |
| `.wav` sound effects | playable `.wav` |
| `Name.bgm` music | `Name.bgm.wav` (plays anywhere, goes back as `Name.bgm`) |
| `.ini` `.inf` `.in` `.sin` `.msg` `.txt` `.lua` … | UTF-8 text |
| `.inx` model info | the `.ini` / `.inf` / `.in` it was compiled from |

![Textures come out as normal images](docs/images/textures.png)

![A compiled .inx and the .ini rebuilt from it](docs/images/model_info.png)

![Sounds: the JODO header is fixed and the wave plays anywhere](docs/images/sounds.png)

The output folder mirrors the game:

```
PT-Readable\
  char\monster\Tees\Tees.ase     the model, skinned and animated
  char\monster\Tees\Tees.tga     its texture, readable
  char\monster\Tees\Tees.ini     its model info, rebuilt from Tees.inx
  Field\forest\fore-1.ase        a map, split into its objects
  wav\Effects\...\damage 1.wav   a sound effect, playable
  wav\BGM\Field - Desert - Pilgrim.bgm.wav     music
  _server\char\...\Tees.ini      the model info again in the game's Korean code page (for the server)
  missing_textures.txt           textures the models name but the game doesn't have
```

### Options

| Option | What it does |
|---|---|
| Copy + decrypt textures | Writes readable copies of the textures; the `.ase` points at them. Leave it ticked. |
| Baked vertex lighting | Keeps the game's lighting and shadows on maps. Untick it for maps you will put back into the game. |
| Stage lights | Writes a map's light points (lamps, fires) as lights. |
| Split maps into separate objects | Cuts a map into terrain, buildings, trees… close to how the original `.ase` files were made. Untick for one mesh. |
| Collision walls | The invisible walls of a map: separate object (easy to hide), keep in mesh, or remove. |
| Also save the model info for the server | The `_server` copy of the model info in the game's own code page. |

![A folder: what's in it and how long it takes](src/Guide/Guide_images/convert_folder.png)

### Where things are in the game folder

| Folder | Contains |
|---|---|
| `Field\` | Maps, and the objects placed on them (trees, buildings, animated props) |
| `image\Sinimage\Items\DropItem\` | Weapons (`itW…`), armour, shields and other items |
| `char\monster\` | Monsters, one folder each |
| `char\tmABCD\` | Player armour (bodies), heads and costumes, and the class motion files |
| `char\npc\` | NPCs |
| `wav\` | Sound effects and music |

---

## Models in 3ds Max and Blender

| | Import | Export |
|---|---|---|
| **Maps** | Every zone in its real world position, so maps line up as in the game. Split into objects (terrain, buildings, trees…), each with its own pivot. Game lighting, lightmaps and collision walls included. | Yes |
| **Weapons and items** | Swords, axes, staffs, armour, shields and other drop items. | Yes |
| **Monsters** | Skinned to their skeleton, with every animation (stand, walk, run, attack, die…). | Mesh, bones, skin and animation |
| **Characters** | Player armour, heads and costumes on their class skeleton, with the whole class animation and a clickable list of motions. | Mesh, bones and skin (the game takes the animation from the class file) |
| **The developers' own `.ASE` files** | Animated with the class animation, or in their bind pose. | Yes |

Models are checked against the game's own maths: they move the same as in the game, and import → export gives back the
same bones, skin and animation.

<p>
  <img src="src/Guide/Guide_images/blender_map.png" alt="A map in Blender" width="49%">
  <img src="src/Guide/Guide_images/max_character.png" alt="A character walking in 3ds Max" width="49%">
</p>
<p>
  <img src="src/Guide/Guide_images/max_weapon.png" alt="A weapon in 3ds Max" width="49%">
  <img src="src/Guide/Guide_images/blender_weapon.png" alt="A weapon in Blender" width="49%">
</p>

Characters share their class's animation file, which the converter writes next to the armour:

| File names | Class | Animation file |
|---|---|---|
| `TmbA` `TmbB` `MmbA` | Mechanician, Fighter, Knight | `m1_motions.ase` |
| `TfbD` `MfbB` | Archer, Atalanta | `m2_motions.ase` |
| `MmbD` | Magician | `m3_motions.ase` |
| `TmbC` | Pikeman | `m4_motions.ase` |
| `MfbC` | Priestess | `m5_motions.ase` |
| `TfbE` | Assassin | `m6_motions.ase` |
| `MmbE` | Shaman | `m7_motions.ase` |
| `TfbF` | Martial Artist | `m8_motions.ase` |

(`b` = body, `h` = head, `m` / `f` = male / female, a leading `C` = costume.)

---

## The plug-ins: install, import, export

### Install

The window finds every 3ds Max (2020 or newer) and Blender (4.2 or newer) on your PC, and shows an **Install**,
**Update** or **Reinstall** button for each.

![The plug-in panel](docs/images/plugins_panel.png)

- **3ds Max:** the plug-in goes into your own scripts folder, so it needs no administrator rights. If you put an older
  copy into 3ds Max's own folder by hand, that copy is updated where it is (Windows asks for permission). Restart Max,
  then **Customize → Customize User Interface → Toolbars → Category "PT Tools"**: drag **PT ASE Import** and
  **PT Motions** onto a toolbar.
- **Blender:** Blender installs and switches on the add-on itself. Close Blender first.

By hand: copy the four files from the release's `3dsMax\` folder into `<3ds Max>\scripts\startup\`. In Blender,
**Edit → Preferences → Get Extensions → ⌄ → Install from Disk…** and pick `Blender\pt_ase_importer.zip`.

<p>
  <img src="src/Guide/Guide_images/blender_1_prefs.png" alt="Blender: Get Extensions" width="49%">
  <img src="src/Guide/Guide_images/blender_2_install_from_disk.png" alt="Blender: Install from Disk" width="49%">
</p>

### Import

- **3ds Max:** click **PT ASE Import**, then **Import ASE file(s)…** or **Import all ASE in a folder…**.
- **Blender:** **File → Import → Priston Tale / 3ds Max ASE (.ase)**.

Characters and monsters come in skinned and animated. Pick a motion from the **PT Motions** list (3ds Max) or the
**PT** tab of the side panel (press **N**, Blender) and press play. *Pose: T-pose* loads only the bones, in their rest pose.

<p>
  <img src="src/Guide/Guide_images/max_dialog.png" alt="The 3ds Max importer" width="32%">
  <img src="src/Guide/Guide_images/max_motions.png" alt="PT Motions in 3ds Max" width="32%">
  <img src="src/Guide/Guide_images/blender_import_options.png" alt="The Blender importer" width="32%">
</p>

Textures are found next to the `.ase`, anywhere in the converted output folder (also after you move or share it), or in
an **Extra texture folder** you pick; the game's own scrambled textures work there too.

### Export

Select what to export and use **Export selected as ASE…** (3ds Max) or
**File → Export → Priston Tale / 3ds Max ASE (.ase)** (Blender), with the **same name as the original `.smd`**.
Keep *Copy textures* ticked.

<p>
  <img src="src/Guide/Guide_images/blender_7_export_menu.png" alt="Blender export menu" width="49%">
  <img src="src/Guide/Guide_images/blender_export_options.png" alt="Blender export options" width="49%">
</p>

Characters and monsters are written with the mesh in its rest pose, every bone, which bone each vertex follows (the game
uses one bone per vertex) and, for monsters, the animation. Keep the material names: they hold the game's keywords
(`wind:`, `wall:`, `BLEND_LAMP:` …).

---

## ENCODE: your edits → game files

Drop your edited files, or the whole output folder, on the orange **ENCODE** box. The game-format files go to
`game_format` in the output folder, in the game's folder layout:

| You edited | Becomes |
|---|---|
| `.ini` / `.inf` / `.in` model info | `.inx`, byte for byte what the game compiles, plus the text in the game's code page |
| `.bmp` / `.tga` | the game's scrambled texture |
| `.wav` | the game's sound header |
| `Name.bgm.wav` | `Name.bgm` |
| other text | the game's Korean code page |

The game's loaders are much stricter than image and sound editors, so Encode also puts files into the one layout the
game reads: RLE-packed TGAs (GIMP's default) are unpacked, a TGA image ID is left out, grey images become colour,
upside-down BMPs are flipped, and wave files with extra chunks (most sound editors add them) are rewritten.

**Read the `note` lines in the log.** They say what was changed, or what the game would not read the way you meant:
an unknown weapon, class or skill name, a `// comment` after a motion's frames, a character the Korean code page
doesn't have, a float or 24-bit sound.

![Encode with notes in the log](docs/images/encode_notes.png)

- Keep the game's folder names (`char\monster\Tees\…`): an `.inx` stores a checksum of its own path.
- Dropping the whole output folder is fine: its `_server` copy and any earlier `game_format` output are left out.

---

## Putting your work back into the game

When the game finds an `.ase` without a matching `.smd`, it builds the `.smd` (and for animated models the `.smb`)
itself when it starts.

1. **Back up** the original files.
2. Export with the **same name** as the original `.smd` (`fore-1.ase` for `fore-1.smd`, `Tees.ase` for `Tees.smd`).
3. Copy the `.ase` and its textures into the original's folder in the game.
4. Remove or rename the old files the game should rebuild:

| Model | Remove | Keep |
|---|---|---|
| Maps, map objects, weapons, items | its `.smd` | |
| Player armour, heads, costumes | its `.smd` | the class files `m1.smb` … `m8.smb` |
| Monster with its animation in the same file (e.g. `Tees`) | its `.smd` and `.smb` | its `.inx` |
| Monster with a separate motion file (e.g. `MonGknight-model` + `mGknight`) | the model's `.smd` | the motion `.smb` and the `.inx` |

5. Model info, textures and sounds you changed: copy them from `game_format` over the game's files.

For maps going back into the game, convert with **Baked vertex lighting** unticked, or the game lights them twice.

---

## Command line

`smd2ase.exe` does everything the window does, for scripts and batch files:

```
smd2ase "<game>\Field" -o D:\PT-ASE --textures              models and maps -> .ase
smd2ase --client "<game>" -o D:\PT-Readable                 the whole game folder (like DECODE)
smd2ase --to-game D:\PT-Readable\char\monster\Tees -o D:\PT-Game    edited files -> game (like ENCODE)
smd2ase --check-inx "<game>"                                every .inx decompiles and compiles back exactly?
smd2ase --help                                              every option
```

---

## Problems?

| | |
|---|---|
| **"PT Tools" is missing in 3ds Max** | Check the window shows the plug-in as installed (or that the 4 files are in `scripts\startup`), then restart 3ds Max. |
| **The model is white or untextured** | Keep the output folder together, or set *Extra texture folder*. Textures the game itself doesn't have are listed in `missing_textures.txt`. |
| **A character comes in T-pose** | Check *Pose* is *Animated* and the class file (`m1_motions.ase` … `m8_motions.ase`) is next to the `.ase`. |
| **The add-on is missing in Blender** | Close Blender, click **Reinstall** in the window, and start Blender again. |
| **Nothing shows after importing** | Maps sit far from the centre: zoom to everything (Shift+Ctrl+Z in 3ds Max, Home in Blender). |
| **The game doesn't show my change** | Check the file name matches the original and the old `.smd` / `.smb` is removed (table above), and read the ENCODE notes. |

Known limits: monsters that keep their animation in a separate motion file can have their model and skin edited, but not
their animation replaced yet. The game's own rebuild from `.ase` can only be tested in the game: please report what you find.

---

## Credits

- **[bobsobol](https://forum.ragezone.com/threads/pt-file-patcher.684994/)** for **PT File Patcher** (and TGAPatch
  before it), the tool that first made Priston Tale's `.tga`, `.bmp`, `.wav` and `.bgm` files open in ordinary image and
  sound editors, shared with its source on RaGEZONE. Rosetta Stone's texture and sound decoding stands on that work, and
  on **Obscura**'s BMPPatcher and WAVPatcher that it built on.
- The Priston Tale community on RaGEZONE, for years of shared research.

---

## Source code

| Folder | Contents |
|---|---|
| `src\` | The program in C#: the window (`PT_SMD2ASE\`), the command line (`smd2ase\`) and the library (`PTSmd\`), plus the guides and the release build script |
| `smdanim\` | The same converter in Python, the reference: the C# output is byte-identical to it |
| `tools\max\`, `tools\blender\` | The 3ds Max and Blender plug-ins |
| `scripts\` | The checks used to verify the converter and plug-ins against the game |
| `docs\TECHNICAL.md` | How the game's formats work (`.smd`, `.smb`, `.inx`, the scrambled headers, what the game's loaders accept) and what was verified |

Build with `src\build_release.cmd` (needs the .NET 8 SDK and Python 3). See [src/README_SOURCE.md](src/README_SOURCE.md).
No game files are included: you need your own Priston Tale client.

## Licence

[MIT](LICENSE), except the Blender add-on (`tools/blender/io_scene_pt_ase/`), which is GPL-3.0-or-later as Blender
requires for add-ons.

This is a fan-made tool and isn't affiliated with or endorsed by the makers of Priston Tale. Priston Tale and its game
data belong to their respective owners.
