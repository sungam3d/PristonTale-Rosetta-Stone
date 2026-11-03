-- 3ds Max test suite worker (3dsmaxbatch): import -> dump -> export -> re-import, per file.
-- Job list %TEMP%\pt_max_suite_<k>.txt (k from the file name in the env var PT_MAX_SUITE, default 0):
--   one job per line: in.ase|out.ase|dump.txt|prop ticks #(...)
-- Dump file: what the Python side (run_max_suite.py) compares with the file and the game.
(
    local k = systemTools.getEnvVariable "PT_MAX_SUITE"
    if k == undefined do k = "0"
    local listPath = sysInfo.tempdir + "pt_max_suite_" + k + ".txt"
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    local o = execute "PTASE_Opts"
    o[10] = #animated
    o[11] = ""
    local jobs = #()
    local jf = openFile listPath
    while not eof jf do (local l = readLine jf; if l != "" do append jobs l)
    close jf

    fn dumpVerts f n t =
    (
        local m = at time t (snapshotAsMesh n)
        format "N %\n" (getNumVerts m) to:f
        for i = 1 to getNumVerts m do
        (
            local v = getVert m i
            format "% % %\n" (formattedPrint v.x format:".6f") (formattedPrint v.y format:".6f") (formattedPrint v.z format:".6f") to:f
        )
        delete m
    )

    for job in jobs do
    (
        local p = filterString job "|"
        local src = p[1], dst = p[2], dumpPath = p[3]
        local ticks = if p.count > 3 then execute p[4] else #()
        local f = createFile dumpPath
        try
        (
            resetMaxFile #noPrompt
            PTASE_AnimMissing = #()
            local t0 = timestamp()
            local nodes = PTASE_ImportFile src opts:o
            format "IMPORT % %\n" (timestamp() - t0) nodes.count to:f
            format "RANGE % % %\n" animationRange.start.frame animationRange.end.frame frameRate to:f
            local motions = try (execute "PTASE_Motions") catch (#())
            if motions == undefined do motions = #()
            format "MOTIONS %\n" motions.count to:f
            local geoms = for n in nodes where superClassOf n == GeometryClass and getUserProp n "pt_bind" == undefined collect n
            local skinned = for n in geoms where n.modifiers.count > 0 and classOf n.modifiers[1] == Skin collect n
            local bones = for n in nodes where getUserProp n "pt_bind" != undefined collect n
            format "BONES %\n" bones.count to:f
            -- every mesh at frame 0 in world space (static ones are compared with the file)
            for n in geoms do
            (
                local kind = if (findItem skinned n) > 0 then "skin" else if n.isAnimated then "anim" else "static"
                format "MESH %|%\n" kind n.name to:f
                if kind != "skin" do dumpVerts f n 0
            )
            -- skinned meshes at some frames (compared with the game's maths)
            if skinned.count > 0 do
            (
                local frs = #(0)
                local stp = amax 1 (motions.count / 3)
                for i = 1 to motions.count by stp while frs.count < 4 do
                    append frs (floor (motions[i][2] + (motions[i][3] - motions[i][2]) * 0.4) as integer)
                for fr in frs do
                (
                    format "POSE %\n" fr to:f
                    for n in skinned do (format "SKIN %\n" n.name to:f; dumpVerts f n fr)
                )
            )
            -- moving props at the given ticks
            local props = for n in geoms where (findItem skinned n) == 0 and n.isAnimated collect n
            for t in ticks do
                for n in props do (format "PROP % %\n" t n.name to:f; dumpVerts f n ((t / 160.0) as time))
            -- export everything (collision layer included)
            for i = 0 to LayerManager.count - 1 do (LayerManager.getLayer i).ishidden = false
            local t1 = timestamp()
            PTASE_Export dst nodes:nodes copyTextures:false anim:#auto
            format "EXPORT %\n" (timestamp() - t1) to:f
            local nf = 0, nm = 0
            for n in geoms where canConvertTo n TriMeshGeometry do (nm += 1; nf += n.mesh.numfaces)
            -- re-import the export: same meshes, faces and bones
            resetMaxFile #noPrompt
            local again = PTASE_ImportFile dst opts:o
            local g2 = for n in again where superClassOf n == GeometryClass and getUserProp n "pt_bind" == undefined collect n
            local nf2 = 0
            for n in g2 where canConvertTo n TriMeshGeometry do nf2 += n.mesh.numfaces
            local b2 = for n in again where getUserProp n "pt_bind" != undefined collect n
            format "REIMPORT % % % % % %\n" nm g2.count nf nf2 bones.count b2.count to:f
            format "DONE\n" to:f
        )
        catch
        (
            format "ERROR %\n" ((getCurrentException()) as string) to:f
        )
        close f
    )
    format "SUITE DONE\n"
)
