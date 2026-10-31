-- 3dsmaxbatch test: import a character and dump skinned vertices at some frames.
-- Job file %TEMP%\pt_max_job.txt: ase / output txt / frames / pose (#animated|#tpose) / animation file
(
    local job = openFile (sysInfo.tempdir + "pt_max_job.txt")
    local ase = readLine job, outp = readLine job, frs = execute (readLine job)
    local pose = if eof job then "#animated" else readLine job
    local animf = if eof job then "" else readLine job
    close job
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    local o = execute "PTASE_Opts"
    o[10] = execute pose
    o[11] = animf
    resetMaxFile #noPrompt
    local t = timestamp()
    local nodes = PTASE_ImportFile ase opts:o
    format "IMPORT: % nodes in % ms\n" nodes.count (timestamp() - t)
    local m = undefined
    for n in nodes where superClassOf n == GeometryClass and n.modifiers.count > 0 do m = n
    format "SKINNED: % modifiers:% bones:%\n" m (if m != undefined then m.modifiers.count else 0) \
           (if m != undefined then skinOps.GetNumberBones m.modifiers[1] else 0)
    format "MOTIONS: % range % missing %\n" (execute "PTASE_Motions.count") animationRange (execute "PTASE_AnimMissing")
    local f = createFile outp
    local skinned = for n in nodes where superClassOf n == GeometryClass and n.modifiers.count > 0 collect n
    for fr in frs do
    (
        format "FRAME %\n" fr to:f
        for sk in skinned do                       -- every skinned mesh, in file order
        (
            local sm = at time fr (snapshotAsMesh sk)
            for i = 1 to sm.numverts do (local v = getVert sm i; format "% % %\n" v.x v.y v.z to:f)
        )
    )
    close f
    format "DONE\n"
)
