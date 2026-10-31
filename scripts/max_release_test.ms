-- Release check (3dsmaxbatch): the shipped 3ds Max scripts import a monster and a map.
(
    fileIn @"X:\Projects\SMD-ANIM\release\PT_SMD2ASE_v1.1.0\3dsMax\PT_ASE_Importer.ms"
    resetMaxFile #noPrompt
    local a = PTASE_ImportFile @"X:\Projects\SMD-ANIM\work\PT_ASE_Output\Tees.ase"
    local sk = for n in a where superClassOf n == GeometryClass and n.modifiers.count > 0 collect n
    local keys = numKeys (for n in a where n.name == "Bip01_pelvis" collect n)[1].rotation.controller
    format "RELEASE monster: % nodes, skinned % (bones %), pelvis rot keys %, motions %, range %\n" a.count sk.count \
        (if sk.count > 0 then skinOps.GetNumberBones sk[1].modifiers[1] else 0) keys (execute "PTASE_Motions.count") animationRange
    resetMaxFile #noPrompt
    local b = PTASE_ImportFile @"X:\Projects\SMD-ANIM\work\PT_ASE_Output\Field\forest\fore-3.ase"
    local faces = 0
    for n in b where superClassOf n == GeometryClass do faces += n.mesh.numfaces
    format "RELEASE map: % nodes, % faces, helpers %\n" b.count faces (for n in b where superClassOf n == Helper collect n).count
)
