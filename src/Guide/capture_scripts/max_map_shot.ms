-- Guide screenshot in a real 3ds Max window: a split map with one of its objects selected (Move tool on its own pivot).
--   3dsmax.exe -U MAXScript max_map_shot.ms -silent
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

try
(
    resetMaxFile #noPrompt
    local mx = windows.getMAXHWND()
    windows.sendMessage mx 0x0112 0xF030 0          -- maximize
    viewport.setLayout #layout_1
    viewport.setType #view_persp_user
    viewport.SetRenderLevel #smoothhighlights
    PTASE_ImportFiles #(@"X:\Projects\SMD-ANIM\work\PT_ASE_Output3\Field\forest\village-1.ase")
    viewport.setTM (matrix3 [0.8,-0.25,0.55] [0.6,0.35,-0.72] [-0.0,0.9,0.43] [0,0,0])
    local pick = getNodeByName "village-1_017_sod_roof"
    select (for o in geometry where not o.isHidden collect o)
    max zoomext sel
    viewport.zoom 0.9
    if pick != undefined then select pick else gLog "object not found"
    max modify mode
    max move
    completeRedraw()
    windows.processPostedMessages()
    gShot mx "max_map.png"
    gLog "done"
)
catch (gLog ("ERROR " + getCurrentException()))
quitMax #noPrompt
