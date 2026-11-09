using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

namespace PTSmd
{
    public class BatchSettings
    {
        public string OutDir = "ase_out";
        public string GameRoot;                   // null = detect per file (folder above 'Field')
        public bool Textures = true;
        public bool StagesOnly, ModelsOnly;
        public ConvertOptions Template = new ConvertOptions();
    }

    public class BatchResult
    {
        public int Ok, Failed, Skipped;
        public TimeSpan Elapsed;
        public List<string> Outputs = new List<string>();
        public Dictionary<string, SortedSet<string>> Missing = new Dictionary<string, SortedSet<string>>();
        public string MissingReport;
        public bool Cancelled;
    }

    /// <summary>Converts many .smd files; reports progress through callbacks.</summary>
    public static class Batch
    {
        public static List<string> Collect(IEnumerable<string> inputs)
        {
            var files = new List<string>();
            foreach (string p in inputs)
            {
                if (Directory.Exists(p))
                {
                    var found = new List<string>();
                    Walk(p, found);
                    files.AddRange(found);
                }
                else if (File.Exists(p) && (p.EndsWith(".smd", StringComparison.OrdinalIgnoreCase) ||
                                            p.EndsWith(".smb", StringComparison.OrdinalIgnoreCase)))
                    files.Add(Path.GetFullPath(p));
            }
            return files;
        }

        static void Walk(string dir, List<string> outl)
        {
            string[] fs, ds;
            try
            {
                fs = Directory.GetFiles(dir);
                ds = Directory.GetDirectories(dir);
            }
            catch (Exception) { return; }
            Array.Sort(fs, StringComparer.Ordinal);
            Array.Sort(ds, StringComparer.Ordinal);
            foreach (var f in fs) if (f.EndsWith(".smd", StringComparison.OrdinalIgnoreCase)) outl.Add(f);
            foreach (var d in ds) Walk(d, outl);
        }

        public static long TotalBytes(IEnumerable<string> files)
        {
            long t = 0;
            foreach (var f in files) try { t += new FileInfo(f).Length; } catch (Exception) { }
            return t;
        }

        /// <summary>Output .ase path for an input, keeping the Field\zone\ layout.</summary>
        public static string OutputPath(string smd, string outDir, string gameRoot, out string rel)
        {
            string root = gameRoot ?? Converter.GuessGameRoot(smd);
            rel = Converter.RelPath(smd, root) ?? Path.GetFileName(smd);
            return Path.Combine(outDir, Path.ChangeExtension(rel, ".ase"));
        }

        public static BatchResult Run(IList<string> files, BatchSettings s,
                                      Action<int, string> onStart, Action<string, bool> onLog,
                                      CancellationToken cancel = default(CancellationToken))
        {
            var res = new BatchResult();
            var sw = Stopwatch.StartNew();
            Textures.ClearCache();
            Converter.ClearClientCache();
            for (int i = 0; i < files.Count; i++)
            {
                if (cancel.IsCancellationRequested) { res.Cancelled = true; onLog?.Invoke(L.T("log.cancelled"), false); break; }
                string f = files[i];
                onStart?.Invoke(i, f);
                string rel = Path.GetFileName(f);
                try
                {
                    var kind = Smd.KindOf(f);
                    if (kind == SmdKind.Unknown) throw new SmdException("not a Priston Tale SMD file");
                    if ((s.StagesOnly && kind != SmdKind.Stage) || (s.ModelsOnly && kind != SmdKind.Model)) { res.Skipped++; continue; }
                    string root = s.GameRoot ?? Converter.GuessGameRoot(f);
                    string outPath = OutputPath(f, s.OutDir, root, out rel);
                    var t = s.Template;
                    var opt = new ConvertOptions
                    {
                        GameRoot = root,
                        TextureOut = s.Textures ? Path.Combine(s.OutDir, "textures") : null,
                        SplitCollision = t.SplitCollision, DropCollision = t.DropCollision, SplitObjects = t.SplitObjects,
                        CompactMaterials = t.CompactMaterials, VertexColors = t.VertexColors,
                        ClampColors = t.ClampColors, ColorScale = t.ColorScale,
                        IncludeBones = t.IncludeBones, IncludeLights = t.IncludeLights,
                        Animation = t.Animation, Lod = t.Lod,
                        MissingTextures = res.Missing,
                    };
                    var ft = Stopwatch.StartNew();
                    var sc = Converter.ConvertFile(f, outPath, opt);
                    res.Outputs.Add(outPath);
                    res.Ok++;
                    onLog?.Invoke(string.Format("OK   {0,-6} {1,-46} {2,7} verts {3,7} faces {4,4} mats  {5:0.0}s",
                        sc.Kind, rel, sc.VertexCount, sc.FaceCount, sc.Materials.Count, ft.Elapsed.TotalSeconds), true);
                    if (sc.Kind == "stage" && sc.Objects.Count > 2)
                        onLog?.Invoke("     " + L.T("log.split", sc.Objects.Count), true);
                    if (sc.Skeleton != null)
                        onLog?.Invoke("     " + L.T("log.skeleton", sc.SkeletonFile, sc.Motions.Count,
                                      sc.AnimFile.Length > 0 ? L.T("log.anim_in", sc.AnimFile) : "",
                                      sc.MissingBones ? L.T("log.bones_missing", sc.MissingBoneNames.Count) : ""), true);
                    else if (sc.MissingBones)
                        onLog?.Invoke("     " + L.T("log.no_skeleton"), false);
                }
                catch (Exception e)
                {
                    res.Failed++;
                    onLog?.Invoke(string.Format("ERR  {0}: {1}", rel, e.Message), false);
                }
            }
            if (res.Missing.Count > 0)
            {
                try
                {
                    Directory.CreateDirectory(s.OutDir);
                    res.MissingReport = Path.Combine(s.OutDir, "missing_textures.txt");
                    File.WriteAllLines(res.MissingReport, res.Missing.OrderBy(k => k.Key, StringComparer.Ordinal)
                        .Select(k => k.Key + "\t(used by " + string.Join(", ", k.Value) + ")"));
                }
                catch (Exception) { res.MissingReport = null; }
            }
            res.Elapsed = sw.Elapsed;
            return res;
        }
    }
}
