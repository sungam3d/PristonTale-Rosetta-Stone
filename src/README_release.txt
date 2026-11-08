PT SMD -> ASE Converter  v1.4.0
===============================

Turns Priston Tale game files (.smd) into .ase files for 3ds Max and Blender:
maps, weapons and items, monsters and characters - with textures, skeletons
and animation. Drop the whole game folder in to also get playable sounds,
readable (UTF-8) Korean text and the .ini/.inf/.in behind every compiled .inx.

>>> Open Guide_3dsMax.html or Guide_Blender.html for the illustrated guide. <<<


QUICK START
-----------
1. Convert
   Double-click PT_SMD2ASE.exe and drag an .smd file or a folder onto it.
   (Maps: Field\   Weapons/items: image\Sinimage\Items\DropItem\
    Monsters: char\monster\   Player armour/heads: char\tmABCD\)
   Maps are split into separate objects like the original .ase files
   (untick "Split maps into separate objects" for one mesh).
   Keep the output folder together - the .ase files need the textures folder
   and, for player armour/heads, the m1_motions.ase ... m8_motions.ase files.

   The whole game folder (Convert: "Whole game folder", picked by itself when
   you drop the game folder) gives, in the game's own folder layout:
     .smd -> .ase    .bmp/.tga -> normal images    .wav -> playable (.bgm -> .wav)
     .inf .ini .in .sin .msg .txt .lua -> UTF-8 text
     .inx (monster/NPC/player model info) -> the .ini/.inf/.in it was built from
     _server\  the model info again in the game's Korean code page (for the server)
   "Back to game format..." does the reverse for edited files:
     .ini/.inf/.in -> .inx, .wav/.bmp/.tga -> the game's headers.
   Keep the game's folder names (char\monster\...): the .inx stores a checksum of its path.

2. Plug-ins: the window lists 3ds Max and Blender found on this PC, with an
   Install / Update button for each. Or by hand:

2a. 3ds Max 2020+
   Copy the 4 files from 3dsMax\ into  <3ds Max>\scripts\startup\  and restart Max.
   Customize > Customize User Interface > Toolbars > Category "PT Tools":
   drag "PT ASE Import" and "PT Motions" onto a toolbar.
   Characters come in skinned and animated; the PT Motions list plays one motion.

2b. Blender 4.2+
   Edit > Preferences > Get Extensions > last v (top right) > Install from Disk...
   > Blender\pt_ase_importer.zip
   File > Import > Priston Tale / 3ds Max ASE (.ase)
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
              https://github.com/sungam3d/Pristontale-SMD-to-ASE-Converter
Licence:      MIT (LICENSE.txt); the Blender add-on is GPL-3.0-or-later.
