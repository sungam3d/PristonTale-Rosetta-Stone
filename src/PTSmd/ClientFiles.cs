// Everything else in a Priston Tale client folder: sounds, text files and model info.
// A line-for-line port of smdanim/clientfiles.py (scripts/compare_clientfiles.py checks that
// both give the same bytes for every file of a client).
//
//   .wav   the client's sound effects start with "JODO" instead of "RIFF"; the rest is a normal
//          PCM wave.  .bgm (music) files are already normal waves.
//   text   .inf .ini .in .sin .msg .txt ... are Korean text in code page 949: readable copies
//          are written as UTF-8 (with a BOM).
//   .inx   the compiled form of a model's .ini / .inf / .in (smMODELINFO, fileread.cpp
//          AddModelDecode): model + motion files, detail levels and the motion table, with the
//          start/end frames scrambled with a checksum of the file's path (MotionKeyWordEncode).
//          ReadInx() undoes that, InxToIni() writes the text the game compiles it from, and
//          CompileIni() builds the .inx again exactly as the game does.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace PTSmd
{
    public static class ClientFiles
    {
        public const int EXT = 10;              // CHRMOTION_EXT: motion slots below this are unused
        public const int MOTION_MAX = 512;
        public const int TALK_MAX = 30;
        public const int NPC_RATE_MAX = 30;

        static readonly Dictionary<uint, string> StateWord = new Dictionary<uint, string>
        {
            { 0x40, "서있기" }, { 0x50, "걷는" }, { 0x60, "뛰는" }, { 0x80, "떨어지는" }, { 0x100, "공격" },
            { 0x110, "타격" }, { 0x120, "죽기" }, { 0x130, "가끔" }, { 0x140, "먹기" }, { 0x150, "기술" },
            { 0x170, "작은착지" }, { 0x180, "큰착지" }, { 0x200, "다시시작" }, { 0x210, "워프" },
            { 0x220, "만세" }, { 1, "기타" },
        };
        static readonly uint[] AutoRepeat = { 0x40, 0x50, 0x60 };      // stand / walk / run loop by themselves
        static readonly Dictionary<uint, string> TalkWord = new Dictionary<uint, string>
        {
            { 0x400, "아표정" }, { 0x410, "이표정" }, { 0x420, "오표정" }, { 0x430, "눈깜빡표정" },
            { 0, "무표정(작동않함)" }, { 0x440, "웃는표정" }, { 0x450, "화난표정" }, { 0x460, "슬픈표정" },
            { 0x470, "놀란표정" }, { 0x480, "고유표정" }, { 0x490, "특별표정" },
        };
        // *적용직업 (BitMaskJobNames, plus the classes added after the 2012 source)
        static readonly (string name, uint bit)[] JobBits =
        {
            ("Fighter", 0x01), ("Mechanician", 0x02), ("Archer", 0x04), ("Pikeman", 0x08),
            ("Atalanta", 0x10), ("Knight", 0x20), ("Magician", 0x40), ("Priest", 0x80),
            ("Assassin", 0x100), ("Shaman", 0x200), ("MartialArtist", 0x400),
        };

        // ------------------------------------------------------------------------- small helpers
        static Encoding cp;
        /// <summary>Code page 949 that writes '?' and reads U+FFFD for what it cannot map (as Python's 'replace').</summary>
        public static Encoding CP
        {
            get
            {
                if (cp == null)
                {
#if !NETFRAMEWORK
                    Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
#endif
                    cp = Encoding.GetEncoding(949, new EncoderReplacementFallback("?"), new DecoderReplacementFallback("�"));
                }
                return cp;
            }
        }
        static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);
        static Encoding strictCp;
        /// <summary>Code page 949 that throws on bytes it cannot map.</summary>
        static Encoding StrictCP
        {
            get
            {
                if (strictCp == null)
                {
                    var unused = CP;                                // (registers the code pages on .NET 8)
                    strictCp = Encoding.GetEncoding(949, EncoderFallback.ExceptionFallback, DecoderFallback.ExceptionFallback);
                }
                return strictCp;
            }
        }

        /// <summary>GetSpeedSum (character.cpp): the checksum of a game-relative path, case-insensitive.</summary>
        public static uint SpeedSum(string name)
        {
            uint s2 = 0, dw = 0, cnt = 0;
            foreach (byte b in CP.GetBytes(name))
            {
                uint ch = b;
                if (ch >= 97 && ch <= 122) ch -= 0x20;
                s2 += ch * (cnt + 1);
                dw += ch * cnt * cnt;
                cnt++;
            }
            return (dw << 24) | (cnt << 16) | s2;
        }

        static bool Starts(byte[] d, string magic)
        {
            if (d.Length < magic.Length) return false;
            for (int i = 0; i < magic.Length; i++) if (d[i] != magic[i]) return false;
            return true;
        }

        /// <summary>Client sound -> playable .wav (only the first 4 bytes differ).</summary>
        public static byte[] DecodeWav(byte[] data)
        {
            if (!Starts(data, "JODO")) return data;
            var o = (byte[])data.Clone();
            o[0] = (byte)'R'; o[1] = (byte)'I'; o[2] = (byte)'F'; o[3] = (byte)'F';
            return o;
        }

        public static byte[] EncodeWav(byte[] data)
        {
            if (!Starts(data, "RIFF")) return data;
            var o = (byte[])data.Clone();
            o[0] = (byte)'J'; o[1] = (byte)'O'; o[2] = (byte)'D'; o[3] = (byte)'O';
            return o;
        }

        /// <summary>An edited .wav in the layout the game's loader reads (Dxwav.cpp
        /// CreateBufferFromWaveFile).  It does not walk the RIFF chunks: it wants the 16-byte "fmt "
        /// chunk at byte 12 and then "data" (or one 4-byte "fact" chunk, then "data"; or an 18-byte
        /// "fmt " with cbSize 0, "fact", "data").  Other files - LIST / bext / JUNK chunks from sound
        /// editors, WAVE_FORMAT_EXTENSIBLE - are rewritten to fmt + data; PCM inside
        /// WAVE_FORMAT_EXTENSIBLE becomes plain PCM.  magic: "JODO" (the client's sound effects).
        /// notes gets what was changed, or why the game will not play the sound right.</summary>
        public static byte[] WavForGame(byte[] data, string magic, List<string> notes)
        {
            if (data.Length < 20 || !(Starts(data, "RIFF") || Starts(data, "JODO")) || Encoding.ASCII.GetString(data, 8, 4) != "WAVE")
            {
                notes.Add("not a .wav file the game can play");
                return data;
            }
            int fmtAt = -1, fmtLen = 0, dataAt = -1, dataLen = 0;
            var ids = new List<string>();
            long p = 12;
            while (p + 8 <= data.Length && dataAt < 0)
            {
                string id = Encoding.ASCII.GetString(data, (int)p, 4);
                long len = U32(data, (int)p + 4), avail = data.Length - p - 8;
                ids.Add(id);
                if (id == "fmt " && fmtAt < 0) { fmtAt = (int)p + 8; fmtLen = (int)Math.Min(len, avail); }
                else if (id == "data")
                {
                    dataAt = (int)p + 8;
                    dataLen = (int)Math.Min(len, avail);
                    if (len > avail) notes.Add("the sound data is cut short");
                }
                p += 8 + len + (len & 1);
            }
            if (fmtAt < 0 || fmtLen < 16 || dataAt < 0) { notes.Add("damaged .wav (no fmt or data chunk)"); return data; }
            int tag = data[fmtAt] | data[fmtAt + 1] << 8, bits = data[fmtAt + 14] | data[fmtAt + 15] << 8;
            bool extensible = tag == 0xFFFE && fmtLen >= 40;
            if (extensible) tag = data[fmtAt + 24] | data[fmtAt + 25] << 8;          // the sub-format
            if (tag != 1)
                notes.Add((tag == 3 ? "32-bit float sound" : "not PCM sound (format " + tag + ")") +
                          ": the game plays it as noise - export it as 16-bit PCM");
            else if (bits != 8 && bits != 16)
                notes.Add(bits + "-bit sound: the game plays 8 and 16-bit sound - export it as 16-bit PCM");
            bool asIs = fmtAt == 20 && !extensible &&
                        ((fmtLen == 16 && ids.Count == 2) ||                                                    // fmt, data
                         (fmtLen == 16 && ids.Count == 3 && ids[1] == "fact" && U32(data, 40) == 4) ||        // fmt, fact, data
                         (fmtLen == 18 && data[36] == 0 && data[37] == 0 && ids.Count == 3 && ids[1] == "fact" && U32(data, 42) == 4));
            byte[] o;
            if (asIs) o = (byte[])data.Clone();
            else
            {
                int pad = dataLen & 1;
                o = new byte[44 + dataLen + pad];
                Buffer.BlockCopy(data, fmtAt, o, 20, 16);
                if (extensible) { o[20] = (byte)tag; o[21] = (byte)(tag >> 8); }
                Put(o, 4, 36 + dataLen + pad);
                o[8] = (byte)'W'; o[9] = (byte)'A'; o[10] = (byte)'V'; o[11] = (byte)'E';
                o[12] = (byte)'f'; o[13] = (byte)'m'; o[14] = (byte)'t'; o[15] = (byte)' ';
                Put(o, 16, 16);
                o[36] = (byte)'d'; o[37] = (byte)'a'; o[38] = (byte)'t'; o[39] = (byte)'a';
                Put(o, 40, dataLen);
                Buffer.BlockCopy(data, dataAt, o, 44, dataLen);
                notes.Add("sound header rewritten to the plain layout the game reads (" +
                          string.Join(", ", ids.Where(i => i != "data").Select(i => i.Trim())) + " -> fmt, data)");
            }
            for (int i = 0; i < 4; i++) o[i] = (byte)magic[i];
            return o;
        }

        public static bool IsText(byte[] data)
        {
            if (Utf16Bom(data)) return true;
            int n = Math.Min(data.Length, 4096);
            for (int i = 0; i < n; i++) if (data[i] == 0) return false;
            return true;
        }

        static bool HasBom(byte[] d) => d.Length >= 3 && d[0] == 0xEF && d[1] == 0xBB && d[2] == 0xBF;
        static bool Utf16Bom(byte[] d) => d.Length >= 2 && ((d[0] == 0xFF && d[1] == 0xFE) || (d[0] == 0xFE && d[1] == 0xFF));

        /// <summary>Text saved as UTF-16 (Notepad's "Unicode"), or null.</summary>
        static string Utf16(byte[] d)
        {
            if (!Utf16Bom(d)) return null;
            return d[0] == 0xFF ? Encoding.Unicode.GetString(d, 2, d.Length - 2) : Encoding.BigEndianUnicode.GetString(d, 2, d.Length - 2);
        }

        /// <summary>The characters of s the game's code page (949) has no place for: they would be
        /// written as '?'.</summary>
        public static List<string> Unmappable(string s)
        {
            var bad = new List<string>();
            if (CP.GetString(CP.GetBytes(s)) == s) return bad;
            for (int i = 0; i < s.Length; i++)
            {
                string ch = char.IsSurrogatePair(s, i) ? s.Substring(i++, 2) : s[i].ToString();
                try { StrictCP.GetBytes(ch); }
                catch (ArgumentException) { if (!bad.Contains(ch)) bad.Add(ch); }
            }
            return bad;
        }

        /// <summary>CP949 text -> UTF-8 with a BOM (so Notepad and editors pick the right code page).
        /// Plain ASCII, text that already is UTF-8 and bytes that are not clean CP949 stay as they are.</summary>
        public static byte[] TextToUtf8(byte[] data)
        {
            if (HasBom(data) || data.All(b => b < 0x80)) return data;
            try { StrictUtf8.GetString(data); return data; } catch (ArgumentException) { }
            string s;
            try { s = StrictCP.GetString(data); } catch (ArgumentException) { return data; }
            var body = Encoding.UTF8.GetBytes(s);
            var o = new byte[body.Length + 3];
            o[0] = 0xEF; o[1] = 0xBB; o[2] = 0xBF;
            Buffer.BlockCopy(body, 0, o, 3, body.Length);
            return o;
        }

        /// <summary>UTF-8 (with a BOM, or valid UTF-8 with Korean in it) -> CP949 text the game reads.</summary>
        public static byte[] TextToCp949(byte[] data)
        {
            var u16 = Utf16(data);
            if (u16 != null) return CP.GetBytes(u16);
            if (HasBom(data)) return CP.GetBytes(Encoding.UTF8.GetString(data, 3, data.Length - 3));
            if (data.All(b => b < 0x80)) return data;
            try { return CP.GetBytes(StrictUtf8.GetString(data)); } catch (ArgumentException) { return data; }
        }

        /// <summary>Text bytes as a string: UTF-8 when marked or valid, CP949 otherwise.</summary>
        public static string ReadText(byte[] data)
        {
            var u16 = Utf16(data);
            if (u16 != null) return u16;
            if (HasBom(data)) return Encoding.UTF8.GetString(data, 3, data.Length - 3);
            try { return StrictUtf8.GetString(data); } catch (ArgumentException) { return CP.GetString(data); }
        }

        static string CStr(byte[] b, int o, int max)
        {
            int n = 0;
            while (n < max && o + n < b.Length && b[o + n] != 0) n++;
            return CP.GetString(b, o, n);
        }

        static void PutStr(byte[] buf, int off, string s, int size)
        {
            var raw = CP.GetBytes(s ?? "");
            int n = Math.Min(raw.Length, size - 1);
            Buffer.BlockCopy(raw, 0, buf, off, n);
            for (int i = n; i < size; i++) buf[off + i] = 0;
        }

        /// <summary>lstrcpy: a name longer than its slot runs on into the next one (the next copy
        /// then overwrites the overflow, as in the game).</summary>
        static void StrCpy(byte[] buf, int off, string s)
        {
            var raw = CP.GetBytes(s);
            int n = Math.Min(raw.Length, buf.Length - off);
            Buffer.BlockCopy(raw, 0, buf, off, n);
            if (off + n < buf.Length) buf[off + n] = 0;
        }

        static int I32(byte[] b, int o) => BitConverter.ToInt32(b, o);
        static uint U32(byte[] b, int o) => BitConverter.ToUInt32(b, o);
        static void Put(byte[] b, int o, uint v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }
        static void Put(byte[] b, int o, int v) => Put(b, o, unchecked((uint)v));
        static void Put(byte[] b, int o, long v) => Put(b, o, unchecked((uint)v));
        static string Num(long v) => v.ToString(CultureInfo.InvariantCulture);

        // ntpath.splitext / basename / dirname as Python does them (both slashes are separators)
        static int LastSep(string p) => Math.Max(p.LastIndexOf('\\'), p.LastIndexOf('/'));
        static string BaseName(string p) => p.Substring(LastSep(p) + 1);
        static string DirName(string p) { int k = LastSep(p); return k < 0 ? "" : p.Substring(0, k); }
        static string SplitExtRoot(string p)
        {
            int sep = LastSep(p), dot = p.LastIndexOf('.');
            if (dot <= sep) return p;
            for (int i = sep + 1; i < dot; i++) if (p[i] != '.') return p.Substring(0, dot);
            return p;                                       // a name of only dots has no extension
        }

        // ------------------------------------------------------------------------- layout
        /// <summary>smMOTIONINFO: 120 bytes (2012 clients, 52 one-byte item codes) or 172 bytes
        /// (later clients, 52 two-byte item codes).</summary>
        public sealed class Layout
        {
            public readonly int Rec, ItemBytes, Job, Skill, MapPos, Repeat, Key, Frame, Motions;
            public readonly int Count, Ftk, Lfk, Link, TalkLink, TalkFile, Talk, TalkCount;
            public readonly int NpcRate, NpcRateCnt, TalkRate, TalkRateCnt, Size;
            public readonly bool Wide;

            public Layout(int rec)
            {
                Rec = rec;
                Wide = rec == 172;
                ItemBytes = Wide ? 104 : 52;
                int o = 40 + ItemBytes;
                Job = o; Skill = o + 4; MapPos = o + 12; Repeat = o + 16; Key = o + 20; Frame = o + 24;
                Motions = 0x18C;
                int tail = Motions + MOTION_MAX * rec;
                Count = tail; Ftk = tail + 4; Lfk = tail + 8;
                Link = tail + 12; TalkLink = tail + 76; TalkFile = tail + 140;
                Talk = tail + 204;
                TalkCount = Talk + TALK_MAX * rec;
                NpcRate = TalkCount + 4;
                NpcRateCnt = NpcRate + 4 * NPC_RATE_MAX;
                TalkRate = NpcRateCnt + 400;
                TalkRateCnt = TalkRate + 4 * TALK_MAX;
                Size = TalkRateCnt + 800;
            }
        }

        public static readonly Layout Narrow = new Layout(120), Wide = new Layout(172);
        public static Layout LayoutForSize(long size) => size == Narrow.Size ? Narrow : size == Wide.Size ? Wide : null;

        public sealed class Motion
        {
            public uint State;
            public long Start, End;
            public long[] Events = new long[4];       // ticks from the start frame (can be < 0)
            public int ItemCount;
            public List<long> Items = new List<long>();
            public uint Jobs;
            public bool JobsSet;                      // a *적용직업 line came (it overwrites an item overflow)
            public byte[] Skills = new byte[8];
            public int MapPos;
            public uint Repeat;
            public int Key;
            public int Piece;                         // MotionFrame: which *동작모음 (1-based; talk: 0-based)
            internal uint Kw1, Sf, Kw2, Ef;
        }

        public sealed class ModelInfo
        {
            public Layout Layout;
            public string ModelFile = "", MotionFile = "", SubFile = "";
            public List<string>[] Lod = { new List<string>(), new List<string>(), new List<string>() };
            public List<Motion> Motions = new List<Motion>();     // index = slot; slots below EXT are unused
            public string LinkFile = "", TalkLink = "", TalkFile = "";
            public List<Motion> Talk = new List<Motion>();
            public int[] NpcRate = new int[NPC_RATE_MAX];
            public int[] TalkRate = new int[TALK_MAX];
            public int[] NpcRateCnt = new int[100];
            public int[][] TalkRateCnt = { new int[100], new int[100] };
            public uint Ftk, Lfk;
            public string Folder = "";                            // folder stored in front of the file names
            public uint? Code;                                    // path checksum the frames were scrambled with
            public ModelInfo(Layout l) { Layout = l; }
        }

        static Motion ReadMotion(byte[] b, int o, Layout L)
        {
            var m = new Motion();
            m.State = U32(b, o);
            m.Kw1 = U32(b, o + 4); m.Sf = U32(b, o + 8); m.Kw2 = U32(b, o + 12); m.Ef = U32(b, o + 16);
            m.Start = m.Sf; m.End = m.Ef;
            for (int k = 0; k < 4; k++) m.Events[k] = I32(b, o + 20 + 4 * k);
            m.ItemCount = I32(b, o + 36);
            int n = Math.Max(0, Math.Min(m.ItemCount, 52));
            for (int k = 0; k < n; k++)
                m.Items.Add(L.Wide ? BitConverter.ToUInt16(b, o + 40 + 2 * k) : b[o + 40 + k]);
            m.Jobs = U32(b, o + L.Job);
            Buffer.BlockCopy(b, o + L.Skill, m.Skills, 0, 8);
            m.MapPos = I32(b, o + L.MapPos);
            m.Repeat = U32(b, o + L.Repeat);
            m.Key = b[o + L.Key];
            m.Piece = I32(b, o + L.Frame);
            return m;
        }

        /// <summary>MotionKeyWordDecode: (start, end) frames and the path checksum they were mixed with.</summary>
        static uint? Unscramble(Motion m)
        {
            uint kw1 = m.Kw1, sf = m.Sf, kw2 = m.Kw2, ef = m.Ef;
            uint? code = null;
            if (kw1 != 0 || sf != 0)
            {
                code = (kw1 & 0xff000000) | ((kw1 & 0x0000ff00) << 8) | (sf & 0x0000ff00) | ((sf & 0xff000000) >> 24);
                m.Start = ((sf & 0xff) << 24) | (sf & 0x00ff0000) | ((kw1 & 0x00ff0000) >> 8) | (kw1 & 0xff);
            }
            if (kw2 != 0 || ef != 0)
            {
                uint c2 = ((ef & 0x0000ff00) << 16) | ((ef & 0xff000000) >> 8) | (kw2 & 0x0000ff00) | ((kw2 & 0xff000000) >> 24);
                code = code ?? c2;
                m.End = ((kw2 & 0x00ff0000) << 8) | ((kw2 & 0xff) << 16) | ((ef & 0x00ff0000) >> 8) | (ef & 0xff);
            }
            return code;
        }

        public static ModelInfo ReadInx(string path) => ReadInx(File.ReadAllBytes(path));

        public static ModelInfo ReadInx(byte[] b)
        {
            var L = LayoutForSize(b.Length);
            if (L == null) throw new InvalidDataException("not an .inx (" + b.Length + " bytes)");
            var mi = new ModelInfo(L);
            mi.ModelFile = CStr(b, 0, 64); mi.MotionFile = CStr(b, 64, 64); mi.SubFile = CStr(b, 128, 64);
            for (int k = 0; k < 3; k++)
            {
                int o = 192 + 68 * k;
                // a name of 16 or more characters runs on into the next slot; the next name (if
                // any) overwrote the overflow, the last one keeps it
                int n = Math.Max(0, Math.Min(I32(b, o), 4));
                for (int j = 0; j < n; j++)
                {
                    int end = j < n - 1 ? o + 20 + 16 * j : o + 68;
                    mi.Lod[k].Add(CStr(b, o + 4 + 16 * j, end - (o + 4 + 16 * j)));
                }
            }
            foreach (var f in new[] { mi.ModelFile, mi.MotionFile })
                if (f.IndexOf('\\') >= 0) { mi.Folder = f.Substring(0, f.LastIndexOf('\\') + 1); break; }
            uint count = U32(b, L.Count);
            mi.Ftk = U32(b, L.Ftk); mi.Lfk = U32(b, L.Lfk);
            mi.LinkFile = CStr(b, L.Link, 64); mi.TalkLink = CStr(b, L.TalkLink, 64); mi.TalkFile = CStr(b, L.TalkFile, 64);
            uint talkCount = U32(b, L.TalkCount);
            for (int k = 0; k < Math.Min(count, (uint)MOTION_MAX); k++) mi.Motions.Add(ReadMotion(b, L.Motions + L.Rec * k, L));
            for (int k = 0; k < Math.Min(talkCount, (uint)TALK_MAX); k++) mi.Talk.Add(ReadMotion(b, L.Talk + L.Rec * k, L));
            bool scrambled = count > EXT && talkCount <= EXT;
            if (scrambled)
                for (int k = EXT; k < mi.Motions.Count; k++)
                {
                    var c = Unscramble(mi.Motions[k]);
                    mi.Code = mi.Code ?? c;
                }
            for (int k = 0; k < NPC_RATE_MAX; k++) mi.NpcRate[k] = I32(b, L.NpcRate + 4 * k);
            for (int k = 0; k < TALK_MAX; k++) mi.TalkRate[k] = I32(b, L.TalkRate + 4 * k);
            return mi;
        }

        // ------------------------------------------------------------------------- tables
        static List<string> items, skills;

        /// <summary>Item and skill names in the order the game indexes them (sinItem.cpp sItem[],
        /// fileread.cpp SkillDataCode[]; embedded from smdanim/data).</summary>
        static void SourceTables()
        {
            if (items != null) return;
            items = LoadTable("items.txt");
            skills = LoadTable("skills.txt");
        }

        static List<string> LoadTable(string name)
        {
            var asm = typeof(ClientFiles).GetTypeInfo().Assembly;
            using (var s = asm.GetManifestResourceStream("PTSmd.data." + name))
            {
                if (s == null) return new List<string>();
                using (var r = new StreamReader(s, Encoding.UTF8))
                    return r.ReadToEnd().Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).ToList();
            }
        }

        static List<string> JobNames(uint bits)
        {
            var o = JobBits.Where(j => (bits & j.bit) != 0).Select(j => j.name).ToList();
            uint all = 0;
            foreach (var j in JobBits) all |= j.bit;
            uint rest = bits & ~all;
            for (ulong k = 0x100; rest != 0 && k <= 0x80000000; k <<= 1)
                if ((rest & k) != 0) { o.Add("0x" + k.ToString("X")); rest &= ~(uint)k; }
            return o;
        }

        // ------------------------------------------------------------------------- .inx -> .ini
        /// <summary>A path stored with the .ini's folder in front -> as written in the .ini.</summary>
        static string RelName(string path, string folder)
        {
            string p = path.Replace('/', '\\');
            if (folder.Length > 0 && p.StartsWith(folder, StringComparison.OrdinalIgnoreCase)) return p.Substring(folder.Length);
            return p;
        }

        /// <summary>The text an .inx is compiled from.  relPath: the .inx's path from the game
        /// folder (char\monster\Tees\Tees.inx), to write file names the way the .ini writes them.</summary>
        public static string InxToIni(ModelInfo mi, string relPath = "")
        {
            SourceTables();
            string folder = mi.Folder.Length > 0 ? mi.Folder : DirName(relPath.Replace('/', '\\'));
            if (folder.Length > 0 && !folder.EndsWith("\\")) folder += "\\";
            string bn = BaseName(relPath);
            var o = new List<string> { "// " + (bn.Length > 0 ? bn : "model") + " - rebuilt from the compiled .inx by PristonTale - Rosetta Stone", "" };
            if (mi.ModelFile.Length > 0) o.Add("*모양파일\t" + RelName(mi.ModelFile, folder));
            string[] lodWords = { "*정밀모양", "*보통모양", "*저질모양" };
            for (int k = 0; k < 3; k++)
                if (mi.Lod[k].Count > 0) o.Add(lodWords[k] + "\t" + string.Join("\t", mi.Lod[k].Select(n => "\"" + n + "\"")));
            if (mi.SubFile.Length > 0) o.Add("*보조동작파일\t\"" + RelName(mi.SubFile, folder) + "\"");
            if (mi.LinkFile.Length > 0) o.Add("*파일연결\t" + RelName(mi.LinkFile, folder));
            if (mi.TalkLink.Length > 0) o.Add("*표정파일연결\t\"" + RelName(mi.TalkLink, folder) + "\"");
            if (mi.TalkFile.Length > 0) o.Add("*표정파일\t\"" + RelName(mi.TalkFile, folder) + "\"");
            if (mi.MotionFile.Length > 0) { o.Add(""); o.Add("*동작파일\t" + RelName(mi.MotionFile, folder)); }
            // Body motions belong to the n-th *동작모음 before them (MotionFrame = n), face motions
            // to the (n+1)-th (MotionFrame = n - 1): both lists are walked together, file by file.
            int last = 0;
            for (int i = EXT; i < mi.Motions.Count; i++) last = Math.Max(last, mi.Motions[i].Piece);
            for (int i = EXT; i < mi.Talk.Count; i++) last = Math.Max(last, mi.Talk[i].Piece + 1);
            bool single = last == 1 && mi.Talk.Count <= EXT;
            string motionName = BaseName(mi.MotionFile.Replace('\\', '/'));
            string motionBase = SplitExtRoot(motionName);
            if (motionBase.Length == 0) motionBase = "motion";
            var count = new Dictionary<string, int>();
            for (int piece = 0; piece <= last; piece++)
            {
                if (piece != 0)
                {
                    string name = single ? motionName : motionBase + "_" + piece.ToString("00", CultureInfo.InvariantCulture) + ".ASE";
                    o.Add("");
                    o.Add("*동작모음\t\"" + name + "\"" + (single ? "" : "\t// (the original name is not kept in the .inx)"));
                }
                for (int i = EXT; i < mi.Motions.Count; i++)
                    if (mi.Motions[i].Piece == piece) o.AddRange(BodyLines(mi, i, mi.Motions[i], count));
                for (int i = EXT; i < mi.Talk.Count; i++)
                    if (mi.Talk[i].Piece + 1 == piece) o.Add(FaceLine(mi, i, mi.Talk[i]));
            }
            o.Add(""); o.Add("*끝"); o.Add("");
            return string.Join("\r\n", o);
        }

        /// <summary>The token after the frames: a key letter, or 반복 (repeat); a word in front of a rate.</summary>
        static List<string> Flag(Motion m, int rate, uint[] autoRepeat)
        {
            string flag = null;
            if (m.Key != 0 && m.Key >= 32 && m.Key < 127 && m.Key != '(') flag = ((char)m.Key).ToString();
            else if (m.Repeat != 0 && Array.IndexOf(autoRepeat, m.State) < 0) flag = "반복";
            if (rate != 0 && flag == null) flag = "비율";              // any word: the next token is the rate
            var o = new List<string>();
            if (flag != null) o.Add(flag);
            if (rate != 0) o.Add("(" + rate.ToString(CultureInfo.InvariantCulture) + ")");
            return o;
        }

        /// <summary>A code as its name, or #code when the name would not lead back to this code (not
        /// in the table, or listed twice: the client's table is not quite the 2012 source's).</summary>
        static string ItemName(List<string> table, long c)
        {
            if (c >= 0 && c < table.Count && table[(int)c].Length > 0 && table.IndexOf(table[(int)c]) == c) return table[(int)c];
            return "#" + Num(c);
        }

        static string EventText(Motion m) => string.Join("", m.Events.Where(e => e != 0).Select(e => "\t" + Num(e / 160 + m.Start)));

        static List<string> BodyLines(ModelInfo mi, int i, Motion m, Dictionary<string, int> count)
        {
            string word;
            if (!StateWord.TryGetValue(m.State, out word)) word = "기타";
            int c;
            count.TryGetValue(word, out c);
            count[word] = ++c;
            string label = "*" + word + "동작" + (c == 1 ? "" : Num(c - 1));
            long end = m.State == 0x120 ? m.End + 8 : m.End;               // AddModelDecode takes 8 off a death
            var parts = new List<string> { label, Num(m.Start), Num(end) };
            parts.AddRange(m.Events.Where(e => e != 0).Select(e => Num(e / 160 + m.Start)));
            parts.AddRange(Flag(m, i < NPC_RATE_MAX ? mi.NpcRate[i] : 0, AutoRepeat));
            var o = new List<string> { string.Join("\t", parts) };
            if (m.ItemCount != 0 || m.Jobs != 0 || m.MapPos != 0)
            {
                if (m.ItemCount == 0) o.Add("*착용무기\t모두");
                else
                {
                    long none = mi.Layout.Wide ? 0xFFFF : 0xFF;
                    var names = m.Items.Select(x => x == none ? "없음" : ItemName(items, x)).ToList();
                    if (names.Count > 0)
                        for (int k = names.Count; k < m.ItemCount; k++) names.Add(names[names.Count - 1]);   // (overwritten in the file)
                    o.Add("*착용무기\t" + string.Join("\t", names));
                }
                if (m.Jobs != 0) o.Add("*적용직업\t" + string.Join("\t", JobNames(m.Jobs)));
                if (m.MapPos != 0) o.Add("*해당위치\t" + (m.MapPos == 1 ? "마을" : m.MapPos == 2 ? "필드" : "마을\t필드"));
            }
            if (m.State == 0x150 && m.Skills.Any(s => s != 0))
            {
                var low = skills.Select(n => n.ToLowerInvariant()).ToList();   // (the game compares skill names case-blind)
                o.Add("*적용기술\t" + string.Join("\t", m.Skills.Where(s => s != 0)
                    .Select(s => ItemName(low, s).StartsWith("#") ? "#" + Num(s) : skills[s])));
            }
            return o;
        }

        static string FaceLine(ModelInfo mi, int i, Motion m)
        {
            string word;
            if (!TalkWord.TryGetValue(m.State, out word)) word = "고유표정";
            var parts = new List<string> { "*" + word, Num(m.Start), Num(m.End) };
            parts.AddRange(m.Events.Where(e => e != 0).Select(e => Num(e / 160 + m.Start)));
            parts.AddRange(Flag(m, i < TALK_MAX ? mi.TalkRate[i] : 0, new uint[0]));
            return string.Join("\t", parts);
        }

        // ------------------------------------------------------------------------- .ini -> .inx
        static readonly string[] IniCommands =
        {
            "*동작파일", "*동작모음", "*모양파일", "*모양이름", "*파일연결", "*보조동작파일",
            "*정밀모양", "*보통모양", "*저질모양", "*XX걷는동작", "*XX서있기동작",
            "*착용무기", "*적용직업", "*해당위치", "*적용기술", "*표정파일연결", "*표정파일", "*표정모음",
        };
        // AddModelDecode's checks in its order (a later one wins)
        static readonly (string[] words, uint state, bool rep)[] StateChecks =
        {
            (new[] { "뛰는" }, 0x60, true), (new[] { "공격" }, 0x100, false), (new[] { "죽기" }, 0x120, false),
            (new[] { "죽는" }, 0x120, false), (new[] { "타격" }, 0x110, false), (new[] { "데미지" }, 0x110, false),
            (new[] { "막기" }, 0x110, false), (new[] { "가끔" }, 0x130, false), (new[] { "떨어" }, 0x80, false),
            (new[] { "작은착지" }, 0x170, false), (new[] { "큰착지" }, 0x180, false),
            (new[] { "*서있기", "*정지" }, 0x40, true), (new[] { "*걷는" }, 0x50, true), (new[] { "다시시작" }, 0x200, false),
            (new[] { "먹기" }, 0x140, false), (new[] { "기술" }, 0x150, false), (new[] { "울기", "워프" }, 0x210, false),
            (new[] { "만세" }, 0x220, false),
        };
        static readonly (string word, uint state)[] TalkChecks =
        {
            ("아표정", 0x400), ("이표정", 0x410), ("오표정", 0x420), ("눈깜빡표정", 0x430),
            ("무표정(작동않함)", 0), ("웃는표정", 0x440), ("화난표정", 0x450), ("슬픈표정", 0x460),
            ("놀란표정", 0x470), ("고유표정", 0x480), ("특별표정", 0x490),
        };

        /// <summary>GetWord: whitespace-separated (space / tab), stopping at the line end.</summary>
        static string[] Words(string line) => line.Replace('\r', ' ').Replace('\n', ' ').Replace('\t', ' ').Split(' ');
        static List<string> Tokens(string line) => Words(line).Where(w => w.Length > 0).ToList();
        static bool IsDigit(char c) => c >= '0' && c <= '9';
        static bool IsHashNumber(string t) => t.Length > 1 && t[0] == '#' && t.Skip(1).All(IsDigit);
        static long ParseLong(string digits)
        {
            long v = 0;
            foreach (char ch in digits) v = unchecked(v * 10 + (ch - '0'));
            return v;
        }

        /// <summary>The engine's GetString after a quote: everything up to the closing quote.</summary>
        static string StringArg(string rest)
        {
            rest = rest.TrimStart(' ', '\t');
            if (rest.StartsWith("\""))
            {
                int end = rest.IndexOf('"', 1);
                return end > 0 ? rest.Substring(1, end - 1) : rest.Substring(1).TrimEnd('\r', '\n');
            }
            var t = Tokens(rest);
            return t.Count > 0 ? t[0] : "";
        }

        /// <summary>SetIniMotionInfo: start end [events...] [flag] [(rate)] -> rate or null.</summary>
        static int? SetMotion(Motion m, List<string> args)
        {
            long NumOf(string s)
            {
                int k = 0;
                bool neg = s.StartsWith("-");
                if (neg) k = 1;
                int st = k;
                while (k < s.Length && IsDigit(s[k])) k++;
                if (k == st) return 0;
                long v = ParseLong(s.Substring(st, k - st));
                return neg ? -v : v;
            }
            var a = args.Concat(Enumerable.Repeat("", 8)).ToList();
            int p = 0;
            m.Start = NumOf(a[p++]);
            m.End = NumOf(a[p++]);
            m.Events = new long[4];
            int n = 0;
            string tok = a[p++];
            while (tok.Length > 0 && IsDigit(tok[0]) && n < 4)
            {
                m.Events[n] = (NumOf(tok) - m.Start) * 160;
                n++;
                tok = p < a.Count ? a[p++] : "";
            }
            if (tok == "반복") m.Repeat = 1;
            if (tok.Length > 0 && tok[0] != '(' && tok[0] >= ' ' && tok[0] <= '\x7f') m.Key = tok[0];
            int? rate = null;
            tok = p < a.Count ? a[p++] : "";
            if (tok.Length > 2 && tok.Length < 6 && tok[0] == '(' && tok[tok.Length - 1] == ')')
            {
                string inner = tok.Substring(1, tok.Length - 2);
                rate = Math.Min(inner.Length > 0 && inner.All(IsDigit) ? int.Parse(inner, CultureInfo.InvariantCulture) : 0, 100);
            }
            return rate;
        }

        /// <summary>AddModelDecode + the keyword encoding: .ini / .inf / .in text -> .inx bytes.
        /// relInx: the .inx path from the game folder (its checksum is mixed into the file);
        /// folder: how the game spelled the folder it puts in front of file names (default:
        /// relInx's; only the case can differ, which the game ignores); code: the path checksum
        /// to use instead of relInx's (an .inx compiled somewhere else and copied keeps the old one).</summary>
        public static byte[] CompileIni(string text, string relInx, int layout = 172, string folder = null, uint? code = null,
                                        Action<string> warn = null)
        {
            SourceTables();
            int lineNo = 0;
            void Warn(string msg) => warn?.Invoke("line " + lineNo + ": " + msg);
            // (what follows // on a line is a comment for the reader; the game reads it as more names)
            IEnumerable<string> Named(List<string> a) => a.TakeWhile(t => !t.StartsWith("//"));
            var itemIndex = new Dictionary<string, int>();
            for (int i = 0; i < items.Count; i++) if (!itemIndex.ContainsKey(items[i])) itemIndex[items[i]] = i;
            var skillIndex = new Dictionary<string, int>();
            for (int i = 0; i < skills.Count; i++) { string k = skills[i].ToLowerInvariant(); if (!skillIndex.ContainsKey(k)) skillIndex[k] = i; }
            var L = new Layout(layout);
            relInx = relInx.Replace('/', '\\');
            if (folder == null)
            {
                folder = DirName(relInx);
                folder = folder.Length > 0 ? folder + "\\" : "";
            }
            var mi = new ModelInfo(L);
            for (int k = 0; k < EXT; k++) { mi.Motions.Add(new Motion()); mi.Talk.Add(new Motion()); }
            int pieces = 0, last = 0;
            foreach (string line0 in text.Replace("\r\n", "\n").Split('\n'))
            {
                lineNo++;
                string line = line0.Length > 511 ? line0.Substring(0, 511) : line0;
                string head = Words(line).FirstOrDefault(w => w.Length > 0) ?? "";
                string rest = head.Length > 0 ? line.Substring(line.IndexOf(head, StringComparison.Ordinal) + head.Length) : "";
                var args = Tokens(rest);
                int cmd = Array.IndexOf(IniCommands, head);
                if (cmd < 0)
                {
                    if (head.StartsWith("*") && head.Contains("동작"))
                    {
                        if (args.Any(t => t.StartsWith("//")))
                            Warn(head + ": the game reads text after the frames as a key letter ('/' here) - put comments on a line of their own");
                        if (mi.Motions.Count < MOTION_MAX)
                        {
                            var m = new Motion();
                            var rate = SetMotion(m, args);
                            if (rate != null && mi.Motions.Count < NPC_RATE_MAX) mi.NpcRate[mi.Motions.Count] = rate.Value;
                            m.Piece = pieces;
                            m.State = 1;
                            foreach (var chk in StateChecks)
                                if (chk.words.Any(w => head.Contains(w)))
                                {
                                    m.State = chk.state;
                                    if (chk.rep) m.Repeat = 1;
                                }
                            if (m.State == 0x150) m.Skills[0] = 0;
                            if (m.State == 0x120) m.End = (m.End - 8) & 0xFFFFFFFF;
                            last = mi.Motions.Count;
                            mi.Motions.Add(m);
                        }
                    }
                    else if (head.StartsWith("*") && head.Contains("표정") && pieces != 0)
                    {
                        if (mi.Talk.Count < TALK_MAX)
                        {
                            var m = new Motion();
                            var rate = SetMotion(m, args);
                            if (rate != null) mi.TalkRate[mi.Talk.Count] = rate.Value;
                            m.Piece = pieces - 1;
                            m.State = 1;
                            foreach (var chk in TalkChecks)
                                if (head.Contains(chk.word)) { m.State = chk.state; break; }
                            mi.Talk.Add(m);
                        }
                    }
                    else if (head.StartsWith("*") && head.Contains("표정"))
                        Warn(head + " comes before any *동작모음 / *표정모음 - the game skips it");
                    else if (head.StartsWith("*") && head != "*끝")
                        Warn(head + " is not a model info command - the game skips the line");
                    continue;
                }
                switch (cmd)
                {
                    case 0: mi.MotionFile = folder + StringArg(rest); break;
                    case 1: case 17: pieces++; break;
                    case 2: mi.ModelFile = folder + (args.Count > 0 ? args[0] : ""); break;
                    case 4: mi.LinkFile = folder + (args.Count > 0 ? args[0] : ""); break;
                    case 5: mi.SubFile = folder + StringArg(rest); break;
                    case 6: case 7: case 8:
                    {
                        var grp = mi.Lod[cmd - 6];
                        string r = rest;
                        for (int k = 0; k < 4; k++)
                        {
                            if (Tokens(r).Count == 0) break;
                            string s = r.TrimStart(' ', '\t');
                            string name;
                            if (s.StartsWith("\""))
                            {
                                int end = s.IndexOf('"', 1);
                                if (end < 0) { name = s.Length >= 2 ? s.Substring(1, s.Length - 2) : ""; r = s; }
                                else { name = s.Substring(1, end - 1); r = s.Substring(end + 1); }
                            }
                            else
                            {
                                name = Tokens(s)[0];
                                r = s.Substring(name.Length);
                            }
                            if (grp.Count < 4) grp.Add(name);
                        }
                        break;
                    }
                    case 11:
                    {
                        var m = mi.Motions[last];
                        foreach (var tok in args)
                        {
                            if (tok == "모두") { m.ItemCount = 0; m.Items.Clear(); break; }
                            int idx;
                            if (tok == "없음") m.Items.Add(L.Wide ? 0xFFFF : 0xFF);
                            else if (itemIndex.TryGetValue(tok, out idx)) m.Items.Add(idx);
                            else if (IsHashNumber(tok)) m.Items.Add(ParseLong(tok.Substring(1)));   // an item code by number (our own form)
                            m.ItemCount = m.Items.Count;
                        }
                        foreach (var tok in Named(args).TakeWhile(t => t != "모두"))
                            if (tok != "없음" && !itemIndex.ContainsKey(tok) && !IsHashNumber(tok))
                                Warn("*착용무기: no item is called '" + tok + "' - the game leaves it out");
                        break;
                    }
                    case 12:
                    {
                        var m = mi.Motions[last];
                        m.Jobs = 0;
                        m.JobsSet = true;
                        foreach (var tok in args)
                            foreach (var j in JobBits)
                                if (string.Equals(tok.ToLowerInvariant(), j.name.ToLowerInvariant(), StringComparison.Ordinal)) { m.Jobs |= j.bit; break; }
                        foreach (var tok in Named(args))
                            if (!JobBits.Any(j => string.Equals(tok, j.name, StringComparison.OrdinalIgnoreCase)))
                                Warn("*적용직업: no class is called '" + tok + "' (" + string.Join(", ", JobBits.Select(j => j.name)) + ") - the game leaves it out");
                        break;
                    }
                    case 13:
                    {
                        var m = mi.Motions[last];
                        int v = 0;
                        foreach (var tok in Named(args))
                            if (tok != "마을" && tok != "필드") Warn("*해당위치: '" + tok + "' is neither 마을 (town) nor 필드 (field)");
                        foreach (var tok in args.Take(2)) v |= tok == "마을" ? 1 : tok == "필드" ? 2 : 0;
                        if (v == 0 || m.State == 0x150) v = 3;
                        m.MapPos = v;
                        break;
                    }
                    case 14:
                    {
                        var m = mi.Motions[last];
                        if (m.State == 0x150)
                        {
                            int k = 0, idx;
                            foreach (var tok in args)
                            {
                                if (k >= 7) break;
                                if (skillIndex.TryGetValue(tok.ToLowerInvariant(), out idx)) m.Skills[k++] = (byte)idx;
                                else if (IsHashNumber(tok)) m.Skills[k++] = (byte)(ParseLong(tok.Substring(1)) & 0xFF);   // a skill by number
                            }
                            m.Skills[k] = 0;
                            foreach (var tok in Named(args))
                                if (!skillIndex.ContainsKey(tok.ToLowerInvariant()) && !IsHashNumber(tok))
                                    Warn("*적용기술: no skill is called '" + tok + "' - the game leaves it out");
                        }
                        else Warn("*적용기술 belongs to a skill motion (*기술동작...) - the game ignores it here");
                        break;
                    }
                    case 15: mi.TalkLink = folder + StringArg(rest); break;
                    case 16: mi.TalkFile = folder + StringArg(rest); break;
                }
            }
            BalanceRates(mi);
            return WriteInx(mi, relInx, code);
        }

        /// <summary>The NpcMotionRate fix-up of AddModelDecode: the largest share absorbs the
        /// difference to 100, then NpcMotionRateCnt lists each motion index rate times.</summary>
        static void BalanceRates(ModelInfo mi)
        {
            mi.NpcRateCnt = new int[100];
            if (mi.NpcRate[EXT] != 0)
            {
                int hi = Math.Min(mi.Motions.Count, NPC_RATE_MAX);
                int best = 0, pos = 0, tot = 0;
                for (int i = EXT; i < hi; i++)
                {
                    if (best < mi.NpcRate[i]) { best = mi.NpcRate[i]; pos = i; }
                    tot += mi.NpcRate[i];
                }
                if (tot > 100)
                {
                    best -= tot - 100;
                    if (best <= 0) mi.NpcRate[EXT] = 0;
                    else mi.NpcRate[pos] = best;
                }
                else if (tot < 100) mi.NpcRate[pos] = best + 100 - tot;
                if (mi.NpcRate[EXT] != 0)
                {
                    int k = 0;
                    for (int i = EXT; i < hi; i++)
                        for (int r = 0; r < mi.NpcRate[i]; r++) { if (k < 100) mi.NpcRateCnt[k] = i; k++; }
                }
            }
            // face motions: the same per face-motion file (MotionFrame 0 / 1), on a copy of the rates
            mi.TalkRateCnt = new[] { new int[100], new int[100] };
            if (mi.TalkRate[EXT] != 0)
                for (int f = 0; f < 2; f++)
                {
                    var idx = Enumerable.Range(EXT, Math.Max(0, mi.Talk.Count - EXT)).Where(i => mi.Talk[i].Piece == f).ToList();
                    var rate = idx.ToDictionary(i => i, i => i < TALK_MAX ? mi.TalkRate[i] : 0);
                    int best = 0, tot = 0;
                    int? pos = null;
                    foreach (int i in idx)
                    {
                        if (best < rate[i]) { best = rate[i]; pos = i; }
                        tot += rate[i];
                    }
                    if (tot > 100)
                    {
                        best -= tot - 100;
                        if (best <= 0) mi.TalkRate[EXT] = 0;
                        else if (pos != null) rate[pos.Value] = best;
                    }
                    else if (tot < 100 && pos != null) rate[pos.Value] = best + 100 - tot;
                    if (mi.TalkRate[EXT] != 0)
                    {
                        int k = 0;
                        foreach (int i in idx)
                            for (int r = 0; r < rate[i]; r++) { if (k < 100) mi.TalkRateCnt[f][k] = i; k++; }
                    }
                }
        }

        static void WriteMotion(byte[] buf, int o, Motion m, Layout L, uint? code)
        {
            uint sf = unchecked((uint)m.Start), ef = unchecked((uint)m.End), kw1 = 0, kw2 = 0;
            if (code != null)
            {
                uint c = code.Value;
                if (sf != 0)
                {
                    kw1 = (c & 0xff000000) | ((sf & 0x0000ff00) << 8) | ((c & 0x00ff0000) >> 8) | (sf & 0xff);
                    sf = ((c & 0xff) << 24) | (sf & 0x00ff0000) | (c & 0x0000ff00) | ((sf & 0xff000000) >> 24);
                }
                if (ef != 0)
                {
                    kw2 = ((c & 0xff) << 24) | ((ef & 0xff000000) >> 8) | (c & 0x0000ff00) | ((ef & 0x00ff0000) >> 16);
                    ef = ((c & 0x00ff0000) << 8) | ((ef & 0x0000ff00) << 8) | ((c & 0xff000000) >> 16) | (ef & 0xff);
                }
            }
            Put(buf, o, m.State); Put(buf, o + 4, kw1); Put(buf, o + 8, sf); Put(buf, o + 12, kw2); Put(buf, o + 16, ef);
            for (int k = 0; k < 4; k++) Put(buf, o + 20 + 4 * k, m.Events[k]);
            Put(buf, o + 36, m.ItemCount);
            int n = Math.Min(m.Items.Count, 60);
            for (int k = 0; k < n; k++)
            {
                if (L.Wide) { buf[o + 40 + 2 * k] = (byte)m.Items[k]; buf[o + 41 + 2 * k] = (byte)(m.Items[k] >> 8); }
                else buf[o + 40 + k] = (byte)m.Items[k];
            }
            if (n <= 52 || m.JobsSet) Put(buf, o + L.Job, m.Jobs);
            Buffer.BlockCopy(m.Skills, 0, buf, o + L.Skill, 8);
            Put(buf, o + L.MapPos, m.MapPos);
            Put(buf, o + L.Repeat, m.Repeat);
            buf[o + L.Key] = (byte)m.Key;
            Put(buf, o + L.Frame, m.Piece);
        }

        static byte[] WriteInx(ModelInfo mi, string relInx, uint? code)
        {
            var L = mi.Layout;
            var buf = new byte[L.Size];
            PutStr(buf, 0, mi.ModelFile, 64);
            PutStr(buf, 64, mi.MotionFile, 64);
            PutStr(buf, 128, mi.SubFile, 64);
            for (int k = 0; k < 3; k++)
            {
                int o = 192 + 68 * k;
                Put(buf, o, mi.Lod[k].Count);
                for (int j = 0; j < Math.Min(4, mi.Lod[k].Count); j++) StrCpy(buf, o + 4 + 16 * j, mi.Lod[k][j]);
            }
            uint cd = code ?? SpeedSum(relInx);
            bool scramble = mi.Motions.Count > EXT && mi.Talk.Count <= EXT;
            for (int k = EXT; k < Math.Min(mi.Motions.Count, MOTION_MAX); k++)
                WriteMotion(buf, L.Motions + L.Rec * k, mi.Motions[k], L, scramble ? cd : (uint?)null);
            Put(buf, L.Count, mi.Motions.Count);
            // ModelKeyWordEncode
            uint ftk, lfk;
            if (mi.LinkFile.Length > 0)
            {
                uint link = SpeedSum(SplitExtRoot(mi.LinkFile) + ".inx");
                ftk = ((cd & 0x00ff0000) << 8) | ((link & 0xff) << 16) | ((cd & 0xff) << 8) | ((link & 0xff000000) >> 24);
                lfk = (cd & 0xff000000) | ((link & 0x0000ff00) << 8) | (cd & 0x0000ff00) | ((link & 0x00ff0000) >> 16);
            }
            else
            {
                ftk = ((cd & 0x0000ff00) << 16) | ((cd & 0xff000000) >> 8) | ((cd & 0xff) << 8) | ((cd & 0x00ff0000) >> 16);
                lfk = 0;
            }
            Put(buf, L.Ftk, ftk); Put(buf, L.Lfk, lfk);
            PutStr(buf, L.Link, mi.LinkFile, 64);
            PutStr(buf, L.TalkLink, mi.TalkLink, 64);
            PutStr(buf, L.TalkFile, mi.TalkFile, 64);
            for (int k = EXT; k < Math.Min(mi.Talk.Count, TALK_MAX); k++)
                WriteMotion(buf, L.Talk + L.Rec * k, mi.Talk[k], L, null);
            Put(buf, L.TalkCount, mi.Talk.Count);
            for (int k = 0; k < NPC_RATE_MAX; k++) Put(buf, L.NpcRate + 4 * k, mi.NpcRate[k]);
            for (int k = 0; k < 100; k++) Put(buf, L.NpcRateCnt + 4 * k, mi.NpcRateCnt[k]);
            for (int k = 0; k < TALK_MAX; k++) Put(buf, L.TalkRate + 4 * k, mi.TalkRate[k]);
            for (int k = 0; k < 200; k++) Put(buf, L.TalkRateCnt + 4 * k, mi.TalkRateCnt[k / 100][k % 100]);
            return buf;
        }

        // ------------------------------------------------------------------------- naming
        /// <summary>The text file an .inx is compiled from: player models (char\tmABCD) use .inf,
        /// their class motion files (M1Bip ...) .in, monsters and NPCs .ini.</summary>
        public static string SourceExtension(string relInx)
        {
            string r = relInx.Replace('/', '\\').ToLowerInvariant();
            string stem = SplitExtRoot(BaseName(r));
            if (r.Contains("\\tmabcd\\") || r.StartsWith("tmabcd\\"))
            {
                if (stem.Length > 4 && stem[0] == 'm' && stem.EndsWith("bip") && stem.Substring(1, stem.Length - 4).All(IsDigit)) return ".in";
                return ".inf";
            }
            return ".ini";
        }
    }
}
