-- 3dsmaxbatch: original artist ASE textures found via the extra texture folder (scrambled game
-- files, decoded on the fly) and via the converter's textures\ folder next to the .ase.
(
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    local o = execute "PTASE_Opts"
    o[10] = #tpose
    fn report nodes label =
    (
        local maps = #()
        for n in nodes where n.material != undefined do
            for m in getClassInstances BitmapTexture target:n.material do appendIfUnique maps m.filename
        local ok = for f in maps where doesFileExist f and (openBitMap f) != undefined collect f
        format "TEX % : % bitmaps, % readable  %\n" label maps.count ok.count (for f in maps collect filenameFromPath f)
    )
    resetMaxFile #noPrompt
    o[7] = @"C:\Program Files (x86)\MasangSoft\PristonTale(Test)\char\tmABCD"
    report (PTASE_ImportFile @"X:\Projects\SMD-ANIM\Martial Artist ASE\TfbF01.ASE" opts:o) "extra-folder"
    resetMaxFile #noPrompt
    o[7] = ""
    report (PTASE_ImportFile @"X:\Projects\SMD-ANIM\work\ma_out\TfbF01.ASE" opts:o) "textures-subfolder"
)
