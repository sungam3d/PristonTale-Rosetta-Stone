// Whole-client conversion: drop the Priston Tale folder in, get every file in a form other tools
// read, in the same folder layout:
//
//   <out>\...\*.ase            models and maps (.smd)                      (Converter)
//   <out>\...\*.bmp / *.tga    textures with their header restored         (Textures)
//   <out>\...\*.wav            sound effects playable again (JODO -> RIFF); music (.bgm) as Name.bgm.wav
//   <out>\...\*.inf .ini ...   Korean text as UTF-8
//   <out>\...\*.ini/.inf/.in   model info rebuilt from every compiled .inx (motion frames, key
//                              events, LODs ...), as UTF-8
//   <out>\_server\...          the model info text files again in the game's own Korean code page
//                              (CP949): the form the server and the game's tools read
//
// ToGame() goes the other way for edited files: .ini/.inf/.in -> .inx, .wav -> the client's
// sound header, .bmp/.tga -> the client's texture header, UTF-8 text -> CP949.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

namespace PTSmd
{
    public class ClientSettings
    {
        public string OutDir = "client_out";
        public bool Models = true;          // .smd -> .ase
        public bool Textures = true;        // .bmp / .tga
        public bool Sounds = true;          // .wav / .bgm
        public bool Text = true;            // CP949 text -> UTF-8
        public bool ModelInfo = true;       // .inx -> .ini / .inf / .in
        public bool ServerCopy = true;      // <out>\_server\ CP949 model info
        public bool CopyOther;              // copy everything else unchanged
        public int TextCodePage = 949;      // the client's text (not model info: that is 949 in every client)
        public ConvertOptions Template = new ConvertOptions();
    }

    public class ClientResult
    {
        public int Models, Textures, Sounds, Texts, ModelInfos, Copied, Failed, Skipped;
        public int Files;
        public TimeSpan Elapsed;
        public bool Cancelled;
        public string ServerDir, MissingReport;
        public Dictionary<string, SortedSet<string>> Missing = new Dictionary<string, SortedSet<string>>();

        public List<string> SummaryParts()
        {
            var o = new List<string> { L.T("kind.models", Models), L.T("kind.textures", Textures), L.T("kind.sounds", Sounds),
                                       L.T("kind.texts", Texts), L.T("kind.infos", ModelInfos) };
            if (Copied > 0) o.Add(L.T("kind.copied", Copied));
            if (Failed > 0) o.Add(L.T("kind.failed", Failed));
            return o;
        }
        public string Summary() => string.Join(", ", SummaryParts());
    }

    public static class ClientConvert
    {
        public static readonly string[] TextExtensions = { ".inf", ".ini", ".in", ".sin", ".msg", ".txt", ".lua", ".part", ".cht" };
        static readonly string[] ModelInfoExtensions = { ".ini", ".inf", ".in" };
        public const string ServerFolder = "_server";

        static bool IsTextExt(string ext) => Array.IndexOf(TextExtensions, ext) >= 0;

        /// <summary>Folders found right inside a game folder.</summary>
        static readonly string[] TopFolders = { "char", "field", "image", "effect", "wav", "sky", "rain", "weapons", "cselect", "startimage" };
        static bool IsTopFolder(string d) => Array.Exists(TopFolders, t => string.Equals(Path.GetFileName(d), t, StringComparison.OrdinalIgnoreCase));

        /// <summary>True when the folder looks like a game client (has at least two of char, field, image, wav ...).</summary>
        public static bool LooksLikeClient(string dir) => Directory.Exists(dir) && Converter.LooksLikeClient(Path.GetFullPath(dir).TrimEnd('\\', '/'));

        static List<string> AllFiles(string root)
        {
            var o = new List<string>();
            var stack = new Stack<string>();
            stack.Push(root);
            while (stack.Count > 0)
            {
                string d = stack.Pop();
                string[] fs, ds;
                try { fs = Directory.GetFiles(d); ds = Directory.GetDirectories(d); }
                catch (Exception) { continue; }
                Array.Sort(fs, StringComparer.Ordinal);
                Array.Sort(ds, StringComparer.Ordinal);
                o.AddRange(fs);
                for (int i = ds.Length - 1; i >= 0; i--) stack.Push(ds[i]);
            }
            return o;
        }

        static string Rel(string path, string root) => Converter.RelPath(path, root) ?? Path.GetFileName(path);

        static void Write(string path, byte[] data)
        {
            string d = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(d)) Directory.CreateDirectory(d);
            File.WriteAllBytes(path, data);
        }

        /// <summary>The shipped .ini / .inf / .in an .inx was compiled from (any case), or null.</summary>
        static string ShippedSource(string inx, Dictionary<string, string> byLowerPath)
        {
            string stem = Path.Combine(Path.GetDirectoryName(inx) ?? "", Path.GetFileNameWithoutExtension(inx)).ToLowerInvariant();
            foreach (var e in ModelInfoExtensions)
                if (byLowerPath.TryGetValue(stem + e, out var p)) return p;
            return null;
        }

        /// <summary>The game folder a dropped file or folder belongs to (its paths below it are kept):
        /// the nearest folder that looks like a game folder (the game folder, or a decoded copy of
        /// it; inside it are folders named like top ones - Effect\Sky\Field, image\Sinimage\Effect),
        /// else the folder above the nearest char / Field / wav ... (a copy of single folders).</summary>
        public static string RootOf(string input)
        {
            string p = Path.GetFullPath(input).TrimEnd('\\', '/');
            string start = Directory.Exists(p) ? p : Path.GetDirectoryName(p);
            for (string d = start; d != null; d = Path.GetDirectoryName(d))
                if (LooksLikeClient(d)) return d;
            for (string d = start; d != null; d = Path.GetDirectoryName(d))
                if (IsTopFolder(d)) return Path.GetDirectoryName(d) ?? d;
            return start;
        }

        public enum FileKind { Other, Model, Texture, Sound, Text, ModelInfo, Skip }

        public static FileKind KindOf(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            switch (ext)
            {
                case ".smd": return FileKind.Model;
                case ".smb": return FileKind.Skip;                 // (bones: read with their .smd)
                case ".bmp": case ".tga": return FileKind.Texture;
                case ".wav": case ".bgm": return FileKind.Sound;
                case ".inx": return FileKind.ModelInfo;
            }
            return IsTextExt(ext) ? FileKind.Text : FileKind.Other;
        }

        /// <summary>What a set of dropped files / folders holds.</summary>
        public sealed class Scan
        {
            public readonly List<KeyValuePair<string, string>> Files = new List<KeyValuePair<string, string>>();   // file, game root
            public readonly Dictionary<FileKind, int> Count = new Dictionary<FileKind, int>();
            public readonly Dictionary<FileKind, long> Bytes = new Dictionary<FileKind, long>();
            public int this[FileKind k] => Count.TryGetValue(k, out int n) ? n : 0;
            public long BytesOf(FileKind k) => Bytes.TryGetValue(k, out long n) ? n : 0;
            /// <summary>Anything besides models and textures (what the plain .smd mode leaves out).</summary>
            public bool HasClientFiles => this[FileKind.Sound] + this[FileKind.Text] + this[FileKind.ModelInfo] > 0;
            public IEnumerable<string> Roots => Files.Select(f => f.Value).Distinct(StringComparer.OrdinalIgnoreCase);
        }

        public static Scan ScanInputs(IEnumerable<string> inputs)
        {
            Converter.ClearClientCache();                 // (folders may have changed since the last run)
            var sc = new Scan();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var input in inputs)
            {
                string root = RootOf(input);
                string p = Path.GetFullPath(input);
                var list = Directory.Exists(p) ? AllFiles(p) : File.Exists(p) ? new List<string> { p } : new List<string>();
                foreach (var f in list)
                {
                    if (!seen.Add(f)) continue;
                    sc.Files.Add(new KeyValuePair<string, string>(f, root));
                    var k = KindOf(f);
                    sc.Count[k] = sc[k] + 1;
                    long len = 0;
                    try { len = new FileInfo(f).Length; } catch (Exception) { }
                    sc.Bytes[k] = sc.BytesOf(k) + len;
                }
            }
            return sc;
        }

        /// <summary>Convert a whole client folder (see the top of this file).</summary>
        public static ClientResult Run(string root, ClientSettings s, Action<int, int, string> onProgress, Action<string, bool> onLog,
                                       CancellationToken cancel = default(CancellationToken))
            => Run(ScanInputs(new[] { root }), s, onProgress, onLog, cancel);

        /// <summary>Convert what ScanInputs found: every file into OutDir, below its game folder's layout.</summary>
        public static ClientResult Run(Scan scan, ClientSettings s, Action<int, int, string> onProgress, Action<string, bool> onLog,
                                       CancellationToken cancel = default(CancellationToken))
        {
            var res = new ClientResult();
            var sw = Stopwatch.StartNew();
            string outDir = Path.GetFullPath(s.OutDir).TrimEnd('\\', '/');
            string server = Path.Combine(outDir, ServerFolder);
            foreach (var root in scan.Roots)
                if (outDir.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase) || string.Equals(outDir, root.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
                    throw new ArgumentException(L.T("err.out_in_game", root));
            Textures.ClearCache();

            var files = scan.Files;
            res.Files = files.Count;
            var byLower = new Dictionary<string, string>();
            foreach (var f in files) byLower[f.Key.ToLowerInvariant()] = f.Key;
            // text files an .inx was compiled from are written by the .inx step
            var handledByInx = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (s.ModelInfo)
                foreach (var f in files)
                    if (KindOf(f.Key) == FileKind.ModelInfo)
                    {
                        var src = ShippedSource(f.Key, byLower);
                        if (src != null) handledByInx.Add(src);
                    }

            for (int i = 0; i < files.Count; i++)
            {
                if (cancel.IsCancellationRequested) { res.Cancelled = true; onLog?.Invoke(L.T("log.cancelled"), false); break; }
                string f = files[i].Key, root = files[i].Value;
                string rel = Rel(f, root);
                string ext = Path.GetExtension(f).ToLowerInvariant();
                string dst = Path.Combine(outDir, rel);
                onProgress?.Invoke(i, files.Count, rel);
                try
                {
                    switch (KindOf(f))
                    {
                        case FileKind.Model:
                            if (!s.Models) { res.Skipped++; continue; }
                            ConvertModel(f, rel, root, outDir, s, res, onLog);
                            break;
                        case FileKind.Texture:
                            if (!s.Textures) { res.Skipped++; continue; }
                            PTSmd.Textures.DecodeIfNeeded(f, dst);                        // (a model may have written it already)
                            res.Textures++;
                            break;
                        case FileKind.Sound:
                            if (!s.Sounds) { res.Skipped++; continue; }
                            // music (.bgm, already a plain wave) as Name.bgm.wav: plays anywhere, and goes back as .bgm
                            Write(ext == ".bgm" ? dst + ".wav" : dst, ClientFiles.DecodeWav(File.ReadAllBytes(f)));
                            res.Sounds++;
                            break;
                        case FileKind.ModelInfo:
                            if (!s.ModelInfo) { res.Skipped++; continue; }
                            ConvertInx(f, rel, root, outDir, server, s, byLower, res, onLog);
                            break;
                        case FileKind.Text:
                            if (handledByInx.Contains(f)) continue;
                            if (!s.Text) { res.Skipped++; continue; }
                            byte[] d = File.ReadAllBytes(f);
                            if (!ClientFiles.IsText(d)) { if (s.CopyOther) { Write(dst, d); res.Copied++; } continue; }
                            bool info = Array.IndexOf(ModelInfoExtensions, ext) >= 0 && IsModelFolder(rel);
                            Write(dst, ClientFiles.TextToUtf8(d, info ? 949 : s.TextCodePage));
                            res.Texts++;
                            // model info that ships only as text (no .inx) is server data as well
                            if (s.ServerCopy && Array.IndexOf(ModelInfoExtensions, ext) >= 0 && IsModelFolder(rel))
                                Write(Path.Combine(server, rel), ClientFiles.TextToCp949(d));
                            break;
                        case FileKind.Other:
                            if (s.CopyOther && !File.Exists(dst)) { Write(dst, File.ReadAllBytes(f)); res.Copied++; }
                            break;
                    }
                }
                catch (Exception e)
                {
                    res.Failed++;
                    onLog?.Invoke(string.Format("ERR  {0}: {1}", rel, e.Message), false);
                }
            }
            onProgress?.Invoke(files.Count, files.Count, "");
            if (s.ServerCopy && Directory.Exists(server)) res.ServerDir = server;
            if (res.Missing.Count > 0)
            {
                try
                {
                    Directory.CreateDirectory(outDir);
                    res.MissingReport = Path.Combine(outDir, "missing_textures.txt");
                    File.WriteAllLines(res.MissingReport, res.Missing.OrderBy(k => k.Key, StringComparer.Ordinal)
                        .Select(k => k.Key + "\t(used by " + string.Join(", ", k.Value) + ")"));
                }
                catch (Exception) { res.MissingReport = null; }
            }
            res.Elapsed = sw.Elapsed;
            return res;
        }

        static bool IsModelFolder(string rel) => rel.StartsWith("char\\", StringComparison.OrdinalIgnoreCase);

        static void ConvertModel(string f, string rel, string root, string outDir, ClientSettings s, ClientResult res, Action<string, bool> onLog)
        {
            var kind = Smd.KindOf(f);
            if (kind == SmdKind.Unknown) { res.Skipped++; return; }
            string outPath = Path.Combine(outDir, Path.ChangeExtension(rel, ".ase"));
            var t = s.Template;
            var opt = new ConvertOptions
            {
                GameRoot = root,
                TextureOut = outDir,                 // textures land in their own place in the copy
                SplitCollision = t.SplitCollision, DropCollision = t.DropCollision, SplitObjects = t.SplitObjects,
                CompactMaterials = t.CompactMaterials, VertexColors = t.VertexColors,
                ClampColors = t.ClampColors, ColorScale = t.ColorScale,
                IncludeBones = t.IncludeBones, IncludeLights = t.IncludeLights,
                Animation = t.Animation, Lod = t.Lod,
                MissingTextures = res.Missing,
            };
            var sc = Converter.ConvertFile(f, outPath, opt);
            res.Models++;
            onLog?.Invoke(string.Format("OK   {0,-6} {1}", sc.Kind, rel), true);
        }

        static void ConvertInx(string f, string rel, string root, string outDir, string server, ClientSettings s,
                               Dictionary<string, string> byLower, ClientResult res, Action<string, bool> onLog)
        {
            byte[] inx = File.ReadAllBytes(f);
            var mi = ClientFiles.ReadInx(inx);
            string shipped = ShippedSource(f, byLower);
            string textRel;
            byte[] cp949;
            if (shipped != null)
            {
                // the shipped text wins when it still builds this .inx (some are older than it)
                byte[] raw = File.ReadAllBytes(shipped);
                string srel = Rel(shipped, root);
                bool same = false;
                try { same = ClientFiles.CompileIni(ClientFiles.ReadText(raw), rel, mi.Layout.Rec).SequenceEqual(inx); }
                catch (Exception) { }
                if (same)
                {
                    if (s.Text) { Write(Path.Combine(outDir, srel), ClientFiles.TextToUtf8(raw)); res.Texts++; }
                    if (s.ServerCopy) Write(Path.Combine(server, srel), ClientFiles.TextToCp949(raw));
                    res.ModelInfos++;
                    return;
                }
                // keep the shipped one beside the rebuilt one
                if (s.Text)
                {
                    string old = Path.Combine(outDir, Path.ChangeExtension(srel, ".shipped" + Path.GetExtension(srel)));
                    Write(old, ClientFiles.TextToUtf8(raw));
                    res.Texts++;
                }
                textRel = srel;
            }
            else textRel = Path.ChangeExtension(rel, ClientFiles.SourceExtension(rel));
            string text = ClientFiles.InxToIni(mi, rel);
            cp949 = ClientFiles.CP.GetBytes(text);
            Write(Path.Combine(outDir, textRel), ClientFiles.TextToUtf8(cp949));
            if (s.ServerCopy) Write(Path.Combine(server, textRel), cp949);
            res.ModelInfos++;
        }

        // ------------------------------------------------------------------------- back to the game
        public class ToGameResult
        {
            public int Inx, Sounds, Textures, Texts, Maps, Models, Failed, Notes;
            public bool Cancelled;
            public List<string> SummaryParts()
            {
                var o = new List<string> { L.T("kind.inx", Inx), L.T("kind.sounds", Sounds), L.T("kind.textures", Textures), L.T("kind.texts", Texts) };
                if (Models > 0) o.Insert(0, L.T("kind.models", Models));
                if (Maps > 0) o.Insert(0, L.T("kind.maps", Maps));
                if (Notes > 0) o.Add(L.T("kind.notes", Notes));
                if (Failed > 0) o.Add(L.T("kind.failed", Failed));
                return o;
            }
            public string Summary() => string.Join(", ", SummaryParts());
        }

        /// <summary>What ToGame works on: the files given, and every file below the folders given -
        /// except, inside a dropped folder, the decoder's own _server copy (its unedited model info
        /// would overwrite the edited ones), a game_format folder (earlier output),
        /// missing_textures.txt, and anything inside outDir.</summary>
        public static List<string> ToGameFiles(IEnumerable<string> inputs, string outDir)
        {
            Converter.ClearClientCache();                 // (folders may have changed since the last run)
            string od = Path.GetFullPath(outDir).TrimEnd('\\') + "\\";
            var files = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var p0 in inputs)
            {
                string p = Path.GetFullPath(p0).TrimEnd('\\');
                if (File.Exists(p)) { if (seen.Add(p)) files.Add(p); continue; }
                if (!Directory.Exists(p)) continue;
                foreach (var f in AllFiles(p))
                {
                    string rel = f.Substring(p.Length + 1);
                    if (rel.StartsWith(ServerFolder + "\\", StringComparison.OrdinalIgnoreCase) ||
                        rel.StartsWith("game_format\\", StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(rel, "missing_textures.txt", StringComparison.OrdinalIgnoreCase) ||
                        f.StartsWith(od, StringComparison.OrdinalIgnoreCase)) continue;
                    if (seen.Add(f)) files.Add(f);
                }
            }
            return files;
        }

        /// <summary>Edited files -> the forms the client ships: .ini/.inf/.in also as .inx (CP949 text
        /// next to it), .wav with the client's sound header in the layout its loader reads (music,
        /// decoded as Name.bgm.wav: Name.bgm, a plain wave), .bmp/.tga in a form the game's loaders read with the client's
        /// texture header, other UTF-8 / UTF-16 text as CP949.  Files are written under outDir with
        /// the same layout below the game folder (found from char\, field\ ... in the path).
        /// layout: 172 (current clients) or 120 (2012 clients).  onLog gets "OK ..." lines and notes
        /// (what was repaired, or what the game will not read as intended).</summary>
        public static ToGameResult ToGame(IEnumerable<string> inputs, string outDir, Action<string, bool> onLog, int layout = 172,
                                          Action<int, int, string> onProgress = null, CancellationToken cancel = default(CancellationToken),
                                          int textCodePage = 949)
        {
            if (layout != 120 && layout != 172) throw new ArgumentException(L.T("err.layout"));
            var r = new ToGameResult();
            var files = ToGameFiles(inputs, outDir);
            for (int i = 0; i < files.Count; i++)
            {
                if (cancel.IsCancellationRequested) { r.Cancelled = true; onLog?.Invoke(L.T("log.cancelled"), false); break; }
                string f = files[i];
                string ext = Path.GetExtension(f).ToLowerInvariant();
                string root = RootOf(f);                                  // (wav\, sky\ ... count too)
                string rel = Rel(f, root);
                string dst = Path.Combine(outDir, rel);
                onProgress?.Invoke(i, files.Count, rel);
                var notes = new List<string>();
                try
                {
                    if (ext == ".wav" || ext == ".bgm")
                    {
                        byte[] d = File.ReadAllBytes(f);
                        if (ext == ".bgm") Write(dst, ClientFiles.DecodeWav(d));                       // music: a plain wave
                        else if (f.EndsWith(".bgm.wav", StringComparison.OrdinalIgnoreCase))
                            Write(dst.Substring(0, dst.Length - 4), ClientFiles.DecodeWav(d));             // Name.bgm.wav -> Name.bgm
                        else Write(dst, ClientFiles.WavForGame(d, "JODO", notes));
                        r.Sounds++;
                    }
                    else if (ext == ".bmp" || ext == ".tga")
                    {
                        Write(dst, PTSmd.Textures.ForGame(File.ReadAllBytes(f), notes));
                        r.Textures++;
                    }
                    else if (ext == ".ase")
                    {
                        if (AseToSmd.LooksLikeStage(f, out string hint))
                        {
                            string smdRel = EncodeMap(f, rel, hint, outDir, layout, notes);
                            r.Maps++;
                            onLog?.Invoke("OK   " + smdRel, true);
                        }
                        else
                        {
                            foreach (string built in EncodeModel(f, rel, outDir, notes)) onLog?.Invoke("OK   " + built, true);
                            r.Models++;
                        }
                    }
                    else if (IsTextExt(ext))
                    {
                        byte[] raw = File.ReadAllBytes(f);
                        if (!ClientFiles.IsText(raw)) continue;
                        if (f.EndsWith(".shipped" + ext, StringComparison.OrdinalIgnoreCase)) continue;
                        // model info is in the Korean code page in every client; other text in the client's own
                        bool info = Array.IndexOf(ModelInfoExtensions, ext) >= 0 && IsModelInfo(raw);
                        int page = info ? 949 : textCodePage;
                        string text = ClientFiles.ReadText(raw, page);
                        byte[] cp = ClientFiles.TextToCp949(raw, page);
                        if (!ReferenceEquals(cp, raw))
                        {
                            var lost = ClientFiles.Unmappable(text, page);
                            if (lost.Count > 0)
                                notes.Add(L.T("note.unmappable", string.Join(" ", lost.Take(10).Select(c => "'" + c + "'")) + (lost.Count > 10 ? " ..." : "")));
                        }
                        Write(dst, cp);
                        r.Texts++;
                        if (info)
                        {
                            string relInx = Path.ChangeExtension(rel, ".inx");
                            if (rel.IndexOf('\\') < 0)
                                notes.Add(L.T("note.no_game_folder"));
                            Write(Path.Combine(outDir, relInx), ClientFiles.CompileIni(text, relInx, layout, null, null, notes.Add));
                            r.Inx++;
                            onLog?.Invoke("OK   " + relInx, true);
                        }
                    }
                    foreach (var n in notes) { r.Notes++; onLog?.Invoke(L.T("log.note", rel, n), false); }
                }
                catch (Exception e)
                {
                    r.Failed++;
                    onLog?.Invoke("ERR  " + rel + ": " + e.Message, false);
                }
            }
            onProgress?.Invoke(files.Count, files.Count, "");
            return r;
        }

        /// <summary>A map .ase -> .smd the way the game builds it (AseToSmd).  The textures are named with
        /// the game folder the .ase sits in (rel); outside a game folder, with the folder of the map it was
        /// decoded from (hint: our decoder and exporters name its materials "PT_village-2...").  The lighting
        /// is the map's own (an existing .smd of the same map in the output, else the client's setting).
        /// Returns the .smd's path below outDir.</summary>
        static string EncodeMap(string f, string rel, string hint, string outDir, int layout, List<string> notes)
        {
            var o = new EncodeOptions { WideAreas = layout != 120 };
            string name = Path.GetFileNameWithoutExtension(f);
            string dir = Path.GetDirectoryName(rel);
            if (string.IsNullOrEmpty(dir))
            {
                if (!AseToSmd.KnownMap(name, out dir, out _) && hint != null && AseToSmd.KnownMap(hint, out dir, out _))
                {
                    notes.Add(L.T("note.ase_named", hint + ".smd", name + ".ase"));
                    name = hint;
                }
                if (string.IsNullOrEmpty(dir)) dir = AseToSmd.GameDirFromBitmaps(f);
                if (string.IsNullOrEmpty(dir))
                {
                    dir = "field\\" + Path.GetFileName(Path.GetDirectoryName(Path.GetFullPath(f)));
                    notes.Add(L.T("note.ase_folder", dir + "\\"));
                }
            }
            dir = dir.TrimEnd('\\', '/');
            o.DataDir = dir + "\\";
            string smdRel = Path.Combine(dir, name + ".smd");
            string dst = Path.Combine(outDir, smdRel);
            if (!AseToSmd.ReadLighting(dst, o))
                AseToSmd.SetLighting(o, AseToSmd.KnownMap(name, out _, out bool b160) && b160);
            var er = AseToSmd.Stage(f, dst, o);
            if (er.TooManyVertices) notes.Add(L.T("note.ase_vertices", er.Vertices));
            if (er.TooManyFaces) notes.Add(L.T("note.ase_faces", er.Faces));
            if (er.BadFaces > 0) notes.Add(L.T("note.ase_badface", er.BadFaces));
            if (er.CrowdedFaces > AseToSmd.CrowdedLimit)
                notes.Add(L.T("note.ase_crowded", er.CrowdedFaces, Math.Round(er.CrowdedX).ToString(System.Globalization.CultureInfo.InvariantCulture),
                              Math.Round(er.CrowdedY).ToString(System.Globalization.CultureInfo.InvariantCulture)));
            return smdRel;
        }

        /// <summary>A model .ase -> .smd (+ .smb) the way the game builds it (AseToSmd.Model).  The .smb
        /// (bones and animation) is written when the .ase has its own animated skeleton: a monster with
        /// its animation inside, a motion file, a map prop on bones.  Armour and monsters on a shared
        /// skeleton file (our decoder names it in *PT_SKELETON) get the .smd only: their bones just
        /// place the skin.  Returns the files written, below outDir.</summary>
        static List<string> EncodeModel(string f, string rel, string outDir, List<string> notes)
        {
            var o = new EncodeOptions();
            string name = Path.GetFileNameWithoutExtension(f);
            string dir = Path.GetDirectoryName(rel);
            if (string.IsNullOrEmpty(dir))
            {
                dir = AseToSmd.GameDirFromBitmaps(f);
                if (string.IsNullOrEmpty(dir))
                {
                    dir = Path.GetFileName(Path.GetDirectoryName(Path.GetFullPath(f)));
                    notes.Add(L.T("note.ase_folder", dir + "\\"));
                }
            }
            dir = dir.TrimEnd('\\', '/');
            o.DataDir = dir + "\\";
            AseToSmd.ModelParts(f, out bool bones, out bool skinned, out bool meshes);
            string skel = AseToSmd.SkeletonName(f), smbName = null;
            bool animated = AseToSmd.HasBoneAnimation(f);
            if (bones && !meshes) smbName = skel ?? name + ".smb";                       // (a motion / skeleton file)
            else if (bones && (skel == null ? animated : string.Equals(skel, name + ".smb", StringComparison.OrdinalIgnoreCase)))
                smbName = name + ".smb";
            var outl = new List<string>();
            string smdRel = Path.Combine(dir, name + ".smd"), smbRel = smbName != null ? Path.Combine(dir, smbName) : null;
            var mr = AseToSmd.Model(f, meshes ? Path.Combine(outDir, smdRel) : null, smbRel != null ? Path.Combine(outDir, smbRel) : null, o);
            if (mr.WroteSmd) outl.Add(smdRel);
            if (mr.WroteSmb) outl.Add(smbRel);
            if (mr.Unassigned > 0) notes.Add(L.T("note.ase_unassigned", mr.Unassigned));
            if (skinned && !bones) notes.Add(L.T("note.ase_nobones"));
            return outl;
        }

        /// <summary>Model info text (has a *모양파일 or *동작파일 line), not some other .ini.</summary>
        static bool IsModelInfo(byte[] raw)
        {
            string t = ClientFiles.ReadText(raw);
            return t.Contains("*모양파일") || t.Contains("*동작파일") || t.Contains("*파일연결");
        }
    }
}
