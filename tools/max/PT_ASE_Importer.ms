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
    Export: 3ds Max 2020 ships the ASCII exporter (asciiexp.dle) - the
    "Export selected" button uses it.

    Install : copy PT_ASE_Importer.ms, PT_ASE_Exporter.ms + PT_ASE_Reader.cs into
              <3ds Max>\scripts\startup\   (or run via Scripting > Run Script)
              then Customize > Toolbars/Menus > Category "PT Tools" > "PT ASE Import"
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

fn PTASE_Compile =
(
    if PTASE_Asm != undefined do return true
    local src = PTASE_Dir + "PT_ASE_Reader.cs"
    if not doesFileExist src do
    (
        messageBox ("PT_ASE_Reader.cs not found next to the script:\n" + src) title:"PT ASE Importer"
        return false
    )
    local provider = dotNetObject "Microsoft.CSharp.CSharpCodeProvider"
    local params = dotNetObject "System.CodeDom.Compiler.CompilerParameters"
    params.ReferencedAssemblies.Add "System.dll"
    params.ReferencedAssemblies.Add "System.Core.dll"
    params.GenerateInMemory = true
    params.GenerateExecutable = false
    local res = provider.CompileAssemblyFromFile params #(src)
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

fn PTASE_Skin m sc idx bones =
(
    local phys = PTASE_Exec sc (sc.GetObject idx).Phys
    local used = #()
    for b in phys where b > 0 do appendIfUnique used b
    if used.count == 0 do return false
    sort used
    max modify mode
    select m
    local sk = Skin()
    addModifier m sk
    modPanel.setCurrentObject sk
    local slot = #()                                  -- rig bone index -> skin bone index
    for k = 1 to used.count do
    (
        skinOps.addBone sk bones[used[k]] (if k == used.count then 1 else 0)
        slot[used[k]] = k
    )
    classOf m                                         -- evaluate so the skin knows its vertices
    for v = 1 to phys.count where phys[v] > 0 do skinOps.ReplaceVertexWeights sk v slot[phys[v]] 1.0
    true
)

fn PTASE_Animate sc bones =
(
    local rig = sc.Rig
    local total = 0
    for i = 0 to rig.Count - 1 do total += rig.BoneKeyCount i
    if total == 0 do return 0
    local done = 0
    with animate on
    (
        for i = 0 to rig.Count - 1 while not PTASE_Cancelled do
        (
            local n = rig.BoneKeyCount i
            if n == 0 do continue
            local b = bones[i + 1]
            local pc = b.position.controller, rc = b.rotation.controller, scl = b.scale.controller
            for k in (PTASE_Exec sc (rig.PosKeys i)) do at time k[1] pc.value = k[2]
            for k in (PTASE_Exec sc (rig.RotKeys i)) do at time k[1] rc.value = (k[2] as quat)
            for k in (PTASE_Exec sc (rig.ScaleKeys i)) do at time k[1] scl.value = k[2]
            done += n
            PTASE_Step (done as float / total)
        )
    )
    total
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
                for s in skinned do PTASE_Skin s[1] sc s[2] rigBones
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
            progressStart (if files.count == 1 then ("Importing " + nm + "...")
                           else ("Importing " + nm + "  (" + i as string + " of " + files.count as string + ")..."))
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
        messageBox ("PT ASE import failed:\n" + getCurrentException()) title:"PT ASE Importer"
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
    local msg = "PT ASE: imported " + done as string + " file(s), " + vis.count as string + " objects in " + \
                (formattedPrint secs format:".1f") + " s" + (if PTASE_Cancelled then "  (cancelled)" else "")
    displayTempPrompt msg 6000
    format "%\n" msg
    if PTASE_AnimMissing.count > 0 and not (GetQuietMode()) do
    (
        local names = ""
        for n in PTASE_AnimMissing do names += "    " + n + "\n"
        messageBox ("No animation found, so the character was imported in T-pose.\n\nLooked for:\n" + names + \
                    "\nPut that file next to the .ase (convert any armour of the same class with " + \
                    "PT_SMD2ASE.exe into that folder), or pick it under 'Animation file'.") title:"PT ASE Importer"
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

rollout PTASE_Rollout "PT ASE Importer" width:300
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
        edittext edtAnim "Animation file (optional, e.g. m8_motions.ase):" labelOnTop:true
        button btnAnim "Browse..." width:80 align:#right
    )
    button btnFiles "Import ASE file(s)..." width:260 height:28
    button btnFolder "Import all ASE in a folder..." width:260
    button btnExport "Export selected as ASE..." width:260
    checkbox chkCopyTex "Copy textures next to the exported .ase" checked:true
    dropdownlist ddAnim "Characters: export animation" items:#("Auto (monsters yes, player armour no)", "Always", "Never") width:260
    label lblStatus "Tip: the window closes and Max zooms to the map" align:#left

    fn opts =
    (
        #((if rdoMode.state == 1 then #game else #lit), chkVC.checked, chkLM.checked,
          chkColl.checked, chkLights.checked, spnScale.value, edtTex.text, true, chkRig.checked,
          (if rdoPose.state == 1 then #animated else #tpose), edtAnim.text)
    )
    fn updatePose =
    (
        rdoPose.enabled = chkRig.checked
        local act = chkRig.checked and rdoPose.state == 1
        edtAnim.enabled = act
        btnAnim.enabled = act
    )
    on chkRig changed s do updatePose()
    on rdoPose changed s do updatePose()
    on btnAnim pressed do
    (
        local f = getOpenFileName caption:"Animation file (converted *_motions.ase)" types:"ASCII Scene Export (*.ase)|*.ase|All files (*.*)|*.*"
        if f != undefined do edtAnim.text = f
    )
    -- Close the dialog, then import with a progress bar and zoom to the result.
    fn runMany files =
    (
        if files.count == 0 do (messageBox "No .ase files found." title:"PT ASE Importer"; return ok)
        if files.count > 10 and not (queryBox (files.count as string + " .ase files will be imported.\n" + \
                "This may take a while (about 2-4 seconds per map).\n\nContinue?") title:"PT ASE Importer") do return ok
        PTASE_Opts = opts()
        destroyDialog PTASE_Rollout
        PTASE_ImportFiles files opts:PTASE_Opts
        if PTASE_Motions.count > 0 and files.count == 1 do PTASE_ShowMotions()
    )
    on PTASE_Rollout open do
    (
        -- restore the options used last time
        local o = PTASE_Opts
        rdoMode.state = if o[1] == #lit then 2 else 1
        chkVC.checked = o[2]; chkLM.checked = o[3]; chkColl.checked = o[4]; chkLights.checked = o[5]
        spnScale.value = o[6]; edtTex.text = o[7]; chkRig.checked = o[9]
        rdoPose.state = if o[10] == #tpose then 2 else 1; edtAnim.text = o[11]; updatePose()
    )
    on btnTex pressed do (local d = getSavePath caption:"Texture folder"; if d != undefined do edtTex.text = d)
    on btnFiles pressed do
    (
        local dlg = dotNetObject "System.Windows.Forms.OpenFileDialog"
        dlg.Filter = "ASCII Scene Export (*.ase)|*.ase|All files (*.*)|*.*"
        dlg.Multiselect = true
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
    on btnExport pressed do
    (
        local f = getSaveFileName caption:"Export ASE" types:"ASCII Scene Export (*.ase)|*.ase"
        if f != undefined do
        (
            PTASE_ExportSelected f copyTextures:chkCopyTex.checked anim:(#(#auto, #always, #never))[ddAnim.selection]
            displayTempPrompt ("PT ASE: exported to " + f) 6000
        )
    )
)

macroScript PTASE_Import category:"PT Tools" buttonText:"PT ASE Import" tooltip:"Priston Tale ASE importer"
(
    try (destroyDialog PTASE_Rollout) catch ()
    createDialog PTASE_Rollout
)

macroScript PTASE_Motions category:"PT Tools" buttonText:"PT Motions" tooltip:"Priston Tale motion list (walk, attack ...)"
(
    PTASE_ShowMotions()
)

-- Show the dialog when the script is run directly (not from startup / batch)
if not (matchPattern PTASE_Dir pattern:"*startup*") and not (GetQuietMode()) do
(
    try (destroyDialog PTASE_Rollout) catch ()
    try (createDialog PTASE_Rollout) catch ()
)
