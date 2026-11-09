/*
    PT ASE Importer for 3ds Max 2020+ (works in any Max with .NET 4)
    ---------------------------------------------------------------
    Imports 3ds Max ASCII Scene Export (.ase) files: smd2ase output from
    Priston Tale maps AND the original artist ASE files.

      * geometry with every UV channel (MESH_MAPPINGCHANNEL) + vertex colours
      * NODE_TM pivots and NODE_PARENT hierarchy
      * Multi/Sub materials: bitmap x lightmap layers x baked vertex lighting,
        opacity (TGA alpha / mask), two-sided, additive blending
      * PT collision walls go to a hidden, non-renderable layer
      * optional omni lights
    Export: PT_ASE_Exporter.ms (its own window): meshes, materials, bones, skin, animation and
    moving props, as the game's own builder reads them.

    Install : PT_RosettaStone.exe (3ds Max plug-in), or copy PT_ASE_Importer.ms, PT_ASE_Exporter.ms,
              PT_ASE_Reader.cs + PT_ASE_Skin.cs into <3ds Max>\scripts\startup\
    Use     : menu Priston Tale > Import... / Export... / Motions...  (also File > Import / Export,
              and the macros under Customize > Category "PT Tools")
    Script  : PTASE_ImportFiles #(@"C:\path\map.ase")   -- progress bar + zoom to result
              PTASE_ImportFile @"C:\path\map.ase"        -- one file, no zoom (for batch use)
*/

global PTASE_Dir = getFilenamePath (getSourceFileName())
global PTASE_Asm
global PTASE_Opts
global PTASE_ImportFile
global PTASE_Rollout
global PTASE_LastDir
-- forward declarations (MAXScript resolves names when a function is compiled)
global PTASE_Step, PTASE_ProgOn, PTASE_ProgLo, PTASE_ProgHi, PTASE_Cancelled, PTASE_ImportFiles, PTASE_Export

if PTASE_Opts == undefined do
    PTASE_Opts = #(
        #game,      -- 1 shading: #game (self-illuminated, exact in-game look) or #lit
        true,       -- 2 baked vertex lighting
        true,       -- 3 lightmaps / texture layers
        true,       -- 4 hide collision walls
        false,      -- 5 import lights
        1.0,        -- 6 scale
        "",         -- 7 extra texture search folder
        true,       -- 8 use Scanline-friendly Standard materials (always)
        true,       -- 9 characters / monsters: skeleton + skin
        #animated,  -- 10 characters: #animated or #tpose (bind pose, no animation)
        ""          -- 11 optional animation file (*_motions.ase) to animate with
    )
if PTASE_Opts.count < 9 do append PTASE_Opts true
if PTASE_Opts.count < 10 do append PTASE_Opts #animated
if PTASE_Opts.count < 11 do append PTASE_Opts ""
global PTASE_AnimMissing = #()   -- animation files that were looked for but not found
global PTASE_SkinSdk = undefined  -- PTAse.SkinSdk (PT_ASE_Skin.cs: reads Skin weights), or undefined

-- PT_ASE_Reader.cs, with PT_ASE_Skin.cs (reads Skin weights through the SDK for the exporter,
-- no Modify panel) when Autodesk.Max.dll can be referenced
fn PTASE_Compile =
(
    if PTASE_Asm != undefined do return true
    local src = PTASE_Dir + "PT_ASE_Reader.cs"
    if not doesFileExist src do
    (
        messageBox ("PT_ASE_Reader.cs not found next to the script:\n" + src) title:"PT ASE Importer"
        return false
    )
    fn compile files sdk =
    (
        local provider = dotNetObject "Microsoft.CSharp.CSharpCodeProvider"
        local params = dotNetObject "System.CodeDom.Compiler.CompilerParameters"
        params.ReferencedAssemblies.Add "System.dll"
        params.ReferencedAssemblies.Add "System.Core.dll"
        if sdk do params.ReferencedAssemblies.Add (pathConfig.appendPath (getDir #maxroot) "Autodesk.Max.dll")
        params.GenerateInMemory = true
        params.GenerateExecutable = false
        provider.CompileAssemblyFromFile params files
    )
    local skinSrc = PTASE_Dir + "PT_ASE_Skin.cs"
    local res = undefined
    if doesFileExist skinSrc and doesFileExist (pathConfig.appendPath (getDir #maxroot) "Autodesk.Max.dll") do
        try (res = compile #(src, skinSrc) true) catch (res = undefined)
    PTASE_SkinSdk = undefined
    if res != undefined and res.Errors.Count == 0 then
        PTASE_SkinSdk = res.CompiledAssembly.CreateInstance "PTAse.SkinSdk"
    else
        res = compile #(src) false
    if res.Errors.Count > 0 do
    (
        local msg = "PT_ASE_Reader.cs failed to compile:\n"
        for i = 0 to res.Errors.Count - 1 do msg += (res.Errors.Item[i].ToString()) + "\n"
        format "%\n" msg
        messageBox msg title:"PT ASE Importer"
        return false
    )
    PTASE_Asm = res.CompiledAssembly
    true
)

fn PTASE_SetChannel m ch tvs tfs =
(
    meshop.setMapSupport m ch true
    meshop.setNumMapVerts m ch tvs.count keep:false
    for i = 1 to tvs.count do meshop.setMapVert m ch i tvs[i]
    local n = amin tfs.count (getNumFaces m)
    for i = 1 to n do meshop.setMapFace m ch i tfs[i]
)

-- array literal -> MAXScript array, in chunks (execute overflows on huge literals)
fn PTASE_Exec sc lit =
(
    local n = sc.Split lit 10000
    if n == 1 then execute (sc.GetChunk 0)
    else
    (
        local out = #()
        for i = 0 to n - 1 do join out (execute (sc.GetChunk i))
        out
    )
)

fn PTASE_BuildGeom sc idx opts mats rootNode collLayer =
(
    local d = sc.GetObject idx
    local verts = PTASE_Exec sc d.Verts
    PTASE_Step 0.08
    local faces = PTASE_Exec sc d.Faces
    local mids = PTASE_Exec sc d.MatIds
    if verts.count == 0 or faces.count == 0 do return undefined
    PTASE_Step 0.2
    local m = mesh vertices:verts faces:faces materialIDs:mids
    m.name = d.Name
    PTASE_Step 0.3
    local sg = PTASE_Exec sc d.Smooth
    for i = 1 to sg.count do setFaceSmoothGroup m i sg[i]
    PTASE_Step 0.4

    local chans = execute (sc.ChannelList idx)
    local maxch = 1
    for c in chans do if c > maxch do maxch = c
    meshop.setNumMaps m (maxch + 1) keep:true
    for k = 1 to chans.count do
    (
        local c = chans[k]
        if c == 0 and not opts[2] do continue
        PTASE_SetChannel m c (PTASE_Exec sc (sc.ChanVerts idx (k - 1))) (PTASE_Exec sc (sc.ChanFaces idx (k - 1)))
        PTASE_Step (0.4 + 0.45 * k / chans.count)
    )
    update m
    m.transform = execute d.Transform

    local mref = d.MaterialRef
    if mref >= 0 do
    (
        local key = mref + 1
        if mats[key] == undefined do
            mats[key] = execute (sc.MaterialScript mref (if opts[1] == #game then 0 else 1) opts[2] opts[3] opts[7])
        m.material = mats[key]
    )
    PTASE_Step 1.0
    if d.AllCollision and opts[4] then
    (
        collLayer.addNode m
        m.renderable = false
    )
    m
)

fn PTASE_BuildLight sc idx =
(
    local d = sc.GetObject idx
    local l = omniLight name:d.Name rgb:(execute d.LightColor) multiplier:1.0
    l.useFarAtten = true
    l.farAttenStart = 0
    l.farAttenEnd = d.LightRange
    l.transform = execute d.Transform
    l
)

-- progress bar plumbing (Max status-bar progress with Cancel button)
global PTASE_ProgOn = false
global PTASE_ProgLo = 0.0
global PTASE_ProgHi = 100.0
global PTASE_Cancelled = false
fn PTASE_Step frac =
(
    if PTASE_ProgOn do
    (
        progressUpdate (PTASE_ProgLo + (PTASE_ProgHi - PTASE_ProgLo) * (amin 1.0 (amax 0.0 frac)))
        if getProgressCancel() do PTASE_Cancelled = true
    )
)

-- ---------------------------------------------------------------- characters / monsters
-- Bones become Point helpers in the bind pose, skinned meshes get a Skin modifier
-- (each vertex 100% on its one bone, like the game), and the bone animation is keyed
-- on linear controllers (the game interpolates linearly, 30 fps, 160 ticks a frame).
global PTASE_Motions = #()       -- #(#(name, start, end, loop), ...) of the last character
global PTASE_LastFrame = 100
global PTASE_MotionRollout

fn PTASE_BuildRig sc layer root rigName:"" =
(
    local rig = sc.Rig
    local bones = #()
    for i = 0 to rig.Count - 1 do
    (
        local b = Point name:(rig.BoneName i) size:(rig.BoneSize i) box:true cross:false axistripod:false \
                        centermarker:false wirecolor:(color 255 190 0)
        b.position.controller = Linear_Position()
        b.rotation.controller = Linear_Rotation()
        b.scale.controller = Linear_Scale()
        b.transform = execute (rig.BoneTm i)          -- world bind pose (set before parenting)
        -- for the exporter: the exact rest pose of the file, the rig it belongs to and where its keys came from
        setUserProp b "pt_bind" (rig.BoneRaw i)
        setUserProp b "pt_rig" rigName
        setUserProp b "pt_anim" rig.AnimSource
        layer.addNode b
        append bones b
    )
    for i = 0 to rig.Count - 1 do
    (
        local p = rig.BoneParent i
        if p >= 0 then bones[i + 1].parent = bones[p + 1]
        else if root != undefined do bones[i + 1].parent = root
    )
    bones
)

-- Skin modifiers for the skinned meshes #(#(mesh, object index) ...), each vertex 100% on its
-- bone.  skinOps needs the modifier current in the Modify panel, and every panel change costs
-- (half a second a mesh): all modifiers are added first (Create panel: instant), then each mesh
-- is visited once.
fn PTASE_SkinAll skinned sc bones =
(
    local todo = #()
    max create mode
    for s in skinned do
    (
        local phys = PTASE_Exec sc (sc.GetObject s[2]).Phys
        local used = #()
        for b in phys where b > 0 do appendIfUnique used b
        if used.count == 0 do continue
        sort used
        local sk = Skin()
        addModifier s[1] sk
        append todo #(s[1], sk, phys, used)
    )
    if todo.count == 0 do return 0
    max modify mode
    for e in todo do
    (
        local m = e[1], sk = e[2], phys = e[3], used = e[4]
        select m
        if modPanel.getCurrentObject() != sk do modPanel.setCurrentObject sk
        local slot = #()                              -- rig bone index -> skin bone index
        for k = 1 to used.count do
        (
            skinOps.addBone sk bones[used[k]] (if k == used.count then 1 else 0)
            slot[used[k]] = k
        )
        classOf m                                     -- evaluate so the skin knows its vertices
        for v = 1 to phys.count where phys[v] > 0 do skinOps.ReplaceVertexWeights sk v slot[phys[v]] 1.0
        -- vertices without a bone in the file (LavaGolem has one): Skin gives them envelope weights
        -- whatever is set, so the exporter is told to leave them out of *PHYSIQUE again
        local none = ""
        for v = 1 to phys.count where phys[v] == 0 do none += ((v - 1) as string) + " "
        if none != "" do setUserProp m "pt_unassigned" (phys.count as string + ":" + none)
    )
    todo.count
)

-- The game skins a vertex on its bone's bind pose as written, which can be scaled or skewed
-- (bones at 0.89 in many monsters, 8.8 fixed-point noise in all).  written:true puts every bone
-- there (parents first, so children are not dragged along) to bind the Skin; written:false puts
-- them back to the rigid rest pose the animation starts from.  Skin keeps the bind it was given,
-- so the deformation is exactly the game's and the mesh itself stays as written.
fn PTASE_BindPose sc bones written:true =
(
    local rig = sc.Rig
    local any = false
    for i = 0 to rig.Count - 1 while not any do any = (rig.BoneBindTm i) != ""
    if not any do return false
    for i in (execute (rig.ParentsFirst())) do
    (
        local s = if written then rig.BoneBindTm (i - 1) else ""
        bones[i].transform = execute (if s != "" then s else rig.BoneTm (i - 1))
    )
    true
)

-- linear keys: pos / scale #(#(frame, point3) ...), rot #(#(frame, matrix3) ...), with Auto Key
-- (MAXScript rotation key values are relative to the previous key).  Auto Key also keys frame 0
-- with the old value when the first key is elsewhere: that key is removed again (the game holds
-- the first key's value before it, and keys can start before frame 0 - salon's at frame -30).
fn PTASE_KeyNode sc node posLit rotLit sclLit =
(
    local pc = node.position.controller, rc = node.rotation.controller, scl = node.scale.controller
    local pos = PTASE_Exec sc posLit, rot = PTASE_Exec sc rotLit, sca = PTASE_Exec sc sclLit
    if pos.count > 0 do pc.value = pos[1][2]
    if rot.count > 0 do rc.value = rot[1][2] as quat
    if sca.count > 0 do scl.value = sca[1][2]
    fn dropFrame0 c keys =
    (
        if keys.count == 0 or (for k in keys where (k[1] as time) == 0f collect k).count > 0 do return ok
        local i = getKeyIndex c 0f
        if i > 0 do deleteKey c i
    )
    with animate on
    (
        for k in pos do at time k[1] pc.value = k[2]
        local prev = undefined
        for k in rot do
        (
            -- each key on the same side as the previous one: a linear rotation controller turns
            -- the way the quaternions say, the long way round when the signs flip
            local q = k[2] as quat
            if prev != undefined and (q.x * prev.x + q.y * prev.y + q.z * prev.z + q.w * prev.w) < 0 do
                q = quat -q.x -q.y -q.z -q.w
            at time k[1] rc.value = q
            prev = q
        )
        for k in sca do at time k[1] scl.value = k[2]
    )
    dropFrame0 pc pos
    dropFrame0 rc rot
    dropFrame0 scl sca
)

fn PTASE_Animate sc bones =
(
    local rig = sc.Rig
    local total = 0
    for i = 0 to rig.Count - 1 do total += rig.BoneKeyCount i
    if total == 0 do return 0
    frameRate = 30                                     -- the game: 30 frames a second, 160 ticks a frame
    local done = 0
    for i = 0 to rig.Count - 1 while not PTASE_Cancelled do
    (
        local n = rig.BoneKeyCount i
        if n == 0 or bones[i + 1] == undefined do continue        -- (animation only: a bone the scene lacks)
        PTASE_KeyNode sc bones[i + 1] (rig.PosKeys i) (rig.RotKeys i) (rig.ScaleKeys i)
        -- no scale keys: the game applies no scale, so a mirrored bind pose (omuD's Bip-13) does
        -- not mirror the animated bone
        if (rig.ScaleKeys i) == "#()" do bones[i + 1].scale.controller.value = [1, 1, 1]
        done += n
        PTASE_Step (done as float / total)
    )
    -- bones without keys: the game shows them at their stored local transform
    for i in (execute (rig.ParentsFirst())) do
    (
        local s = rig.BoneStatic (i - 1)
        local b = bones[i]
        if s != "" and b != undefined do at time 0 b.transform = (if b.parent != undefined then (execute s) * b.parent.transform else execute s)
    )
    total
)

-- map props with their own keys (windmills, doors): linear keys relative to the parent object
fn PTASE_AnimateProps sc items =
(
    if items.count == 0 do return 0
    frameRate = 30
    for e in items do
    (
        local n = e[1], d = sc.GetObject e[2]
        -- for the exporter: the pivot the keys turn about, exactly as written
        setUserProp n "pt_rest" d.RestRows
        n.position.controller = Linear_Position()
        n.rotation.controller = Linear_Rotation()
        n.scale.controller = Linear_Scale()
        PTASE_KeyNode sc n d.PosKeys d.RotKeys d.ScaleKeys
    )
    if sc.LastFrame > animationRange.end.frame do animationRange = interval 0 sc.LastFrame
    items.count
)

fn PTASE_SetMotions sc =
(
    local rig = sc.Rig
    PTASE_Motions = execute rig.Motions
    PTASE_LastFrame = amax 1 (if rig.LastFrame > 0 then rig.LastFrame else sc.LastFrame)
    frameRate = 30
    animationRange = interval 0 PTASE_LastFrame
    sliderTime = 0
    -- time-slider tags (Max 2020+: FrameTagManager)
    try (for m in PTASE_Motions do FrameTagManager.CreateNewTag m[1] (m[2] as time)) catch ()
)

rollout PTASE_MotionRollout "PT Motions" width:280
(
    label lbl "Click a motion to play only that range:" align:#left
    listbox lstM "" height:24
    button btnAll "Whole timeline" width:120 across:2
    button btnPlay "Play / Stop" width:120
    on PTASE_MotionRollout open do
        lstM.items = for m in PTASE_Motions collect (m[1] + "     " + m[2] as string + " - " + m[3] as string + (if m[4] then "  loop" else ""))
    on lstM selected i do
    (
        local m = PTASE_Motions[i]
        animationRange = interval m[2] (amax (m[2] + 1) m[3])
        sliderTime = m[2]
    )
    on btnAll pressed do (animationRange = interval 0 PTASE_LastFrame; sliderTime = 0)
    on btnPlay pressed do (if isAnimPlaying() then stopAnimation() else playAnimation immediateReturn:true)
)

-- "text {1} {2}" with the values filled in (the texts are translated as whole sentences by the
-- Rosetta Stone installer, which writes this script in the window's language)
fn PTASE_Fill s args =
(
    for i = 1 to args.count do s = substituteString s ("{" + i as string + "}") (args[i] as string)
    s
)

fn PTASE_ShowMotions =
(
    if PTASE_Motions.count == 0 do (messageBox "No motion list loaded.\nImport a character or monster .ase first." title:"PT Motions"; return ok)
    try (destroyDialog PTASE_MotionRollout) catch ()
    createDialog PTASE_MotionRollout
)

fn PTASE_ImportFile path opts:PTASE_Opts quiet:true =
(
    if not PTASE_Compile() do return #()
    local t0 = timestamp()
    local lo = PTASE_ProgLo, hi = PTASE_ProgHi
    PTASE_Step 0.02
    local sc = PTASE_Asm.CreateInstance "PTAse.Scene"
    sc.Animate = opts.count < 10 or opts[10] != #tpose
    sc.AnimationFile = if opts.count >= 11 then opts[11] else ""
    sc.LoadFile path
    local t1 = timestamp()
    PTASE_Step 0.15
    local base = getFilenameFile path
    local nodes = #()
    local byName = Dictionary #string
    local mats = #()
    mats[sc.MaterialCount + 1] = undefined
    local mainLayer = LayerManager.getLayerFromName base
    if mainLayer == undefined do mainLayer = LayerManager.newLayerFromName base
    local collLayer = LayerManager.getLayerFromName (base + "_collision")
    if collLayer == undefined do collLayer = LayerManager.newLayerFromName (base + "_collision")
    collLayer.ishidden = true
    collLayer.renderable = false

    -- A scaling helper at the world origin is only created when scale != 1
    -- (a helper far from the map would make Zoom Extents useless).
    local root = undefined
    if abs (opts[6] - 1.0) > 1e-6 do
    (
        root = dummy name:(base + "_root") boxsize:[100,100,100]
        mainLayer.addNode root
    )
    -- characters / monsters: skeleton first (skinning needs the bones in their bind pose)
    local doRig = sc.HasRig and (opts.count < 9 or opts[9])
    local rigBones = #()
    local skinned = #()
    local animatedProps = #()
    with redraw off
    (
        undo off
        (
            if doRig do
            (
                rigBones = PTASE_BuildRig sc mainLayer root rigName:base
                for b in rigBones do byName[b.name] = b
            )
            local geomEnd = if doRig then 0.6 else 1.0
            -- share the bar between objects by face count (one big terrain mesh dominates)
            local weights = for i = 0 to sc.ObjectCount - 1 collect (amax 1 (sc.GetObject i).NumFaces)
            local wsum = 0.0
            for w in weights do wsum += w
            local acc = 0.0
            for i = 0 to sc.ObjectCount - 1 while not PTASE_Cancelled do
            (
                local d = sc.GetObject i
                local n = undefined
                PTASE_ProgLo = lo + (hi - lo) * (0.15 + (geomEnd - 0.15) * acc / wsum)
                acc += weights[i + 1]
                PTASE_ProgHi = lo + (hi - lo) * (0.15 + (geomEnd - 0.15) * acc / wsum)
                if d.Kind == "geom" then
                (
                    n = PTASE_BuildGeom sc i opts mats root collLayer
                    if n != undefined and not (d.AllCollision and opts[4]) do mainLayer.addNode n
                )
                else if d.Kind == "light" and opts[5] do
                (
                    n = PTASE_BuildLight sc i
                    mainLayer.addNode n
                )
                if n != undefined do
                (
                    -- a skinned mesh follows its bones through the Skin modifier, never by parenting
                    local isSkin = doRig and d.Phys != ""
                    append nodes #(n, (if isSkin then "" else d.Parent))
                    if isSkin do append skinned #(n, i)
                    -- for the exporter: the parent the file gave it (often a bone)
                    if isSkin and d.Parent != "" do setUserProp n "pt_parent" d.Parent
                    if d.KeyCount > 0 and d.Kind == "geom" and not isSkin do append animatedProps #(n, i)
                    if d.PhysEmpty do setUserProp n "pt_physique" "empty"
                    byName[d.Name] = n
                )
            )
            for e in nodes do
            (
                local p = if e[2] != "" and hasDictValue byName e[2] then byName[e[2]] else root
                if p != undefined and p != e[1] do e[1].parent = p
            )
            if doRig and not PTASE_Cancelled do
            (
                PTASE_ProgLo = lo + (hi - lo) * geomEnd
                PTASE_ProgHi = lo + (hi - lo) * (geomEnd + 0.05)
                local bound = PTASE_BindPose sc rigBones written:true
                PTASE_SkinAll skinned sc rigBones
                if bound do PTASE_BindPose sc rigBones written:false
                PTASE_ProgLo = lo + (hi - lo) * (geomEnd + 0.05)
                PTASE_ProgHi = hi
                PTASE_Animate sc rigBones
                PTASE_SetMotions sc
                if sc.Rig.AnimMissing != "" do
                (
                    appendIfUnique PTASE_AnimMissing sc.Rig.AnimMissing
                    format "PT ASE: no animation for % - % not found next to it (imported in T-pose)\n" base sc.Rig.AnimMissing
                )
                for b in rigBones do append nodes #(b, "")
            )
            if not PTASE_Cancelled do PTASE_AnimateProps sc animatedProps
            if root != undefined do root.scale = [opts[6], opts[6], opts[6]]
        )
    )
    PTASE_ProgLo = lo
    PTASE_ProgHi = hi
    if sc.Missing != "" do format "PT ASE: textures not found for %:\n%" base sc.Missing
    format "PT ASE: % - % objects, parse % ms, build % ms\n" base nodes.count (t1 - t0) (timestamp() - t1)
    (for e in nodes collect e[1])
)

-- Import several files with a progress bar, then frame the result in every viewport.
-- PT maps sit far from the world origin, so without this nothing appears on screen.
fn PTASE_ImportFiles files opts:PTASE_Opts zoom:true =
(
    if files.count == 0 or not PTASE_Compile() do return #()
    local t = timestamp()
    local all = #()
    local done = 0
    PTASE_Cancelled = false
    PTASE_AnimMissing = #()
    PTASE_ProgOn = true
    try
    (
        for i = 1 to files.count while not PTASE_Cancelled do
        (
            local nm = getFilenameFile files[i]
            progressStart (if files.count == 1 then (PTASE_Fill "Importing {1}..." #(nm))
                           else (PTASE_Fill "Importing {1}  ({2} of {3})..." #(nm, i, files.count)))
            PTASE_ProgLo = 0.0
            PTASE_ProgHi = 100.0
            join all (PTASE_ImportFile files[i] opts:opts)
            progressEnd()
            done += 1
        )
    )
    catch
    (
        PTASE_ProgOn = false
        progressEnd()
        messageBox (PTASE_Fill "PT ASE import failed:\n{1}" #(getCurrentException())) title:"PT ASE Importer"
    )
    PTASE_ProgOn = false
    local vis = for n in all where isValidNode n and not n.isHidden and n.renderable collect n
    if zoom and vis.count > 0 do
    (
        local oldSel = selection as array
        select vis
        max zoomext sel all
        if oldSel.count > 0 then select oldSel else clearSelection()
    )
    completeRedraw()
    local secs = (timestamp() - t) / 1000.0
    local msg = (PTASE_Fill "PT ASE: imported {1} file(s), {2} objects in {3} s" #(done, vis.count, formattedPrint secs format:".1f")) + \
                (if PTASE_Cancelled then "  (cancelled)" else "")
    displayTempPrompt msg 6000
    format "%\n" msg
    if PTASE_AnimMissing.count > 0 and not (GetQuietMode()) do
    (
        local names = ""
        for n in PTASE_AnimMissing do names += "    " + n + "\n"
        messageBox (PTASE_Fill "No animation found, so the character was imported in T-pose.\n\nLooked for:\n{1}\nPut that file next to the .ase (convert any armour of the same class with PT_RosettaStone.exe into that folder), or pick it under 'Animation file'." #(names)) title:"PT ASE Importer"
    )
    all
)

fileIn (PTASE_Dir + "PT_ASE_Exporter.ms")

-- Export selection with the PT exporter (all UV channels, vertex colours, PT layers)
fn PTASE_ExportSelected path copyTextures:true skeleton:true anim:#auto = PTASE_Export path copyTextures:copyTextures skeleton:skeleton anim:anim

-- Alternative: Max's own ASCII exporter (asciiexp.dle).  It drops extra UV channels
-- in Max 2020, and its "selected only" mode skips children of unselected parents,
-- so ancestors are selected too.
fn PTASE_ExportSelectedStock path prompt:true =
(
    local cls = undefined
    for c in exporterPlugin.classes where (c as string) == "AsciiExp" do cls = c
    if cls == undefined do (messageBox "3ds Max ASCII exporter (asciiexp.dle) not found."; return false)
    local orig = selection as array
    local sel = for o in orig collect o
    for o in orig do (local p = o.parent; while p != undefined do (appendIfUnique sel p; p = p.parent))
    select sel
    local r = if prompt then exportFile path selectedOnly:true using:cls
              else exportFile path #noPrompt selectedOnly:true using:cls
    select orig
    r
)

fn PTASE_FindAse dir =
(
    local files = getFiles (pathConfig.appendPath dir "*.ase")
    for sub in getDirectories (pathConfig.appendPath dir "*") do join files (PTASE_FindAse sub)
    files
)

-- ------------------------------------------------------------------ game files (.smd / .smb)
-- PT_RosettaStone's installer writes PT_ASE_Config.ms next to these scripts with the path of its
-- converter (smd2ase.exe), so game files open directly: they are converted to .ase first, with
-- their textures decoded, into %TEMP%\PT_RosettaStone.
global PTASE_Converter
if doesFileExist (PTASE_Dir + "PT_ASE_Config.ms") do try (fileIn (PTASE_Dir + "PT_ASE_Config.ms")) catch ()

fn PTASE_ToAse path =
(
    local ext = toLower (getFilenameType path)
    if ext == ".ase" do return path
    if PTASE_Converter == undefined or not doesFileExist PTASE_Converter do
    (
        messageBox (PTASE_Fill "{1} is a game file. Convert it to .ase with PT_RosettaStone.exe first, or install the plug-in again from PT_RosettaStone.exe so that it can open game files itself." #(filenameFromPath path)) title:"PT ASE Importer"
        return undefined
    )
    local out = pathConfig.appendPath (getDir #temp) ("PT_RosettaStone\\" + getFilenameFile path)
    makeDir out all:true
    local code = 0
    hiddenDOSCommand ("\"\"" + PTASE_Converter + "\" \"" + path + "\" -o \"" + out + "\" --textures\"") exitCode:&code
    local want = toLower (getFilenameFile path) + ".ase"
    for f in (PTASE_FindAse out) where toLower (filenameFromPath f) == want do return f
    messageBox (PTASE_Fill "Could not convert {1}." #(filenameFromPath path)) title:"PT ASE Importer"
    undefined
)

-- ------------------------------------------------------------------ animation only
-- Puts the animation of a motion file (a class's m1.smb ... m8.smb, a monster's motion .ase) on
-- the character already in the scene: its bones are found by name, their old keys replaced.
fn PTASE_ApplyAnimation path =
(
    if not PTASE_Compile() do return 0
    local sc = PTASE_Asm.CreateInstance "PTAse.Scene"
    sc.Animate = true
    sc.LoadFile path
    local nm = filenameFromPath path
    if not sc.HasRig do (messageBox (PTASE_Fill "{1} has no bones or animation." #(nm)) title:"PT ASE Importer"; return 0)
    local rig = sc.Rig
    local bones = #()
    local found = 0
    for i = 0 to rig.Count - 1 do
    (
        local n = getNodeByName (rig.BoneName i) exact:true ignoreCase:true
        bones[i + 1] = n
        if n != undefined do found += 1
    )
    if found == 0 do
    (
        messageBox "None of the animation's bones is in the scene.\nImport the character first (Character / monster - T-pose, with bones), then its animation." title:"PT ASE Importer"
        return 0
    )
    with redraw off
    (
        undo "PT animation" on
        (
            for b in bones where b != undefined do
            (
                b.position.controller = Linear_Position()
                b.rotation.controller = Linear_Rotation()
                b.scale.controller = Linear_Scale()
                setUserProp b "pt_anim" nm
            )
            PTASE_Animate sc bones
            PTASE_SetMotions sc
        )
    )
    completeRedraw()
    local msg = PTASE_Fill "PT ASE: animation of {1} put on {2} of {3} bones" #(nm, found, rig.Count)
    displayTempPrompt msg 6000
    format "%\n" msg
    found
)

-- ------------------------------------------------------------------ the import window
-- One choice sets everything up; "Advanced options" (closed) holds the single settings.
global PTASE_Floater, PTASE_AdvRollout, PTASE_ExportRollout
global PTASE_Preset = if PTASE_Preset == undefined then 1 else PTASE_Preset
global PTASE_ExpOpts = if PTASE_ExpOpts == undefined then #(1, true, 1, true) else PTASE_ExpOpts   -- which, copy textures, animation, hidden

rollout PTASE_AdvRollout "Advanced options" width:320
(
    group "Shading"
    (
        radiobuttons rdoMode labels:#("Game look (self-illum)", "Lit (scene lights)") default:1
        checkbox chkVC "Baked vertex lighting (vertex colours)" checked:true
        checkbox chkLM "Lightmaps / extra texture layers" checked:true
    )
    group "Scene"
    (
        checkbox chkColl "Hide collision walls (own layer)" checked:true
        checkbox chkLights "Import lights" checked:false
        spinner spnScale "Scale " range:[0.0001, 1000, 1.0] type:#float scale:0.01
        edittext edtTex "Extra texture folder:" labelOnTop:true
        button btnTex "Browse..." width:80 align:#right
    )
    group "Characters / monsters"
    (
        checkbox chkRig "Skeleton + skin" checked:true
        radiobuttons rdoPose "Pose:" labels:#("Animated", "T-pose (bind pose)") default:1 align:#left
        edittext edtAnim "Animation file (optional, e.g. m8.ase):" labelOnTop:true
        button btnAnim "Browse..." width:80 align:#right
    )
    fn updatePose =
    (
        rdoPose.enabled = chkRig.checked
        local act = chkRig.checked and rdoPose.state == 1
        edtAnim.enabled = act
        btnAnim.enabled = act
    )
    fn opts =
    (
        #((if rdoMode.state == 1 then #game else #lit), chkVC.checked, chkLM.checked,
          chkColl.checked, chkLights.checked, spnScale.value, edtTex.text, true, chkRig.checked,
          (if rdoPose.state == 1 then #animated else #tpose), edtAnim.text)
    )
    fn show o =
    (
        rdoMode.state = if o[1] == #lit then 2 else 1
        chkVC.checked = o[2]; chkLM.checked = o[3]; chkColl.checked = o[4]; chkLights.checked = o[5]
        spnScale.value = o[6]; edtTex.text = o[7]; chkRig.checked = o[9]
        rdoPose.state = if o[10] == #tpose then 2 else 1; edtAnim.text = o[11]; updatePose()
    )
    on chkRig changed s do updatePose()
    on rdoPose changed s do updatePose()
    on btnTex pressed do (local d = getSavePath caption:"Texture folder"; if d != undefined do edtTex.text = d)
    on btnAnim pressed do
    (
        local f = getOpenFileName caption:"Animation file (converted .ase, or the game's .smb)" types:"Priston Tale (*.ase;*.smb)|*.ase;*.smb|All files (*.*)|*.*"
        if f != undefined do edtAnim.text = f
    )
    on PTASE_AdvRollout open do show PTASE_Opts
)

rollout PTASE_Rollout "Priston Tale - Import" width:320
(
    label lblWhat "What are you importing?" align:#left
    radiobuttons rdoWhat labels:#("Map - as seen in the game", "Map - for editing and exporting", "Character / monster - animated", "Character / monster - T-pose, with bones", "Character / monster - mesh only, no bones", "Animation only - onto the character in the scene") columns:1 align:#left default:1
    label lblHint "" align:#left width:296 height:42
    button btnFiles "Import file(s)..." width:296 height:30
    button btnFolder "Import a whole folder..." width:296
    label lblFiles "Opens .ase files, and game files (.smd, .smb) directly." align:#left

    local hints = #("The map with its textures and baked lighting, as the game shows it. Collision walls are hidden.",
                    "Everything you need to change the map and export it again: collision walls visible on their own layer, lights included.",
                    "Skeleton, skin and animation (a monster's own; armour uses its class file, e.g. m1.smb, found next to it).",
                    "Skeleton and skin in the bind pose, without animation - the pose to edit the model in.",
                    "Just the mesh, without a skeleton (weapons and items have none anyway).",
                    "Replaces the animation of the character in the scene with this file's (a class file m1.smb ... m8.smb, or a monster's).")

    -- the settings each choice stands for (#(shading, vertex light, layers, hide collision, lights, rig, pose))
    fn presetOpts i =
    (
        local o = deepCopy PTASE_Opts
        case i of
        (
            1: (o[1] = #game; o[2] = true; o[3] = true; o[4] = true; o[5] = false; o[9] = true; o[10] = #animated)
            2: (o[1] = #game; o[2] = true; o[3] = true; o[4] = false; o[5] = true; o[9] = true; o[10] = #animated)
            3: (o[9] = true; o[10] = #animated)
            4: (o[9] = true; o[10] = #tpose)
            5: (o[9] = false)
        )
        o
    )
    fn choose i =
    (
        PTASE_Preset = i
        lblHint.text = hints[i]
        btnFolder.enabled = i != 6
        -- the choice's settings; the Advanced panel shows them once it is open (it opens after this
        -- panel, and its controls cannot be set before)
        if i != 6 do
        (
            PTASE_Opts = presetOpts i
            try (PTASE_AdvRollout.show PTASE_Opts) catch ()     -- (also while the panel is rolled up)
        )
    )
    on rdoWhat changed i do choose i
    on PTASE_Rollout open do (rdoWhat.state = PTASE_Preset; choose PTASE_Preset)

    -- Close the window, then import with a progress bar and zoom to the result.
    fn runMany files =
    (
        if files.count == 0 do (messageBox "No .ase files found." title:"PT ASE Importer"; return ok)
        if files.count > 10 and not (queryBox (PTASE_Fill "{1} .ase files will be imported.\nThis may take a while (about 2-4 seconds per map).\n\nContinue?" #(files.count)) title:"PT ASE Importer") do return ok
        try (PTASE_Opts = PTASE_AdvRollout.opts()) catch ()
        local preset = rdoWhat.state
        try (closeRolloutFloater PTASE_Floater) catch ()
        local ase = for f in files collect PTASE_ToAse f
        ase = for f in ase where f != undefined collect f
        if ase.count == 0 do return ok
        if preset == 6 then (for f in ase do PTASE_ApplyAnimation f; PTASE_ShowMotions())
        else
        (
            PTASE_ImportFiles ase opts:PTASE_Opts
            if PTASE_Motions.count > 0 and ase.count == 1 do PTASE_ShowMotions()
        )
    )
    on btnFiles pressed do
    (
        local dlg = dotNetObject "System.Windows.Forms.OpenFileDialog"
        dlg.Filter = "Priston Tale (*.ase;*.smd;*.smb)|*.ase;*.smd;*.smb|All files (*.*)|*.*"
        dlg.Multiselect = rdoWhat.state != 6
        dlg.Title = "Import ASE"
        if PTASE_LastDir != undefined and doesFileExist PTASE_LastDir do dlg.InitialDirectory = PTASE_LastDir
        if (dlg.ShowDialog()).ToString() == "OK" do
        (
            local files = dlg.FileNames as array
            PTASE_LastDir = getFilenamePath files[1]
            runMany files
        )
    )
    on btnFolder pressed do
    (
        local d = getSavePath caption:"Folder with .ase files (searched recursively)" \
                              initialDir:(if PTASE_LastDir != undefined then PTASE_LastDir else "")
        if d != undefined do
        (
            PTASE_LastDir = d
            runMany (PTASE_FindAse d)
        )
    )
)

fn PTASE_OpenImport =
(
    try (closeRolloutFloater PTASE_Floater) catch ()
    PTASE_Floater = newRolloutFloater "Priston Tale - Import" 340 600
    addRollout PTASE_Rollout PTASE_Floater
    addRollout PTASE_AdvRollout PTASE_Floater rolledUp:true
)

-- ------------------------------------------------------------------ the export window
rollout PTASE_ExportRollout "Priston Tale - Export" width:320
(
    radiobuttons rdoWhich "Export:" labels:#("Selected objects", "Everything in the scene") columns:1 align:#left
    checkbox chkHidden "Include hidden objects (a map's collision walls)" checked:true
    checkbox chkCopyTex "Copy textures next to the exported .ase" checked:true
    dropdownlist ddAnim "Characters: export animation" items:#("Auto (monsters yes, player armour no)", "Always", "Never") width:296
    button btnExport "Export ASE..." width:296 height:30
    label lblNext "Then drop the .ase on ENCODE in PT_RosettaStone.exe: it builds the game's .smd (and .smb)." align:#left width:296 height:30

    on PTASE_ExportRollout open do
    (
        local o = PTASE_ExpOpts
        rdoWhich.state = o[1]; chkCopyTex.checked = o[2]; ddAnim.selection = o[3]; chkHidden.checked = o[4]
    )
    on btnExport pressed do
    (
        local nodes = if rdoWhich.state == 1 then (selection as array) else (objects as array)
        if nodes.count == 0 do (messageBox "Nothing selected: select the objects to export, or choose 'Everything in the scene'." title:"PT ASE Export"; return ok)
        local f = getSaveFileName caption:"Export ASE" types:"ASCII Scene Export (*.ase)|*.ase"
        if f == undefined do return ok
        PTASE_ExpOpts = #(rdoWhich.state, chkCopyTex.checked, ddAnim.selection, chkHidden.checked)
        try (destroyDialog PTASE_ExportRollout) catch ()
        PTASE_Export f nodes:nodes copyTextures:PTASE_ExpOpts[2] anim:(#(#auto, #always, #never))[PTASE_ExpOpts[3]] includeHidden:PTASE_ExpOpts[4]
        displayTempPrompt (PTASE_Fill "PT ASE: exported to {1}" #(f)) 6000
    )
)

fn PTASE_OpenExport =
(
    try (destroyDialog PTASE_ExportRollout) catch ()
    createDialog PTASE_ExportRollout
)

macroScript PTASE_Import category:"PT Tools" buttonText:"PT ASE Import" tooltip:"Priston Tale ASE importer"
(
    PTASE_OpenImport()
)

macroScript PTASE_ExportMacro category:"PT Tools" buttonText:"PT ASE Export" tooltip:"Priston Tale ASE exporter"
(
    PTASE_OpenExport()
)

macroScript PTASE_Motions category:"PT Tools" buttonText:"PT Motions" tooltip:"Priston Tale motion list (walk, attack ...)"
(
    PTASE_ShowMotions()
)

-- ------------------------------------------------------------------ menus
-- A "Priston Tale" menu in the main menu bar, and the importer / exporter under File > Import and
-- File > Export (3ds Max 2020-2024 menus; newer versions keep the macros under PT Tools).
fn PTASE_AddItem menu macro title =
(
    for i = 1 to menu.numItems() do if (menu.getItem i).getTitle() == title do return false
    local it = menuMan.createActionItem macro "PT Tools"
    it.setTitle title
    it.setUseCustomTitle true
    menu.addItem it -1
    true
)

fn PTASE_InstallMenus =
(
    try
    (
        local main = menuMan.getMainMenuBar()
        local pt = menuMan.findMenu "Priston Tale"
        if pt == undefined do
        (
            pt = menuMan.createMenu "Priston Tale"
            local sub = menuMan.createSubMenuItem "Priston Tale" pt
            main.addItem sub (main.numItems() + 1)
        )
        PTASE_AddItem pt "PTASE_Import" "Import..."
        PTASE_AddItem pt "PTASE_ExportMacro" "Export..."
        PTASE_AddItem pt "PTASE_Motions" "Motions..."
        -- File > Import / File > Export
        local file = menuMan.findMenu "&File"
        if file != undefined do
            for i = 1 to file.numItems() do
            (
                local it = file.getItem i
                local sm = it.getSubMenu()
                if sm == undefined do continue
                local t = it.getTitle()
                if matchPattern t pattern:"*Import*" do PTASE_AddItem sm "PTASE_Import" "Priston Tale (.ase, .smd, .smb)..."
                if matchPattern t pattern:"*Export*" do PTASE_AddItem sm "PTASE_ExportMacro" "Priston Tale (.ase)..."
            )
        menuMan.updateMenuBar()
    )
    catch (format "PT ASE: menus not added (%)\n" (getCurrentException()))
)

if not (GetQuietMode()) do PTASE_InstallMenus()

-- Show the import window when the script is run directly (not from startup / batch)
if not (matchPattern PTASE_Dir pattern:"*startup*") and not (GetQuietMode()) do
    try (PTASE_OpenImport()) catch ()
