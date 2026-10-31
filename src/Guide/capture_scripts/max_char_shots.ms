-- Guide screenshots in a real 3ds Max window: importer dialog, character import, motion list.
--   3dsmax.exe -U MAXScript max_char_shots.ms -silent
fileIn @"X:\Projects\SMD-ANIM\tools\max\PT_ASE_Importer.ms"
global gLog, gShot, gGrabType
global OUTDIR = @"X:\Projects\SMD-ANIM\work\shots\"
fn gLog s = (local f = openFile (OUTDIR + "max_shots.log") mode:"a"; if f == undefined do f = createFile (OUTDIR + "max_shots.log"); format "%\n" s to:f; close f)

-- tiny C# helper: PrintWindow(hwnd, PW_RENDERFULLCONTENT) -> png
(
    local src = "using System; using System.Drawing; using System.Drawing.Imaging; using System.Runtime.InteropServices;
public static class GuideGrab {
  [DllImport(\"user32.dll\")] static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport(\"user32.dll\")] static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public static string Save(long hwnd, string path) {
    IntPtr h = new IntPtr(hwnd); RECT r; GetWindowRect(h, out r);
    int w = r.R - r.L, ht = r.B - r.T; if (w <= 0 || ht <= 0) return \"empty\";
    using (var bmp = new Bitmap(w, ht)) { using (var g = Graphics.FromImage(bmp)) { IntPtr dc = g.GetHdc(); PrintWindow(h, dc, 2); g.ReleaseHdc(dc); }
      bmp.Save(path, ImageFormat.Png); }
    return w + \"x\" + ht; } }"
    local prov = dotNetObject "Microsoft.CSharp.CSharpCodeProvider"
    local par = dotNetObject "System.CodeDom.Compiler.CompilerParameters"
    par.ReferencedAssemblies.Add "System.dll"; par.ReferencedAssemblies.Add "System.Drawing.dll"
    par.GenerateInMemory = true
    local res = prov.CompileAssemblyFromSource par #(src)
    if res.Errors.Count > 0 then gLog ("grab compile error " + res.Errors.Item[0].ToString())
    else gGrabType = res.CompiledAssembly.GetType "GuideGrab"
)
fn gShot hwnd name = (gLog (name + " " + ((dotNetClass gGrabType).Save hwnd (OUTDIR + name)) as string))
fn gDialog title = (local h = for c in (windows.getChildrenHWND 0) where c[5] == title collect c[1]; if h.count > 0 then h[1] else undefined)

try
(
    resetMaxFile #noPrompt
    local mx = windows.getMAXHWND()
    windows.sendMessage mx 0x0112 0xF030 0          -- maximize
    viewport.setLayout #layout_1
    viewport.setType #view_persp_user
    viewport.SetRenderLevel #smoothhighlights
    -- 1: the importer dialog
    createDialog PTASE_Rollout
    windows.processPostedMessages()
    local dh = gDialog "PT ASE Importer"
    if dh != undefined then gShot dh "max_1_dialog.png" else gLog "dialog hwnd not found"
    -- 2: import a character through the dialog code path (closes dialog, progress bar,
    --    zoom, then opens the PT Motions list)
    PTASE_Rollout.runMany #(@"X:\Projects\SMD-ANIM\work\PT_ASE_Output\MmbA34.ase")
    -- pick the first walk the way a click in the list does
    local wi = 1
    for i = 1 to PTASE_Motions.count where matchPattern PTASE_Motions[i][1] pattern:"walk_01" do wi = i
    local m = PTASE_Motions[wi]
    PTASE_MotionRollout.lstM.selection = wi
    animationRange = interval m[2] m[3]
    sliderTime = m[2] + 10
    -- a 3/4 front view of the character
    local body = for o in geometry where o.modifiers.count > 0 collect o
    clearSelection()
    viewport.setTM (matrix3 [0.8,-0.25,0.55] [0.6,0.35,-0.72] [-0.0,0.9,0.43] [0,0,0])
    select body
    max zoomext sel
    viewport.zoom 1.6
    clearSelection()
    completeRedraw()
    windows.processPostedMessages()
    gShot mx "max_2_character.png"
    local mh = gDialog "PT Motions"
    if mh != undefined then gShot mh "max_3_motions.png" else gLog "motions hwnd not found"
    gLog "done"
)
catch (gLog ("ERROR " + getCurrentException()))
quitMax #noPrompt
