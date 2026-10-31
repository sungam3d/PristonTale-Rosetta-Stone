-- 3dsmaxbatch: import split maps (many objects), report object count, time and pivots, export them back.
(
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Exporter.ms"
    for f in #(@"X:\Projects\SMD-ANIM\work\split_test\village-1.ase", @"X:\Projects\SMD-ANIM\work\split_test\forever-fall-01.ase") do
    (
        resetMaxFile #noPrompt
        local t = timestamp()
        local nodes = PTASE_ImportFile f
        local dt = (timestamp() - t) / 1000.0
        local nf = 0
        for n in geometry do nf += getNumFaces n
        format "IMPORT % : % objects, % faces, % s\n" (filenameFromPath f) geometry.count nf dt
        -- every object's pivot should sit in the middle of its bounding box
        local worst = 0.0
        local atOrigin = 0
        for n in geometry do
        (
            local c = (n.min + n.max) / 2.0
            worst = amax worst (distance n.pivot c)
            if length n.pivot < 1.0 do atOrigin += 1
        )
        format "PIVOTS % : furthest pivot from its box centre %, pivots at the origin %\n" (filenameFromPath f) worst atOrigin
        t = timestamp()
        local out = (getFilenamePath f) + "rt_max_" + (filenameFromPath f)
        PTASE_Export out nodes:(geometry as array) copyTextures:false
        format "EXPORT % : % s\n" (filenameFromPath out) ((timestamp() - t) / 1000.0)
    )
)
