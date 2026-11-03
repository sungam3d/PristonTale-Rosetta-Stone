-- 3dsmaxbatch test: import a character and dump every bone's world transform at some frames.
-- Job file %TEMP%\pt_max_bjob.txt: ase / output txt / frames / pose (#animated|#tpose) / animation file
(
    local job = openFile (sysInfo.tempdir + "pt_max_bjob.txt")
    local ase = readLine job, outp = readLine job, frs = execute (readLine job)
    local pose = if eof job then "#animated" else readLine job
    local animf = if eof job then "" else readLine job
    close job
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    local o = execute "PTASE_Opts"
    o[10] = execute pose
    o[11] = animf
    resetMaxFile #noPrompt
    local nodes = PTASE_ImportFile ase opts:o
    local bones = for n in nodes where getUserProp n "pt_bind" != undefined collect n
    format "BONES: %\n" bones.count
    local f = createFile outp
    for fr in frs do
    (
        format "FRAME %\n" fr to:f
        for b in bones do
        (
            local t = at time fr b.transform
            format "%|% % % % % % % % % % % %\n" b.name t.row1.x t.row1.y t.row1.z t.row2.x t.row2.y t.row2.z \
                t.row3.x t.row3.y t.row3.z t.row4.x t.row4.y t.row4.z to:f
        )
    )
    close f
    format "DONE\n"
)
