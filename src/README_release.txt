PristonTale - Rosetta Stone  v1.5.0
===================================

Turns Priston Tale game files (.smd) into .ase files for 3ds Max and Blender:
maps, weapons and items, monsters and characters - with textures, skeletons
and animation. Drop the whole game folder in to also get playable sounds,
readable (UTF-8) Korean text and the .ini/.inf/.in behind every compiled .inx.

>>> Open Guide_3dsMax.html or Guide_Blender.html for the illustrated guide. <<<


QUICK START
-----------
1. Convert
   Double-click PT_RosettaStone.exe and drag an .smd file or a folder onto it.
   (Maps: Field\   Weapons/items: image\Sinimage\Items\DropItem\
    Monsters: char\monster\   Player armour/heads: char\tmABCD\)
   Maps are split into separate objects like the original .ase files
   (untick "Split maps into separate objects" for one mesh).
   Keep the output folder together - the .ase files need the textures folder
   and, for player armour/heads, the m1_motions.ase ... m8_motions.ase files.

   Drop the whole game folder (or any folder with sounds, text or .inx in it)
   and every kind of file is converted, in the game's own folder layout:
     .smd -> .ase    .bmp/.tga -> normal images    .wav -> playable (X.bgm -> X.bgm.wav)
     .inf .ini .in .sin .msg .txt .lua -> UTF-8 text
     .inx (monster/NPC/player model info) -> the .ini/.inf/.in it was built from
     _server\  the model info again in the game's Korean code page (for the server)
   The ENCODE box (right) does the reverse for edited files:
     .ase maps and models -> .smd (+ .smb), built the way the game builds them,
     .ini/.inf/.in -> .inx, .wav/.bmp/.tga -> the game's headers, in the layout the
     game's loaders read (RLE TGAs unpacked etc.). Read the "note" lines in the log:
     they name what the game would not read as you meant (unknown weapon names ...,
   too many faces in one spot of a map: older clients crash near more than 1000).
   Keep the game's folder names (char\monster\...): the .inx stores a checksum of its path.

2. Plug-ins: the window lists 3ds Max and Blender found on this PC, with an
   Install / Update button for each. Or by hand:

2a. 3ds Max 2020+
   Copy the 4 files from 3dsMax\ into  <3ds Max>\scripts\startup\  and restart Max.
   Menu "Priston Tale" > Import... / Export... / Motions...  (also File > Import / Export).
   Import: click what you have (map as in the game, map for editing, character
   animated / T-pose / mesh only, or an animation such as m1.smb onto the character
   in the scene); .smd / .smb open directly when installed from PT_RosettaStone.exe.
   Export: selected objects or everything, hidden collision walls included.

2b. Blender 4.2+
   Edit > Preferences > Get Extensions > last v (top right) > Install from Disk...
   > Blender\pt_ase_importer.zip
   Priston Tale menu > Import... / Export...: the same windows as in 3ds Max
   (also File > Import / Export > Priston Tale); .smd / .smb open directly.
   Characters: press N in the 3D view, "PT" tab, click a motion.

Both importers: Pose = Animated or T-pose (bind pose); "Animation file" picks a
motions file yourself. Original artist .ASE files (e.g. TfbF01.ASE) have no animation
inside: convert any armour of the same class first (gives m8_motions.ase for Martial
Artist) and keep the originals in that folder or pick the file - see the guides.

3. Back into the game
   Export with the same name as the original .smd, copy the .ase + textures into
   the game folder, remove the old .smd (a monster with its animation in the same
   file: also its .smb), start the game. Back up first; the guides list exactly
   which files to remove for each kind of model.
   Characters/monsters export with bones + skin (+ animation for monsters).
   Not yet: replacing the animation of monsters that use a separate motion file.

"Windows protected your PC"?  More info > Run anyway (the program isn't signed).

Command line: smd2ase.exe --help
Source code:  Source\  (see Source\README_SOURCE.md)
              https://github.com/sungam3d/PristonTale-Rosetta-Stone
Licence:      MIT (LICENSE.txt); the Blender add-on is GPL-3.0-or-later.

Credits:      Sandurr's SMD Reader (2010), the original .smd/.smb -> .ase converter, which the
              model conversion here grew from.
              bobsobol's PT File Patcher (https://forum.ragezone.com/threads/pt-file-patcher.684994/)
              first opened up the game's .tga/.bmp/.wav/.bgm files; the decoding here stands on it
              (and on Obscura's BMPPatcher and WAVPatcher that it built on).
