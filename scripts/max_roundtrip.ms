-- 3dsmaxbatch: import an ASE, select only the skinned mesh(es), export again.
-- Job file %TEMP%\pt_max_rt.txt: line 1 = in.ase, line 2 = out.ase, line 3 = anim mode (#auto ...),
-- line 4 = optional animation file for the import
(
    local job = openFile (sysInfo.tempdir + "pt_max_rt.txt")
    local src = readLine job, dst = readLine job, mode = execute (readLine job)
    local animf = if eof job then "" else readLine job
    close job
    fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
    local o = execute "PTASE_Opts"
    o[10] = #animated
    o[11] = animf
    resetMaxFile #noPrompt
    local nodes = PTASE_ImportFile src opts:o
    sliderTime = 37
    local meshes = for n in nodes where superClassOf n == GeometryClass collect n
    select meshes
    local t = timestamp()
    PTASE_Export dst nodes:meshes copyTextures:false anim:mode
    format "RT exported % in % ms\n" dst (timestamp() - t)
)
