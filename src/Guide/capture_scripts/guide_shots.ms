-- Guide screenshots in a real 3ds Max window (only Max's own windows are captured)
fileIn @"X:\Projects\PT-World-Map\tools\max\PT_ASE_Importer.ms"
global gLog, gShot, gGrab, gOrigStep, gMidDone = false
global OUTDIR = @"X:\Projects\PT-World-Map\work\guide\"
fn gLog s = (local f = openFile (OUTDIR + "max_shots.log") mode:"a"; format "%\n" s to:f; close f)

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
    else global gGrabType = res.CompiledAssembly.GetType "GuideGrab"
)
fn gShot hwnd name = (gLog (name + " " + ((dotNetClass gGrabType).Save hwnd (OUTDIR + name)) as string))

-- hook the progress callback once to grab the status-bar progress bar mid-import
gOrigStep = PTASE_Step
fn PTASE_Step frac =
(
    gOrigStep frac
    if not gMidDone and PTASE_ProgOn and PTASE_ProgLo + (PTASE_ProgHi - PTASE_ProgLo) * frac > 45 do
    (
        gMidDone = true
        windows.processPostedMessages()
        gShot (windows.getMAXHWND()) "max_2_progress.png"
    )
)

try
(
    resetMaxFile #noPrompt
    local mx = windows.getMAXHWND()
    windows.sendMessage mx 0x0112 0xF030 0          -- maximize
    viewport.setLayout #layout_4
    for i = 1 to 4 do (viewport.activeViewport = i; viewport.SetRenderLevel #smoothhighlights)
    viewport.activeViewport = 4
    -- 1: the dialog
    createDialog PTASE_Rollout
    local dh = for c in (windows.getChildrenHWND 0) where c[5] == "PT ASE Importer" collect c[1]
    if dh.count > 0 then gShot dh[1] "max_1_dialog.png" else gLog "dialog hwnd not found"
    -- 2 + 3: import through the dialog code path (closes dialog, progress bar, zoom)
    PTASE_Rollout.runMany #(@"X:\Projects\PT-World-Map\ase_out\Field\Ice\ice1.ase")
    completeRedraw()
    gShot mx "max_3_after_import.png"
    -- 4: scanline render of the active (perspective) view
    renderers.current = Default_Scanline_Renderer()
    render outputSize:[1600, 900] vfb:false outputfile:(OUTDIR + "max_4_render.png")
    gLog "done"
)
catch (gLog ("ERROR " + getCurrentException()))
quitMax #noPrompt
