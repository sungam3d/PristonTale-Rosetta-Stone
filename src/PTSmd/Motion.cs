// Character / monster motion tables and skeleton lookup (port of smdanim/motion.py).
//
// How Priston Tale wires an animated model together
//   <model>.smd   skinned mesh; every vertex stores the NAME of the one bone it follows
//   <motion>.smb  skeleton: every Bip01 bone with its bind pose and ALL animation keys.
//                 The game glues several motion ASE files end to end into one timeline.
//   <name>.inx    compiled .ini: model file, motion file, detail levels, motion table
//   <name>.ini    the same as text (CP949 Korean), shipped for some files
// Player bodies/heads (char\tmABCD) share the class skeletons m1.smb .. m8.smb.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace PTSmd
{
    public class Motion
    {
        public string Name;
        public int State, Start, End, Piece;
        public List<int> Events = new List<int>();
        public bool Loop;
    }

    public class RawMotion
    {
        public int State, Piece, Start, End;
        public List<int> Events = new List<int>();
        public bool Loop;
        public string Label = "";
    }

    public class ModelInfo
    {
        public string Path = "", ModelFile = "", MotionFile = "", SubFile = "", LinkFile = "";
        public List<string>[] Lod = { new List<string>(), new List<string>(), new List<string>() };
        public List<RawMotion> RawMotions = new List<RawMotion>();

        /// <summary>Motion list on the absolute timeline of the matching .smb.</summary>
        public List<Motion> Motions(List<int[]> segments)
        {
            var outl = new List<Motion>();
            var count = new Dictionary<string, int>();
            foreach (var r in RawMotions)
            {
                int bas = 0;
                if (r.Piece >= 1 && r.Piece <= segments.Count) bas = segments[r.Piece - 1][0] / MotionInfo.TicksPerFrame;
                string label = r.Label.Length > 0 ? r.Label
                    : (MotionInfo.StateNames.TryGetValue(r.State, out string sn) ? sn : "motion");
                count[label] = count.TryGetValue(label, out int c) ? c + 1 : 1;
                outl.Add(new Motion
                {
                    Name = label + "_" + count[label].ToString("00"), State = r.State,
                    Start = bas + r.Start, End = bas + r.End, Events = r.Events.Select(x => bas + x).ToList(),
                    Loop = r.Loop, Piece = r.Piece,
                });
            }
            return outl;
        }
    }

    public class Rig
    {
        public string Smb;                 // skeleton / motion file
        public ModelInfo Info;             // motion table (or null)
        public string How = "";            // why this skeleton was chosen
        public List<string> LodHigh = new List<string>();
        public bool Shared;                // player class skeleton (m1..m8)
    }

    public static class MotionInfo
    {
        public const int TicksPerFrame = 160;

        public static readonly Dictionary<int, string> StateNames = new Dictionary<int, string>
        {
            { 0x40, "stand" }, { 0x50, "walk" }, { 0x60, "run" }, { 0x80, "fall" }, { 0x100, "attack" },
            { 0x110, "damage" }, { 0x120, "die" }, { 0x130, "idle" }, { 0x140, "potion" }, { 0x150, "skill" },
            { 0x170, "land_small" }, { 0x180, "land_big" }, { 0x200, "restart" }, { 0x210, "warp" },
            { 0x220, "cheer" }, { 0x300, "hammer" },
        };

        // Korean .ini keywords (written as escapes so the source is plain ASCII)
        const string KModel = "모양파일";            // model file
        const string KMotion = "동작파일";           // motion file
        const string KSub = "보조동작파일";  // extra motion file
        const string KLink = "파일연결";             // file link
        static readonly string[] KLod = { "정밀모양", "보통모양", "저질모양" };
        const string KPiece = "동작모음";            // motion collection
        const string KAction = "동작";                       // ...motion
        const string KRepeat = "반복";                       // loop
        static readonly (string kw, string en)[] IniWords =
        {
            ("서있기", "stand"), ("걷는", "walk"), ("뛰는", "run"),
            ("떨어지는", "fall"), ("공격", "attack"), ("타격", "damage"),
            ("죽는", "die"), ("죽기", "die"), ("정지", "idle"), ("물약", "potion"),
            ("기술", "skill"), ("작은착지", "land_small"), ("큰착지", "land_big"),
            ("다시시작", "restart"), ("워프", "warp"), ("만세", "cheer"),
            ("망치", "hammer"), ("대기", "idle"),
        };
        static readonly Regex ActionRe = new Regex("동작\\d*[a-z]?$");

        // Player class skeletons.  Name scheme: [C] + race(T/M) + sex(m/f) + part(b/h) + class letter
        static readonly Regex PlayerRe = new Regex("^c?([tm])([mf])([bh])[-_]?m?([a-f])", RegexOptions.IgnoreCase);   // MmbA34, Tfh-D03d, Mfh_B01b, MmbmA01b
        static readonly Dictionary<string, int> ClassSkeleton = new Dictionary<string, int>
        {
            { "ta", 1 }, { "tb", 1 }, { "tc", 4 }, { "td", 2 }, { "te", 6 }, { "tf", 8 },
            { "ma", 1 }, { "mb", 2 }, { "mc", 5 }, { "md", 3 }, { "me", 7 },
        };
        public static readonly Dictionary<int, string> ClassNames = new Dictionary<int, string>
        {
            { 1, "Knight / Mechanician / Fighter" }, { 2, "Atalanta / Archer" }, { 3, "Magician" }, { 4, "Pikeman" },
            { 5, "Priestess" }, { 6, "Assassin" }, { 7, "Shaman" }, { 8, "Martial Artist" },
        };

        static Encoding korean;
        static Encoding Korean
        {
            get
            {
                if (korean == null)
                {
#if !NETFRAMEWORK
                    Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
#endif
                    korean = Encoding.GetEncoding(949);
                }
                return korean;
            }
        }

        static string CStr(byte[] b, int o, int max)
        {
            int n = 0;
            while (n < max && o + n < b.Length && b[o + n] != 0) n++;
            return Korean.GetString(b, o, n);
        }

        // Frames are stored with a key byte interleaved: value = byte0 | byte2 << 8
        static int Frame16(byte[] b, int o) => b[o] | (b[o + 2] << 8);

        public static ModelInfo ReadInx(string path)
        {
            byte[] b = File.ReadAllBytes(path);
            var mi = new ModelInfo { Path = path };
            if (b.Length < 0x18C) return mi;
            mi.ModelFile = CStr(b, 0, 64);
            mi.MotionFile = CStr(b, 0x40, 64);
            mi.SubFile = CStr(b, 0x80, 64);
            for (int k = 0; k < 3; k++)
            {
                int o = 0xC0 + 68 * k;
                int n = Math.Max(0, Math.Min(Bin.I(b, o), 4));
                for (int j = 0; j < n; j++) mi.Lod[k].Add(CStr(b, o + 4 + 16 * j, 16));
            }
            // 512 smMOTIONINFO records; 120 bytes in 2012 files, 172 bytes in current ones
            int size = 0, count = 0;
            foreach (int sz in new[] { 172, 120 })
            {
                int cntOff = 0x18C + 512 * sz;
                if (cntOff + 4 <= b.Length)
                {
                    int c = Bin.I(b, cntOff);
                    if (c >= 0 && c <= 512) { size = sz; count = c; break; }
                }
            }
            if (size == 0) return mi;
            int tail = size - 120;                   // extra weapon-code bytes in the newer layout
            for (int k = 0; k < count; k++)
            {
                int o = 0x18C + size * k;
                int state = (int)Bin.U(b, o);
                if (state == 0) continue;
                var r = new RawMotion { State = state, Start = Frame16(b, o + 4), End = Frame16(b, o + 16) };
                for (int e = 0; e < 4; e++)
                {
                    uint x = Bin.U(b, o + 20 + 4 * e);
                    if (x != 0) r.Events.Add(r.Start + (int)(x / TicksPerFrame));
                }
                r.Loop = Bin.U(b, o + 0x6C + tail) != 0;
                r.Piece = Bin.I(b, o + 0x74 + tail);
                mi.RawMotions.Add(r);
            }
            return mi;
        }

        static bool AllDigits(string s) => s.Length > 0 && s.All(ch => ch >= '0' && ch <= '9');

        public static ModelInfo ReadIni(string path)
        {
            string text = Korean.GetString(File.ReadAllBytes(path));
            var mi = new ModelInfo { Path = path };
            int piece = 0;
            foreach (string raw in text.Split('\n'))
            {
                string line = raw;
                int c = line.IndexOf("//", StringComparison.Ordinal);
                if (c >= 0) line = line.Substring(0, c);
                line = line.Trim();
                if (!line.StartsWith("*")) continue;
                var parts = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                string key = parts[0].Substring(1);
                var args = parts.Skip(1).Select(a => a.Trim('"')).ToList();
                int lod = Array.IndexOf(KLod, key);
                if (key == KModel && args.Count > 0) mi.ModelFile = args[0];
                else if (key == KMotion && args.Count > 0) mi.MotionFile = args[0];
                else if (key == KSub && args.Count > 0) mi.SubFile = args[0];
                else if (key == KLink && args.Count > 0) mi.LinkFile = args[0];
                else if (lod >= 0) mi.Lod[lod].AddRange(args);
                else if (key == KPiece) piece++;
                else if (key.EndsWith(KAction, StringComparison.Ordinal) || (key.Length > 0 && char.IsDigit(key[key.Length - 1]))
                         || ActionRe.IsMatch(key))
                {
                    var nums = args.Where(AllDigits).Select(int.Parse).ToList();
                    if (nums.Count >= 2 && piece > 0)
                    {
                        string label = "motion";
                        foreach (var w in IniWords)
                            if (key.StartsWith(w.kw, StringComparison.Ordinal)) { label = w.en; break; }
                        mi.RawMotions.Add(new RawMotion
                        {
                            Piece = piece, Start = nums[0], End = nums[1], Events = nums.Skip(2).Take(4).ToList(),
                            Loop = args.Contains(KRepeat), Label = label,
                        });
                    }
                }
            }
            return mi;
        }

        static readonly Dictionary<string, (DateTime, ModelInfo)> infoCache = new Dictionary<string, (DateTime, ModelInfo)>();

        public static ModelInfo ReadInfo(string path)
        {
            var t = File.GetLastWriteTimeUtc(path);
            lock (infoCache)
                if (infoCache.TryGetValue(path, out var c) && c.Item1 == t) return c.Item2;
            var mi = path.EndsWith(".inx", StringComparison.OrdinalIgnoreCase) ? ReadInx(path) : ReadIni(path);
            lock (infoCache) infoCache[path] = (t, mi);
            return mi;
        }

        /// <summary>(start tick, end tick) of every glued motion piece stored in the .smb header.</summary>
        public static List<int[]> SmbSegments(string path)
        {
            var b = new byte[0x22C];
            using (var f = File.OpenRead(path)) f.Read(b, 0, b.Length);
            int n = Bin.I(b, 0x28);
            var outl = new List<int[]>();
            if (n < 0 || n > 32) return outl;
            for (int i = 0; i < n; i++) outl.Add(new[] { Bin.I(b, 0x2C + 16 * i), Bin.I(b, 0x30 + 16 * i) });
            return outl;
        }

        // ------------------------------------------------------------------ lookup
        static string[] SortedNames(string folder)
        {
            try
            {
                var n = Directory.GetFiles(folder).Select(System.IO.Path.GetFileName).ToArray();
                Array.Sort(n, StringComparer.Ordinal);
                return n;
            }
            catch (Exception) { return new string[0]; }
        }

        static string CiFile(string folder, string name)
        {
            foreach (string n in SortedNames(folder))
                if (string.Equals(n, name, StringComparison.OrdinalIgnoreCase)) return System.IO.Path.Combine(folder, n);
            return null;
        }

        static string BaseName(string aseName) =>
            System.IO.Path.GetFileNameWithoutExtension(aseName.Replace('\\', '/').Split('/').Last());

        static string SmbFor(string folder, string aseName) => CiFile(folder, BaseName(aseName) + ".smb");

        /// <summary>Class skeleton number (1..8) from a player body/head/costume file name, or 0.</summary>
        public static int PlayerClass(string name)
        {
            var m = PlayerRe.Match(name);
            if (!m.Success) return 0;
            return ClassSkeleton.TryGetValue(m.Groups[1].Value.ToLowerInvariant() + m.Groups[4].Value.ToLowerInvariant(), out int c) ? c : 0;
        }

        /// <summary>Pick the skeleton (.smb) and motion table for a skinned .smd.</summary>
        public static Rig FindRig(string smdPath, ICollection<string> boneNames)
        {
            string folder = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(smdPath));
            string bas = System.IO.Path.GetFileNameWithoutExtension(smdPath);
            var rig = new Rig();
            var names = SortedNames(folder);

            // 1) an .inx / .ini in the same folder whose model file is this .smd
            var infos = new List<ModelInfo>();
            foreach (string n in names)
                if (n.EndsWith(".inx", StringComparison.OrdinalIgnoreCase) || n.EndsWith(".ini", StringComparison.OrdinalIgnoreCase))
                    try { infos.Add(ReadInfo(System.IO.Path.Combine(folder, n))); } catch (Exception) { }
            foreach (var mi in infos.OrderBy(m => !m.Path.EndsWith(".inx", StringComparison.OrdinalIgnoreCase)))
            {
                bool mine = string.Equals(BaseName(mi.ModelFile), bas, StringComparison.OrdinalIgnoreCase);
                if (mine && mi.MotionFile.Length > 0)
                {
                    string smb = SmbFor(folder, mi.MotionFile);
                    if (smb != null)
                    {
                        rig.Smb = smb; rig.Info = mi; rig.LodHigh = new List<string>(mi.Lod[0]);
                        rig.How = "motion file of " + System.IO.Path.GetFileName(mi.Path);
                        break;
                    }
                }
                if (mine && mi.LinkFile.Length > 0)
                {
                    string link = CiFile(folder, System.IO.Path.GetFileNameWithoutExtension(mi.LinkFile) + ".inx") ?? CiFile(folder, mi.LinkFile);
                    if (link != null)
                    {
                        var li = ReadInfo(link);
                        string smb = SmbFor(folder, li.MotionFile);
                        if (smb != null)
                        {
                            rig.Smb = smb; rig.Info = li; rig.LodHigh = new List<string>(mi.Lod[0]); rig.Shared = true;
                            rig.How = System.IO.Path.GetFileName(mi.Path) + " -> " + System.IO.Path.GetFileName(link);
                            break;
                        }
                    }
                }
            }
            // 2) player body / head / costume: shared class skeleton
            if (rig.Smb == null)
            {
                int cls = PlayerClass(bas);
                if (cls > 0)
                {
                    string smb = CiFile(folder, "m" + cls + ".smb");
                    if (smb != null)
                    {
                        rig.Smb = smb; rig.Shared = true;
                        rig.How = "class skeleton m" + cls + " (" + ClassNames[cls] + ")";
                        foreach (string nm in new[] { "M" + cls + "Bip.inx", "M" + cls + "Bip.in" })
                        {
                            string p = CiFile(folder, nm);
                            if (p != null) { rig.Info = ReadInfo(p); break; }
                        }
                    }
                }
            }
            // 3) same-name .smb
            if (rig.Smb == null)
            {
                string smb = CiFile(folder, bas + ".smb");
                if (smb != null) { rig.Smb = smb; rig.How = "same name"; }
            }
            // 4) any .smb in the folder that has every bone the mesh needs
            if (rig.Smb == null && boneNames != null && boneNames.Count > 0)
            {
                foreach (string n in names)
                {
                    if (!n.EndsWith(".smb", StringComparison.OrdinalIgnoreCase)) continue;
                    try
                    {
                        var have = new HashSet<string>(new Model(System.IO.Path.Combine(folder, n)).Objects.Select(o => o.Name));
                        if (boneNames.All(have.Contains)) { rig.Smb = System.IO.Path.Combine(folder, n); rig.How = "contains all bones"; break; }
                    }
                    catch (Exception) { }
                }
            }
            return rig;
        }

        /// <summary>Motion table for a skeleton file itself (Tees.smb, mGknight.smb, m1.smb).</summary>
        public static Rig FindRigForSmb(string smbPath)
        {
            string folder = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(smbPath));
            string bas = System.IO.Path.GetFileNameWithoutExtension(smbPath);
            var rig = new Rig { Smb = smbPath, How = "skeleton file" };
            foreach (string n in SortedNames(folder).OrderBy(n => !n.EndsWith(".inx", StringComparison.OrdinalIgnoreCase)))
            {
                string l = n.ToLowerInvariant();
                if (!(l.EndsWith(".inx") || l.EndsWith(".ini") || l.EndsWith(".in"))) continue;
                ModelInfo mi;
                try { mi = ReadInfo(System.IO.Path.Combine(folder, n)); } catch (Exception) { continue; }
                if (string.Equals(BaseName(mi.MotionFile), bas, StringComparison.OrdinalIgnoreCase) && mi.RawMotions.Count > 0)
                {
                    rig.Info = mi;
                    rig.How = "motion table of " + n;
                    break;
                }
            }
            return rig;
        }
    }
}
