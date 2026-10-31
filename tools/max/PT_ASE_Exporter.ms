/*
    PT ASE Exporter for 3ds Max 2020+
    ---------------------------------
    Writes ASCII Scene Export v2.00 that keeps what Priston Tale needs and the
    stock asciiexp.dle loses:
      * every UV channel (MESH_MAPPINGCHANNEL n) - lightmaps!
      * vertex colours (MESH_CVERTLIST / MESH_CFACELIST)
      * Multi/Sub materials; texture layer 0 -> MAP_DIFFUSE, layers 1+ ->
        MAP_SELFILLUM (PT convention), each with *MAP_CHANNEL
        (layers are found by walking RGB Multiply / Mix / Composite trees)
      * MAP_OPACITY, two-sided, additive, self-illum, transparency
      * NODE_TM + NODE_PARENT, omni lights
    Children of unselected parents are exported (unlike the stock exporter).

    Usage:  PTASE_Export @"C:\out\map.ase"                -- selection (or everything if nothing selected)
            PTASE_Export @"C:\out\map.ase" nodes:#($Box01)
*/

global PTASE_Export
global PTASE_TexOutDir = undefined     -- when set, textures are copied here (next to the .ase)
global PTASE_TexCopied = undefined

-- texture path written into the ASE; copies the file next to the .ase when enabled
fn PTASE_TexPath fname =
(
    if fname == undefined or fname == "" do return ""
    if PTASE_TexOutDir == undefined or not doesFileExist fname do return fname
    local nm = filenameFromPath fname
    local dst = pathConfig.appendPath PTASE_TexOutDir nm
    if not (hasDictValue PTASE_TexCopied (toLower nm)) do
    (
        if (toLower fname) != (toLower dst) do (deleteFile dst; copyFile fname dst)
        PTASE_TexCopied[toLower nm] = dst
    )
    dst
)

struct PTASE_Writer
(
    ss = undefined,
    fn fl v = (formattedPrint (v as float) format:".6f"),
    fn p3 v = ((fl v.x) + "\t" + (fl v.y) + "\t" + (fl v.z)),
    fn q s = ("\"" + (substituteString (s as string) "\"" "'") + "\"")
)

fn PTASE_Ind n = (local s = ""; for i = 1 to n do s += "\t"; s)

-- ordered bitmap layers inside a texmap tree (skips Vertex Color maps)
fn PTASE_CollectBitmaps tex out =
(
    if tex == undefined do return out
    local c = classof tex
    if c == BitmapTexture then append out tex
    else if c == RGB_Multiply then (PTASE_CollectBitmaps tex.map1 out; PTASE_CollectBitmaps tex.map2 out)
    else if c == Mix then (PTASE_CollectBitmaps tex.map1 out; PTASE_CollectBitmaps tex.map2 out)
    else if c == CompositeTexturemap then (for m in tex.mapList do PTASE_CollectBitmaps m out)
    else if c == Vertex_Color then ()
    else
    (
        for i = 1 to getNumSubTexmaps tex do PTASE_CollectBitmaps (getSubTexmap tex i) out
    )
    out
)

fn PTASE_WriteMap ss ind tag bm subno =
(
    local w = PTASE_Writer()
    local ch = 1
    try (ch = bm.coords.mapChannel) catch ()
    format "%% {\n" ind tag to:ss
    format "%\t*MAP_NAME %\n" ind (w.q bm.name) to:ss
    format "%\t*MAP_CLASS \"Bitmap\"\n" ind to:ss
    format "%\t*MAP_SUBNO %\n" ind subno to:ss
    format "%\t*MAP_AMOUNT 1.0000\n" ind to:ss
    format "%\t*BITMAP %\n" ind (w.q (PTASE_TexPath bm.filename)) to:ss
    format "%\t*MAP_TYPE Screen\n" ind to:ss
    format "%\t*MAP_CHANNEL %\n" ind ch to:ss
    local uo = 0.0, vo = 0.0, ut = 1.0, vt = 1.0, ang = 0.0
    try (uo = bm.coords.U_Offset; vo = bm.coords.V_Offset; ut = bm.coords.U_Tiling; vt = bm.coords.V_Tiling; ang = degToRad bm.coords.W_Angle) catch ()
    format "%\t*UVW_U_OFFSET %\n%\t*UVW_V_OFFSET %\n%\t*UVW_U_TILING %\n%\t*UVW_V_TILING %\n%\t*UVW_ANGLE %\n" \
        ind (w.fl uo) ind (w.fl vo) ind (w.fl ut) ind (w.fl vt) ind (w.fl ang) to:ss
    format "%\t*UVW_BLUR 1.0000\n%\t*UVW_BLUR_OFFSET 0.0000\n%\t*UVW_NOUSE_AMT 1.0000\n%\t*UVW_NOISE_SIZE 1.0000\n%\t*UVW_NOISE_LEVEL 1\n%\t*UVW_NOISE_PHASE 0.0000\n%\t*BITMAP_FILTER Pyramidal\n" \
        ind ind ind ind ind ind ind to:ss
    format "%}\n" ind to:ss
)

fn PTASE_WriteStd ss mat ind tag idx =
(
    local w = PTASE_Writer()
    format "%% % {\n" ind tag idx to:ss
    local i2 = ind + "\t"
    if mat == undefined or classof mat != StandardMaterial then
    (
        local nm = if mat == undefined then "default" else mat.name
        local dc = color 150 150 150
        try (dc = mat.diffuse) catch ()
        format "%*MATERIAL_NAME %\n%*MATERIAL_CLASS \"Standard\"\n" i2 (w.q nm) i2 to:ss
        format "%*MATERIAL_DIFFUSE %\n" i2 (w.p3 ((dc as point3) / 255.0)) to:ss
        format "%}\n" ind to:ss
        return ok
    )
    local d = (mat.diffuse as point3) / 255.0
    format "%*MATERIAL_NAME %\n" i2 (w.q mat.name) to:ss
    format "%*MATERIAL_CLASS \"Standard\"\n" i2 to:ss
    format "%*MATERIAL_AMBIENT %\n" i2 (w.p3 ((mat.ambient as point3) / 255.0)) to:ss
    format "%*MATERIAL_DIFFUSE %\n" i2 (w.p3 d) to:ss
    format "%*MATERIAL_SPECULAR %\n" i2 (w.p3 ((mat.specular as point3) / 255.0)) to:ss
    format "%*MATERIAL_SHINE %\n%*MATERIAL_SHINESTRENGTH %\n" i2 (w.fl (mat.glossiness / 100.0)) i2 (w.fl (mat.specularLevel / 100.0)) to:ss
    format "%*MATERIAL_TRANSPARENCY %\n" i2 (w.fl (1.0 - mat.opacity / 100.0)) to:ss
    format "%*MATERIAL_WIRESIZE 1.0000\n%*MATERIAL_SHADING Blinn\n%*MATERIAL_XP_FALLOFF 0.0000\n" i2 i2 i2 to:ss
    -- game-look materials use 100% self-illum as a render trick; PT's own value is not recoverable
    format "%*MATERIAL_SELFILLUM %\n" i2 (w.fl (if mat.selfIllumAmount >= 100 then 0.0 else mat.selfIllumAmount / 100.0)) to:ss
    if mat.twoSided do format "%*MATERIAL_TWOSIDED\n" i2 to:ss
    format "%*MATERIAL_FALLOFF In\n" i2 to:ss
    format "%*MATERIAL_XP_TYPE %\n" i2 (if mat.opacityType == 2 then "Additive" else if mat.opacityType == 1 then "Subtractive" else "Filter") to:ss
    local bms = PTASE_CollectBitmaps mat.diffuseMap #()
    for k = 1 to bms.count do
        PTASE_WriteMap ss i2 (if k == 1 then "*MAP_DIFFUSE" else "*MAP_SELFILLUM") bms[k] (if k == 1 then 1 else 5)
    if mat.opacityMap != undefined do
    (
        local ob = PTASE_CollectBitmaps mat.opacityMap #()
        if ob.count > 0 do PTASE_WriteMap ss i2 "*MAP_OPACITY" ob[1] 6
    )
    format "%}\n" ind to:ss
)

fn PTASE_WriteMaterial ss mat idx =
(
    local w = PTASE_Writer()
    if classof mat == MultiMaterial then
    (
        format "\t*MATERIAL % {\n" idx to:ss
        format "\t\t*MATERIAL_NAME %\n\t\t*MATERIAL_CLASS \"Multi/Sub-Object\"\n" (w.q mat.name) to:ss
        format "\t\t*MATERIAL_AMBIENT 0.5880\t0.5880\t0.5880\n\t\t*MATERIAL_DIFFUSE 0.5880\t0.5880\t0.5880\n" to:ss
        format "\t\t*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000\n\t\t*MATERIAL_SHINE 0.1000\n\t\t*MATERIAL_SHINESTRENGTH 0.0000\n" to:ss
        format "\t\t*MATERIAL_TRANSPARENCY 0.0000\n\t\t*MATERIAL_WIRESIZE 1.0000\n" to:ss
        local n = mat.materialList.count
        format "\t\t*NUMSUBMTLS %\n" n to:ss
        for i = 1 to n do PTASE_WriteStd ss mat.materialList[i] "\t\t" "*SUBMATERIAL" (i - 1)
        format "\t}\n" to:ss
    )
    else PTASE_WriteStd ss mat "\t" "*MATERIAL" idx
)

fn PTASE_WriteMapBlock ss m ch ind =
(
    local w = PTASE_Writer()
    local nv = meshop.getNumMapVerts m ch
    local nf = getNumFaces m
    format "%*MESH_NUMTVERTEX %\n" ind nv to:ss
    if nv > 0 do
    (
        format "%*MESH_TVERTLIST {\n" ind to:ss
        for i = 1 to nv do format "%\t*MESH_TVERT %\t%\n" ind (i - 1) (w.p3 (meshop.getMapVert m ch i)) to:ss
        format "%}\n" ind to:ss
        format "%*MESH_NUMTVFACES %\n" ind nf to:ss
        format "%*MESH_TFACELIST {\n" ind to:ss
        for i = 1 to nf do
        (
            local f = meshop.getMapFace m ch i
            format "%\t*MESH_TFACE %\t%\t%\t%\n" ind (i - 1) ((f.x as integer) - 1) ((f.y as integer) - 1) ((f.z as integer) - 1) to:ss
        )
        format "%}\n" ind to:ss
    )
)

fn PTASE_WriteTM ss node ind =
(
    local w = PTASE_Writer()
    local tm = node.transform
    local i2 = ind + "\t"
    format "%*NODE_TM {\n" ind to:ss
    format "%*NODE_NAME %\n" i2 (w.q node.name) to:ss
    format "%*INHERIT_POS 0 0 0\n%*INHERIT_ROT 0 0 0\n%*INHERIT_SCL 0 0 0\n" i2 i2 i2 to:ss
    format "%*TM_ROW0 %\n%*TM_ROW1 %\n%*TM_ROW2 %\n%*TM_ROW3 %\n" i2 (w.p3 tm.row1) i2 (w.p3 tm.row2) i2 (w.p3 tm.row3) i2 (w.p3 tm.row4) to:ss
    format "%*TM_POS %\n" i2 (w.p3 tm.row4) to:ss
    local r = tm.rotationpart
    local aa = r as angleaxis
    format "%*TM_ROTAXIS %\n%*TM_ROTANGLE %\n" i2 (w.p3 aa.axis) i2 (w.fl (degToRad aa.angle)) to:ss
    format "%*TM_SCALE %\n" i2 (w.p3 tm.scalepart) to:ss
    format "%*TM_SCALEAXIS 0.0000\t0.0000\t0.0000\n%*TM_SCALEAXISANG 0.0000\n" i2 i2 to:ss
    format "%}\n" ind to:ss
)

-- ---------------------------------------------------------------- characters / monsters
-- What the game's own ASE -> SMD/SMB builder reads: meshes WITH a material become the model
-- (*PHYSIQUE gives each vertex its bone), meshes WITHOUT a material become the skeleton (.smb)
-- with their animation, helpers are ignored.  So bones are written as small material-less
-- meshes, skinned meshes in their rest pose with one bone per vertex (the game is rigid).

fn PTASE_SkinOf node = (local r = undefined; for m in node.modifiers where classof m == Skin do r = m; r)

fn PTASE_SkinBones node sk =
(
    max modify mode
    select node
    modPanel.setCurrentObject sk
    for i = 1 to skinOps.GetNumberBones sk collect getNodeByName (skinOps.GetBoneName sk i 1)
)

-- bone name per vertex (strongest weight), joined with "|" for the C# writer
fn PTASE_SkinPhysique node sk =
(
    max modify mode
    select node
    modPanel.setCurrentObject sk
    local names = #()
    local missing = 0
    for v = 1 to skinOps.GetNumberVertices sk do
    (
        local best = "", bw = 0.0
        for k = 1 to skinOps.GetVertexWeightCount sk v do
        (
            local wt = skinOps.GetVertexWeight sk v k
            if wt > bw do (bw = wt; best = skinOps.GetBoneName sk (skinOps.GetVertexWeightBoneID sk v k) 1)
        )
        if best == "" do missing += 1
        append names best
    )
    #(names, missing)
)

-- every bone of the skeletons used by the exported skinned meshes (and selected PT bones),
-- with their parents, parents first
fn PTASE_CollectBones nodes skinned =
(
    local bones = #()
    fn addUp b bones = (while b != undefined do (appendIfUnique bones b; b = b.parent))
    for g in skinned do for b in (PTASE_SkinBones g (PTASE_SkinOf g)) where b != undefined do addUp b bones
    for n in nodes where getUserProp n "pt_bind" != undefined do addUp n bones
    -- the rest of a PT skeleton (end bones nobody is skinned to)
    local rigs = #()
    for b in bones do (local r = getUserProp b "pt_rig"; if r != undefined and r != "" do appendIfUnique rigs (r as string))
    if rigs.count > 0 do
        for o in objects do
        (
            local r = getUserProp o "pt_rig"
            if r != undefined and (findItem rigs (r as string)) > 0 do addUp o bones
        )
    -- parents first
    local depth = for b in bones collect (local d = 0; local p = b.parent; while p != undefined do (d += 1; p = p.parent); d)
    local order = for i = 1 to bones.count collect i
    fn byDepth a b depth: = depth[a] - depth[b]
    qsort order byDepth depth:depth
    for i in order collect bones[i]
)

fn PTASE_RowsString tm =
(
    local s = ""
    for r in #(tm.row1, tm.row2, tm.row3, tm.row4) do s += (r.x as string) + " " + (r.y as string) + " " + (r.z as string) + " "
    s
)

-- bones + their animation.  anim: #auto (a model's own keys, i.e. monsters - not a shared player
-- class animation), #always, #never
fn PTASE_WriteBones ss bones anim:#auto =
(
    local rw = PTASE_Asm.CreateInstance "PTAse.RigWriter"
    local animated = 0
    for b in bones do
    (
        local rows = getUserProp b "pt_bind"
        if rows == undefined do rows = at time animationRange.start (PTASE_RowsString b.transform)
        local src = getUserProp b "pt_anim"
        local want = anim == #always or (anim == #auto and (src == undefined or (src as string) != "shared"))
        local times = #()
        if want do
        (
            local ctrls = #(b.position.controller, b.rotation.controller, b.scale.controller)
            for c in ctrls where c != undefined do
                try (for k in c.keys do appendIfUnique times k.time) catch ()
            if times.count == 0 and b.isAnimated do
                for f = animationRange.start.frame to animationRange.end.frame do append times (f as time)
            sort times
        )
        local withTrack = times.count > 0
        if withTrack do
        (
            local hasScale = false
            try (hasScale = (numKeys b.scale.controller) > 0) catch ()
            rw.BeginTrack hasScale
            for t in times do
            (
                local tm = at time t (if b.parent != undefined then b.transform * inverse b.parent.transform else b.transform)
                rw.Key (t as integer) tm.row1.x tm.row1.y tm.row1.z tm.row2.x tm.row2.y tm.row2.z \
                       tm.row3.x tm.row3.y tm.row3.z tm.row4.x tm.row4.y tm.row4.z
            )
            animated += 1
        )
        format "%" (rw.Bone b.name (if b.parent != undefined then b.parent.name else "") (rows as string) withTrack) to:ss
    )
    animated
)

fn PTASE_WriteGeom ss node matIndex exportedSet skinData:undefined =
(
    local w = PTASE_Writer()
    -- skinned meshes are written in their rest pose (Skin off), everything else as it is
    local sk = if skinData != undefined then PTASE_SkinOf node else undefined
    if sk != undefined do sk.enabled = false
    local m = snapshotAsMesh node        -- world-space vertices, all modifiers applied
    if sk != undefined do sk.enabled = true
    format "*GEOMOBJECT {\n" to:ss
    format "\t*NODE_NAME %\n" (w.q node.name) to:ss
    if skinData == undefined and node.parent != undefined and (findItem exportedSet node.parent) > 0 do
        format "\t*NODE_PARENT %\n" (w.q node.parent.name) to:ss
    PTASE_WriteTM ss node "\t"
    local nv = getNumVerts m, nf = getNumFaces m
    format "\t*MESH {\n\t\t*TIMEVALUE 0\n\t\t*MESH_NUMVERTEX %\n\t\t*MESH_NUMFACES %\n" nv nf to:ss
    format "\t\t*MESH_VERTEX_LIST {\n" to:ss
    for i = 1 to nv do format "\t\t\t*MESH_VERTEX %\t%\n" (i - 1) (w.p3 (getVert m i)) to:ss
    format "\t\t}\n\t\t*MESH_FACE_LIST {\n" to:ss
    for i = 1 to nf do
    (
        local f = getFace m i
        local sg = getFaceSmoothGroup m i
        local sgs = ""
        for b = 1 to 32 where (bit.get sg b) do sgs += (if sgs == "" then "" else ",") + (b as string)
        format "\t\t\t*MESH_FACE %:    A: % B: % C: % AB: % BC: % CA: %\t *MESH_SMOOTHING % \t*MESH_MTLID %\n" \
            (i - 1) ((f.x as integer) - 1) ((f.y as integer) - 1) ((f.z as integer) - 1) \
            (if getEdgeVis m i 1 then 1 else 0) (if getEdgeVis m i 2 then 1 else 0) (if getEdgeVis m i 3 then 1 else 0) \
            sgs ((getFaceMatID m i) - 1) to:ss
    )
    format "\t\t}\n" to:ss
    local nmaps = meshop.getNumMaps m
    -- extra channels first (legacy importers then still end with channel 1)
    for ch = 2 to nmaps - 1 where (meshop.getMapSupport m ch) do
    (
        format "\t\t*MESH_MAPPINGCHANNEL % {\n" ch to:ss
        PTASE_WriteMapBlock ss m ch "\t\t\t"
        format "\t\t}\n" to:ss
    )
    if meshop.getMapSupport m 1 then PTASE_WriteMapBlock ss m 1 "\t\t"
    else format "\t\t*MESH_NUMTVERTEX 0\n" to:ss
    if meshop.getMapSupport m 0 do
    (
        local nc = meshop.getNumMapVerts m 0
        format "\t\t*MESH_NUMCVERTEX %\n\t\t*MESH_CVERTLIST {\n" nc to:ss
        for i = 1 to nc do format "\t\t\t*MESH_VERTCOL %\t%\n" (i - 1) (w.p3 (meshop.getMapVert m 0 i)) to:ss
        format "\t\t}\n\t\t*MESH_NUMCVFACES %\n\t\t*MESH_CFACELIST {\n" nf to:ss
        for i = 1 to nf do
        (
            local f = meshop.getMapFace m 0 i
            format "\t\t\t*MESH_CFACE %\t%\t%\t%\n" (i - 1) ((f.x as integer) - 1) ((f.y as integer) - 1) ((f.z as integer) - 1) to:ss
        )
        format "\t\t}\n" to:ss
    )
    format "\t}\n\t*PROP_MOTIONBLUR 0\n\t*PROP_CASTSHADOW 1\n\t*PROP_RECVSHADOW 1\n" to:ss
    if matIndex >= 0 then format "\t*MATERIAL_REF %\n" matIndex to:ss
    else
    (
        local wc = (node.wirecolor as point3) / 255.0
        format "\t*WIREFRAME_COLOR %\n" (w.p3 wc) to:ss
    )
    if skinData != undefined do
    (
        local rw = PTASE_Asm.CreateInstance "PTAse.RigWriter"
        local joined = ""
        for i = 1 to skinData.count do joined += (if i > 1 then "|" else "") + skinData[i]
        format "%" (rw.Physique joined) to:ss
    )
    format "}\n" to:ss
    delete m
)

fn PTASE_WriteLight ss node =
(
    local w = PTASE_Writer()
    format "*LIGHTOBJECT {\n\t*NODE_NAME %\n\t*LIGHT_TYPE Omni\n" (w.q node.name) to:ss
    PTASE_WriteTM ss node "\t"
    format "\t*LIGHT_SHADOWS Off\n\t*LIGHT_USELIGHT 1\n\t*LIGHT_SPOTSHAPE Circle\n\t*LIGHT_USEGLOBAL 0\n\t*LIGHT_ABSMAPBIAS 0\n\t*LIGHT_OVERSHOOT 0\n" to:ss
    format "\t*LIGHT_SETTINGS {\n\t\t*TIMEVALUE 0\n" to:ss
    local c = color 255 255 255, mult = 1.0, att = 200.0
    try (c = node.rgb; mult = node.multiplier; att = node.farAttenEnd) catch ()
    format "\t\t*LIGHT_COLOR %\n\t\t*LIGHT_INTENS %\n\t\t*LIGHT_ASPECT -1.0000\n" (w.p3 ((c as point3) / 255.0)) (w.fl mult) to:ss
    format "\t\t*LIGHT_ATTNSTART 0.0000\n\t\t*LIGHT_ATTNEND %\n" (w.fl att) to:ss
    format "\t}\n}\n" to:ss
)

fn PTASE_Export path nodes:undefined copyTextures:true skeleton:true anim:#auto =
(
    PTASE_TexOutDir = if copyTextures then getFilenamePath path else undefined
    PTASE_TexCopied = Dictionary #string
    local t0 = timestamp()
    if nodes == undefined do nodes = if selection.count > 0 then (selection as array) else (objects as array)
    local geoms = for n in nodes where (superclassof n == GeometryClass and canConvertTo n TriMeshGeometry and not n.isHidden) collect n
    local lights = for n in nodes where (superclassof n == Light and classof n == Omnilight) collect n
    -- characters / monsters: skinned meshes and their skeletons (selecting a PT bone exports its skinned meshes too)
    local skinned = #(), bones = #()
    if skeleton and PTASE_Compile() do
    (
        local selRigs = #()
        for n in nodes do (local r = getUserProp n "pt_rig"; if r != undefined and r != "" do appendIfUnique selRigs (r as string))
        for o in objects where (PTASE_SkinOf o) != undefined and not o.isHidden do
        (
            local inSel = (findItem geoms o) > 0
            if not inSel and selRigs.count > 0 do
                for b in (PTASE_SkinBones o (PTASE_SkinOf o)) where b != undefined do
                    (local r = getUserProp b "pt_rig"; if r != undefined and (findItem selRigs (r as string)) > 0 do inSel = true)
            if inSel do (appendIfUnique skinned o; appendIfUnique geoms o)
        )
        bones = PTASE_CollectBones nodes skinned
        -- material-less PT bone meshes must not be written twice
        geoms = for g in geoms where (findItem bones g) == 0 collect g
    )
    local mats = #()
    for g in geoms where g.material != undefined do appendIfUnique mats g.material
    local ss = stringStream ""
    format "*3DSMAX_ASCIIEXPORT\t200\n*COMMENT \"AsciiExport Version  2.00 - PT ASE Exporter (3ds Max %)\"\n" ((maxVersion())[1] / 1000 + 1998) to:ss
    format "*SCENE {\n\t*SCENE_FILENAME \"%\"\n\t*SCENE_FIRSTFRAME %\n\t*SCENE_LASTFRAME %\n" maxFileName ((animationRange.start.frame) as integer) ((animationRange.end.frame) as integer) to:ss
    format "\t*SCENE_FRAMESPEED %\n\t*SCENE_TICKSPERFRAME %\n" frameRate ticksPerFrame to:ss
    format "\t*SCENE_BACKGROUND_STATIC 0.0000\t0.0000\t0.0000\n\t*SCENE_AMBIENT_STATIC 0.0000\t0.0000\t0.0000\n}\n" to:ss
    -- motion list (walk, attack ...) when the animation is written
    local ownAnim = false
    for b in bones do (local s = getUserProp b "pt_anim"; if s == undefined or (s as string) != "shared" do ownAnim = true)
    local motions = try (execute "PTASE_Motions") catch (#())
    if bones.count > 0 and motions != undefined and motions.count > 0 and (anim == #always or (anim == #auto and ownAnim)) do
    (
        format "*PT_ANIMATION {\n\t*PT_SKELETON \"%\"\n" (getFilenameFile path) to:ss
        for m in motions do format "\t*PT_MOTION \"%\"\t%\t%\t%\n" m[1] m[2] m[3] (if m[4] then 1 else 0) to:ss
        format "}\n" to:ss
    )
    format "*MATERIAL_LIST {\n\t*MATERIAL_COUNT %\n" mats.count to:ss
    for i = 1 to mats.count do PTASE_WriteMaterial ss mats[i] (i - 1)
    format "}\n" to:ss
    local unassigned = 0
    for g in geoms do
    (
        local sk = PTASE_SkinOf g
        local phys = undefined
        if (findItem skinned g) > 0 and sk != undefined do
        (
            local r = PTASE_SkinPhysique g sk
            phys = r[1]
            unassigned += r[2]
        )
        PTASE_WriteGeom ss g ((findItem mats g.material) - 1) (geoms + bones) skinData:phys
    )
    local animated = if bones.count > 0 then PTASE_WriteBones ss bones anim:anim else 0
    if bones.count > 0 do
        format "PT ASE export: % bones (% animated), % skinned meshes%\n" bones.count animated skinned.count \
            (if unassigned > 0 then (", " + unassigned as string + " vertices without a bone") else "")
    for l in lights do PTASE_WriteLight ss l
    local sw = dotNetObject "System.IO.StreamWriter" path false ((dotNetClass "System.Text.Encoding").GetEncoding 1252)
    sw.NewLine = "\r\n"
    sw.Write ((ss as string))
    sw.Close()
    format "PT ASE export: % objects, % materials, % textures copied -> % (% ms)\n" geoms.count mats.count \
        (if copyTextures then PTASE_TexCopied.count else 0) path (timestamp() - t0)
    PTASE_TexOutDir = undefined
    true
)
