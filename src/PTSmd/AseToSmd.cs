// ASE -> SMD: the game's own builder, ported line by line from the 2012 source so that the
// developers' .ase files give the .smd the game built from them:
//   smRead3d.cpp   smSTAGE3D_ReadASE, ReadASE_LIGHTMAP_MATERIAL, smSTAGE3D_ReadASE_GEOMOBJECT,
//                  smReadASE_LIGHTOBJECT, smSTAGE3D_GetASE_Info
//   smStage3d.cpp  AddVertex / AddFace / AddTexLink / SetVertexShade / AddVertexLightRound /
//                  SetupPolyAreas / SaveFile
//   smTexture.cpp  smMATERIAL_GROUP::AddMaterial / SaveFile, smTEXTURE::Add
// The game reads the .ase as bytes, line by line (fgets of 254 characters), and keeps its quirks:
// materials are de-duplicated by a byte checksum, a vertex colour is averaged together with a white
// one, an untextured object gets material 0, and so on.  They are kept here too.
//
// Files written by our own tools (the decoder and both exporters, told apart by their *COMMENT)
// carry things the game's reader does not know, so for those:
//   * vertex colours are the finished lighting of the shipped map (the decoder writes sDef_Color/255):
//     they are used as they are instead of being shaded again; objects without colours are shaded
//     the game's way
//   * texture layer k of a material takes its UVs from *MESH_MAPPINGCHANNEL k+1 when the object has it
//   * a light's range is *LIGHT_ATTNEND x 256 (the decoder writes Range/256), colours are rounded
//   * a *MESH_MTLID past the last sub-material wraps around (as in 3ds Max), and an object without
//     UVs keeps its own material
//
// Map coordinates: x = Max X * 256, y = Max Z * 256, z = Max Y * 256 (whole numbers, truncated).

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace PTSmd
{
    public class EncodeOptions
    {
        /// <summary>The game folder the textures are named with, e.g. "field\\ricarten\\" (the game uses
        /// the folder it loads the .ase from).</summary>
        public string DataDir = "";
        /// <summary>The client's map lighting: 300 / 130 / (0, -372, -93) for most maps; village-1,
        /// forever-fall-03/04, pilai, ice_ura and the login stage were built with 300 / 160 / (256, -256, 128).</summary>
        public int Contrast = 300, Bright = 130, LightX = 0, LightY = -372, LightZ = -93;
        /// <summary>null: decide from the file's *COMMENT (written by our decoder or exporters).</summary>
        public bool? OwnFile;
        /// <summary>Float maths in single precision (the FPU mode Direct3D sets; some shipped maps were
        /// built that way, others in double - it changes UVs and normals by one float step at most).</summary>
        public bool SinglePrecision;
        /// <summary>Area lists with 32-bit face numbers, as current clients have them (and read); false =
        /// the 16-bit lists of the 2012 client.</summary>
        public bool WideAreas = true;
        /// <summary>Models: vertex normals in the older form (without the position added, object header
        /// without the 0x80000000 flag) - some shipped models have it; the 2012 engine reads both.</summary>
        public bool OldNormals;
    }

    public class EncodeResult
    {
        public string Kind = "";
        public bool OwnFile;
        public int Objects, Skipped, Vertices, Faces, TexLinks, Materials, Lights, DynLights, Textures;
        public int BakedObjects, ShadedObjects;
        public int BadFaces;                    // faces pointing past their object's vertices (set to its first one)
        public bool TooManyVertices, TooManyFaces;
        /// <summary>The most faces within reach of one spot (AseToSmd.CrowdedLimit), and where (3ds Max units).</summary>
        public int CrowdedFaces;
        public double CrowdedX, CrowdedY;
    }

    public static partial class AseToSmd
    {
        // ------------------------------------------------------------------ text, the way the game reads it
        internal sealed class Lines
        {
            readonly List<string> l = new List<string>();
            int pos;
            public Lines(string path)
            {
                string t = File.ReadAllText(path, Bin.Latin1);          // bytes 1:1 (names stay CP949 bytes)
                var sb = new StringBuilder(256);
                int i = 0, n = t.Length;
                while (i < n)
                {
                    sb.Clear();
                    while (i < n && sb.Length < 254)                   // fgets( line, 255, fp ), text mode
                    {
                        char c = t[i++];
                        if (c == '\r' && i < n && t[i] == '\n') continue;
                        sb.Append(c);
                        if (c == '\n') break;
                    }
                    l.Add(sb.ToString());
                }
            }
            public bool Next(out string s)
            {
                if (pos >= l.Count) { s = null; return false; }
                s = l[pos++];
                return true;
            }
            public string Need()
            {
                if (pos >= l.Count) throw new SmdException("the .ase file ends inside a block");
                return l[pos++];
            }
            public void Rewind() { pos = 0; }
            public IEnumerable<string> All => l;
        }

        static int GetWord(string s, int p, out string w)
        {
            int n = s.Length;
            while (p < n && (s[p] == ' ' || s[p] == '\t' || s[p] == ':')) p++;
            int st = p;
            while (p < n && s[p] != ' ' && s[p] != '\t' && s[p] != ':' && s[p] != '\n' && s[p] != '\r' && s[p] != '\0') p++;
            w = s.Substring(st, p - st);
            return p;
        }

        static int GetString(string s, int p, out string w)
        {
            int n = s.Length;
            while (p < n && s[p] != '"') p++;
            p++;
            if (p >= n) { w = ""; return n; }
            int st = p;
            while (p < n && s[p] != '"' && s[p] != '\0' && s[p] != '\r' && s[p] != '\n') p++;
            w = s.Substring(st, p - st);
            return p + 1;
        }

        static string Word(string s, ref int p) { p = GetWord(s, p, out string w); return w; }
        static string Str(string s, ref int p) { p = GetString(s, p, out string w); return w; }

        internal static double Atof(string s)
        {
            int i = 0, n = s.Length;
            while (i < n && (s[i] == ' ' || s[i] == '\t')) i++;
            int st = i;
            if (i < n && (s[i] == '+' || s[i] == '-')) i++;
            int d0 = i, digits = 0;
            while (i < n && s[i] >= '0' && s[i] <= '9') { i++; digits++; }
            if (i < n && s[i] == '.') { i++; while (i < n && s[i] >= '0' && s[i] <= '9') { i++; digits++; } }
            if (digits == 0) return 0;
            if (i < n && (s[i] == 'e' || s[i] == 'E'))
            {
                int j = i + 1;
                if (j < n && (s[j] == '+' || s[j] == '-')) j++;
                int e0 = j;
                while (j < n && s[j] >= '0' && s[j] <= '9') j++;
                if (j > e0) i = j;
            }
            double.TryParse(s.Substring(st, i - st), NumberStyles.Float, CultureInfo.InvariantCulture, out double v);
            return v;
        }

        internal static int Atoi(string s)
        {
            int i = 0, n = s.Length;
            while (i < n && (s[i] == ' ' || s[i] == '\t')) i++;
            bool neg = false;
            if (i < n && (s[i] == '+' || s[i] == '-')) { neg = s[i] == '-'; i++; }
            long v = 0;
            while (i < n && s[i] >= '0' && s[i] <= '9') { v = v * 10 + (s[i] - '0'); if (v > int.MaxValue) break; i++; }
            return (int)(neg ? -v : v);
        }

        static bool Has(string s, string sub) => s.IndexOf(sub, StringComparison.Ordinal) >= 0;

        // _stricmp: ASCII letters only (the names are CP949 bytes)
        internal sealed class AsciiNoCase : IEqualityComparer<string>
        {
            public static readonly AsciiNoCase I = new AsciiNoCase();
            static char Lo(char c) => c >= 'A' && c <= 'Z' ? (char)(c + 32) : c;
            public bool Equals(string a, string b)
            {
                if (a.Length != b.Length) return false;
                for (int i = 0; i < a.Length; i++) if (Lo(a[i]) != Lo(b[i])) return false;
                return true;
            }
            public int GetHashCode(string s)
            {
                int h = 17;
                foreach (char c in s) h = h * 31 + Lo(c);
                return h;
            }
        }

        // ------------------------------------------------------------------ ASE_MATERIAL aseMaterial[MATRIAL_MAX*2], as bytes
        // (the game de-duplicates materials by a checksum of these bytes and copies blocks of them around)
        internal sealed class AseMats
        {
            public const int Size = 852, Count = 10000;
            public const int Regist = 0, RegistNum = 4, TextureCounter = 8, Diffuse = 16, Transparency = 28,
                SelfIllum = 32, TwoSide = 36, ScriptState = 40, BITMAP = 44, BitmapStateState = 556,
                BitmapFormState = 588, MAP_OPACITY = 620, U_OFFSET = 684, V_OFFSET = 716, U_TILING = 748,
                V_TILING = 780, ANGLE = 812, SubPoint = 844, BlendType = 848;
            public readonly byte[] B = new byte[Size * Count];
            static int At(int m, int off) => m * Size + off;
            bool Ok(long a, int n) => a >= 0 && a + n <= B.Length;
            public int I(int m, int off) { long a = At(m, off); return Ok(a, 4) ? BitConverter.ToInt32(B, (int)a) : 0; }
            public void SetI(int m, int off, int v)
            {
                long a = At(m, off);
                if (!Ok(a, 4)) return;
                B[a] = (byte)v; B[a + 1] = (byte)(v >> 8); B[a + 2] = (byte)(v >> 16); B[a + 3] = (byte)(v >> 24);
            }
            public float F(int m, int off) { long a = At(m, off); return Ok(a, 4) ? BitConverter.ToSingle(B, (int)a) : 0f; }
            public void SetF(int m, int off, float v) => SetI(m, off, BitConverter.ToInt32(BitConverter.GetBytes(v), 0));
            public string S(int m, int off)
            {
                long a = At(m, off);
                if (!Ok(a, 1)) return "";
                int e = (int)a;
                while (e < B.Length && B[e] != 0) e++;
                return Bin.Latin1.GetString(B, (int)a, e - (int)a);
            }
            public void SetS(int m, int off, string s)                 // lstrcpy (runs over into what follows)
            {
                long a = At(m, off);
                for (int i = 0; i <= s.Length; i++, a++)
                    if (Ok(a, 1)) B[a] = i < s.Length ? (byte)s[i] : (byte)0;
            }
            public void Copy(int dstM, int srcM, int bytes)               // CopyMemory
            {
                long d = At(dstM, 0), s = At(srcM, 0);
                if (bytes <= 0 || !Ok(d, bytes) || !Ok(s, bytes)) return;
                Buffer.BlockCopy(B, (int)s, B, (int)d, bytes);
            }
            public byte[] Get(int m) { var r = new byte[Size]; Buffer.BlockCopy(B, m * Size, r, 0, Size); return r; }
            public uint Sum(int m)
            {
                uint sum = 0;
                int b0 = m * Size;
                for (int n = 0; n < Size; n++) sum += (uint)B[b0 + n] * (uint)(n + 5) * 10u;
                return sum;
            }
        }

        // ------------------------------------------------------------------ smMATERIAL + smTEXTURE
        internal sealed class Mat
        {
            public readonly byte[] B = new byte[Smd.MaterialSize];
            public readonly int[] Tex = { -1, -1, -1, -1, -1, -1, -1, -1 };
            public readonly int[] Anim = new int[32];
            public Mat() { for (int i = 0; i < 32; i++) Anim[i] = -1; }
            public int I(int o) => BitConverter.ToInt32(B, o);
            public void SetI(int o, int v) { B[o] = (byte)v; B[o + 1] = (byte)(v >> 8); B[o + 2] = (byte)(v >> 16); B[o + 3] = (byte)(v >> 24); }
            public float F(int o) => BitConverter.ToSingle(B, o);
            public void SetF(int o, float v) => SetI(o, BitConverter.ToInt32(BitConverter.GetBytes(v), 0));
            public const int InUse = 0, TextureCounter = 4, smTexture = 8, TextureStageState = 40, TextureFormState = 72,
                ReformTexture = 104, MapOpacity = 108, TextureType = 112, BlendType = 116, Shade = 120, TwoSide = 124,
                Diffuse = 132, Transparency = 144, SelfIllum = 148, UseState = 164, MeshState = 168,
                WindMeshBottom = 176 - 4, smAnimTexture = 176, AnimTexCounter = 304, FrameMask = 308,
                Shift_FrameSpeed = 312, AnimationFrame = 316;
        }

        internal sealed class TexTable
        {
            public readonly List<(string name, string nameA)> List = new List<(string, string)>();
            readonly Dictionary<string, int> find = new Dictionary<string, int>(AsciiNoCase.I);
            public int Add(string name, string nameA = null)          // smTEXTURE::Add: the first one with the name wins
            {
                if (find.TryGetValue(name, out int i)) return i;
                List.Add((name, nameA ?? ""));
                return find[name] = List.Count - 1;
            }
        }

        // script keywords in material names (smRead3d.cpp)
        static readonly (string s, int code)[] MatScripts =
        {
            ("wind:", 0x1), ("anim2:", 0x2), ("anim4:", 0x4), ("anim8:", 0x8), ("anim16:", 0x10),
            ("wind_z1:", 0x20), ("wind_z2:", 0x40), ("wind_x1:", 0x80), ("wind_x2:", 0x100),
            ("water:", 0x200), ("wall:", 0x400), ("pass:", 0x800), ("notpass:", 0x1000),
            ("render_latter:", 0x2000), ("BLINK_COLOR:", 0x4000), ("ice:", 0x8000), ("orgwater:", 0x10000),
        };
        static readonly (string s, int code)[] MatBlends =
            { ("BLEND_ALPHA:", 1), ("BLEND_COLOR:", 2), ("BLEND_ADDCOLOR:", 5), ("BLEND_SHADOW:", 3), ("BLEND_LAMP:", 4) };
        static readonly string[] StageScripts = { "BS_MODULATE:", "BS_MODULATE2X:", "BS_MODULATE4X:", "BS_ADD:", "BS_ADDSIGNED:", "BS_ADDSIGNED2X:", "BS_SUBTRACT:" };
        static readonly int[] StageCodes = { 4, 5, 6, 7, 8, 9, 10 };     // D3DTOP_MODULATE ... D3DTOP_SUBTRACT
        static readonly string[] FormScripts =
        {
            "FS_NONE:", "FS_FORMX:", "FS_FORMY:", "FS_FORMZ:", "FS_SCROLL:", "FS_REFLEX:",
            "FS_SCROLL2:", "FS_SCROLL3:", "FS_SCROLL4:", "FS_SCROLL5:", "FS_SCROLL6:", "FS_SCROLL7:",
            "FS_SCROLL8:", "FS_SCROLL9:", "FS_SCROLL10:",
            "FS_SCROLLSLOW1:", "FS_SCROLLSLOW2:", "FS_SCROLLSLOW3:", "FS_SCROLLSLOW4:",
        };
        static readonly string[] BlinkScripts = { "BLINK_TIME1:", "BLINK_TIME2:", "BLINK_TIME3:", "BLINK_TIME4:", "BLINK_TIME5:", "BLINK_TIME6:", "BLINK_TIME7:", "BLINK_TIME8:" };

        internal sealed class MatList
        {
            public AseMats A = new AseMats();
            public int AseCount;
            public bool LightMapStage;
            public List<Mat> Mats = new List<Mat>();
            public TexTable Tex = new TexTable();
            public int ReformTexture;
            public Dictionary<int, int> SubCount = new Dictionary<int, int>();
        }

        static string BaseOf(string s, bool slash)
        {
            if (s.Length == 0) return "Ì";                      // (the game reads the byte before its empty buffer:
            int cnt;                                                 //  0xCC in the debug build that made the maps)
            for (cnt = s.Length - 1; cnt > 0; cnt--)
                if (s[cnt] == '\\' || s[cnt] == ':' || (slash && s[cnt] == '/')) { cnt++; break; }
            return cnt <= 0 ? s : s.Substring(cnt);
        }

        // ReadASE_LIGHTMAP_MATERIAL (lines after "*MATERIAL_LIST {")
        internal static MatList ReadMaterials(Lines rd, string dataDir, bool own)
        {
            var ml = new MatList();
            var A = ml.A;
            var scripts = new List<(int mat, string s)>();
            var lmRef = new List<(bool lm, int sub, int max)>();          // s_LightMapRefBuff
            int strLevel = 0, oldStrLevel = 0, mCount = 0, smCount = 0, matrialNum = 0, oldMatrialNum = 0,
                subMatrialNum = 0, newMatrial = 0, cur = 0, bitmapDiffuse = 0, bitmapCnt = -1,
                stageState = 0, formState = 0;
            while (true)
            {
                string line = rd.Need();
                int p = 0;
                string decode = Word(line, ref p);

                if (decode == "*MATERIAL_COUNT") { mCount = Atoi(Word(line, ref p)); newMatrial = mCount; }
                if (decode == "*MATERIAL") { matrialNum = Atoi(Word(line, ref p)); cur = matrialNum; bitmapCnt = -1; }

                if (decode == "*MATERIAL_NAME")
                {
                    string name = Str(line, ref p);
                    if (strLevel == 1)
                    {
                        if (lmRef.Count >= 4000) lmRef.RemoveAt(lmRef.Count - 1);
                        bool lm = Has(name, "*LM_");
                        if (lm) ml.LightMapStage = true;
                        lmRef.Add((lm, 0, 0));
                    }
                    int st = A.I(cur, AseMats.ScriptState);
                    foreach (var sc in MatScripts) if (Has(name, sc.s)) st |= sc.code;
                    A.SetI(cur, AseMats.ScriptState, st);
                    if (st != 0 && scripts.Count < 256) scripts.Add((cur, name.Length > 63 ? name.Substring(0, 63) : name));
                    foreach (var b in MatBlends) if (Has(name, b.s)) { A.SetI(cur, AseMats.BlendType, b.code); break; }
                }

                if (decode == "*NUMSUBMTLS")
                {
                    if (strLevel % 2 == 0 && smCount - (subMatrialNum + 1) > 0) { oldStrLevel = strLevel - 1; oldMatrialNum = matrialNum; }
                    else oldMatrialNum = 0;
                    smCount = Atoi(Word(line, ref p));
                    A.SetI(cur, AseMats.SubPoint, newMatrial);
                    ml.SubCount[cur] = smCount;
                    int r = lmRef.Count - 1;
                    if (r >= 0)
                    {
                        var e = lmRef[r];
                        if (e.lm) { if (r == cur) e.sub = newMatrial; else e.max = smCount; }
                        else { e.sub = newMatrial; e.max = smCount; }
                        lmRef[r] = e;
                    }
                    matrialNum = newMatrial;
                    newMatrial += smCount;
                }
                if (decode == "*SUBMATERIAL")
                {
                    if (strLevel == oldStrLevel && oldMatrialNum != 0) { matrialNum = oldMatrialNum; oldStrLevel = oldMatrialNum = 0; }
                    subMatrialNum = Atoi(Word(line, ref p));
                    cur = matrialNum + subMatrialNum;
                    bitmapCnt = -1;
                }

                if (decode == "*MAP_DIFFUSE") bitmapDiffuse = 1;
                if (decode == "*MAP_OPACITY") bitmapDiffuse = 0;
                if (decode == "*MAP_AMBIENT") bitmapDiffuse = -1;

                if (decode == "*MAP_NAME")
                {
                    string mn = Str(line, ref p);
                    stageState = 0; formState = 0;
                    for (int i = 0; i < StageScripts.Length; i++) if (Has(mn, StageScripts[i])) { stageState = StageCodes[i]; break; }
                    for (int i = 0; i < FormScripts.Length; i++) if (Has(mn, FormScripts[i])) { formState = i; break; }
                }

                if (decode == "*BITMAP")
                {
                    string file = dataDir + BaseOf(Str(line, ref p), own);
                    if (bitmapDiffuse == 1)
                    {
                        bitmapCnt++;
                        A.SetS(cur, AseMats.BITMAP + 64 * bitmapCnt, file);
                        A.SetI(cur, AseMats.TextureCounter, A.I(cur, AseMats.TextureCounter) + 1);
                        A.SetI(cur, AseMats.BitmapStateState + 4 * bitmapCnt, stageState);
                        A.SetI(cur, AseMats.BitmapFormState + 4 * bitmapCnt, formState);
                    }
                    else if (bitmapDiffuse == 0)
                        A.SetS(cur, AseMats.MAP_OPACITY, file);
                }

                if (decode == "*UVW_U_OFFSET") A.SetF(cur, AseMats.U_OFFSET + 4 * bitmapCnt, (float)Atof(Word(line, ref p)));
                if (decode == "*UVW_V_OFFSET") A.SetF(cur, AseMats.V_OFFSET + 4 * bitmapCnt, (float)Atof(Word(line, ref p)));
                if (decode == "*UVW_U_TILING") A.SetF(cur, AseMats.U_TILING + 4 * bitmapCnt, (float)Atof(Word(line, ref p)));
                if (decode == "*UVW_V_TILING") A.SetF(cur, AseMats.V_TILING + 4 * bitmapCnt, (float)Atof(Word(line, ref p)));
                if (decode == "*UVW_ANGLE") A.SetF(cur, AseMats.ANGLE + 4 * bitmapCnt, (float)Atof(Word(line, ref p)));

                if (decode == "*MATERIAL_TWOSIDED") A.SetI(cur, AseMats.TwoSide, 1);
                if (decode == "*MATERIAL_DIFFUSE")
                {
                    A.SetF(cur, AseMats.Diffuse, (float)Atof(Word(line, ref p)));
                    A.SetF(cur, AseMats.Diffuse + 4, (float)Atof(Word(line, ref p)));
                    A.SetF(cur, AseMats.Diffuse + 8, (float)Atof(Word(line, ref p)));
                }
                if (decode == "*MATERIAL_TRANSPARENCY")
                {
                    string w = Word(line, ref p);
                    if (A.F(cur, AseMats.Transparency) == 0) A.SetF(cur, AseMats.Transparency, (float)Atof(w));
                }
                if (decode == "*MATERIAL_SELFILLUM")
                {
                    string w = Word(line, ref p);
                    if (A.F(cur, AseMats.SelfIllum) == 0) A.SetF(cur, AseMats.SelfIllum, (float)Atof(w));
                }

                if (line.IndexOf('{') >= 0) strLevel++;
                if (line.IndexOf('}') >= 0) { strLevel--; if (strLevel < 0) break; }
            }

            int aseCnt = newMatrial;

            // light-mapped stage: a "*LM_" Shell material's sub 1 is the light map, appended as the last
            // texture of every sub-material of its sub 0
            if (ml.LightMapStage)
            {
                int end = lmRef.Count;
                for (int cnt = 0; cnt < lmRef.Count; cnt++)
                {
                    int sp = lmRef[cnt].sub, max = lmRef[cnt].max;
                    if (sp != 0)
                    {
                        if (lmRef[cnt].lm)
                        {
                            byte[] lmMat = A.Get(sp + 1);
                            A.Copy(end, sp + 2, AseMats.Size * max);
                            for (int i = end; i < end + max; i++)
                            {
                                int bc = A.I(i, AseMats.TextureCounter);
                                A.SetI(i, AseMats.TextureCounter, bc + 1);
                                A.SetS(i, AseMats.BITMAP + 64 * bc, CStr(lmMat, AseMats.BITMAP));
                                A.SetI(i, AseMats.BitmapStateState + 4 * bc, BitConverter.ToInt32(lmMat, AseMats.BitmapStateState));
                                A.SetI(i, AseMats.BitmapFormState + 4 * bc, BitConverter.ToInt32(lmMat, AseMats.BitmapFormState));
                                A.SetF(i, AseMats.U_OFFSET + 4 * bc, BitConverter.ToSingle(lmMat, AseMats.U_OFFSET));
                                A.SetF(i, AseMats.V_OFFSET + 4 * bc, BitConverter.ToSingle(lmMat, AseMats.V_OFFSET));
                                A.SetF(i, AseMats.U_TILING + 4 * bc, BitConverter.ToSingle(lmMat, AseMats.U_TILING));
                                A.SetF(i, AseMats.V_TILING + 4 * bc, BitConverter.ToSingle(lmMat, AseMats.V_TILING));
                                A.SetF(i, AseMats.ANGLE + 4 * bc, BitConverter.ToSingle(lmMat, AseMats.ANGLE));
                            }
                            aseCnt -= 2;
                            for (int s = 0; s < scripts.Count; s++)
                            {
                                int m = scripts[s].mat;
                                if (m == sp || m == sp + 1) scripts[s] = (0, scripts[s].s);
                                else if (m >= sp + 2 && m <= sp + 2 + max - 1) scripts[s] = (m - 2, scripts[s].s);
                            }
                        }
                        else
                        {
                            A.Copy(end, sp, max);                          // (the game copies max BYTES here)
                            int num = sp - end;
                            for (int s = 0; s < scripts.Count; s++)
                            {
                                int m = scripts[s].mat;
                                if (m >= sp && m <= sp + max - 1) scripts[s] = (m - num, scripts[s].s);
                            }
                        }
                        A.SetI(cnt, AseMats.SubPoint, end);
                        end += max;
                    }
                    else if (lmRef[cnt].lm)
                        throw new SmdException("light-map material without sub-materials");
                }
            }

            // de-duplicate (same bytes, same first bitmap; material 0 is never a target)
            aseCnt = Math.Max(0, Math.Min(aseCnt, AseMats.Count));
            var sum = new uint[aseCnt];
            var link = new int[aseCnt];
            for (int c = 0; c < aseCnt; c++) sum[c] = A.Sum(c);
            for (int c = 0; c < aseCnt; c++)
            {
                int n;
                for (n = 0; n < c; n++) if (sum[n] == sum[c]) break;
                link[c] = n > 0 && n < c && AsciiNoCase.I.Equals(A.S(c, AseMats.BITMAP), A.S(n, AseMats.BITMAP)) ? n : -1;
            }
            string dbg = Environment.GetEnvironmentVariable("PT_ASE2SMD_DEBUG");
            if (!string.IsNullOrEmpty(dbg))
                using (var dw = new StreamWriter(dbg))
                    for (int c = 0; c < aseCnt; c++)
                        dw.WriteLine(c + "	" + sum[c] + "	" + link[c] + "	" + A.S(c, AseMats.BITMAP) + "	" + BitConverter.ToString(A.Get(c)).Replace("-", ""));
            for (int c = 0; c < aseCnt; c++)
            {
                string script = null;
                foreach (var s in scripts) if (s.mat == c) { script = s.s; break; }
                if (link[c] < 0) A.SetI(c, AseMats.RegistNum, AddMaterial(ml, c, script));
                else A.SetI(c, AseMats.RegistNum, A.I(link[c], AseMats.RegistNum));
                A.SetI(c, AseMats.Regist, 1);
            }
            ml.AseCount = aseCnt;
            return ml;
        }

        static string CStr(byte[] b, int o)
        {
            int e = o;
            while (e < b.Length && b[e] != 0) e++;
            return Bin.Latin1.GetString(b, o, e - o);
        }

        // wsprintf( out, "dir\\flame%d.tga", n )
        static string Printf(string fmt, int n)
        {
            var sb = new StringBuilder();
            bool used = false;
            for (int i = 0; i < fmt.Length; i++)
            {
                char c = fmt[i];
                if (c != '%' || i + 1 >= fmt.Length) { sb.Append(c); continue; }
                if (fmt[i + 1] == '%') { sb.Append('%'); i++; continue; }
                int j = i + 1;
                bool zero = j < fmt.Length && fmt[j] == '0';
                while (j < fmt.Length && fmt[j] >= '0' && fmt[j] <= '9') j++;
                int width = j > i + 1 ? int.Parse(fmt.Substring(i + 1, j - i - 1), CultureInfo.InvariantCulture) : 0;
                if (j < fmt.Length && (fmt[j] == 'd' || fmt[j] == 'i' || fmt[j] == 'u') && !used)
                {
                    string v = n.ToString(CultureInfo.InvariantCulture);
                    sb.Append(v.PadLeft(width, zero ? '0' : ' '));
                    used = true;
                    i = j;
                }
                else sb.Append(c);
            }
            return sb.ToString();
        }

        // smMATERIAL_GROUP::AddMaterial
        static int AddMaterial(MatList ml, int am, string script)
        {
            var A = ml.A;
            var m = new Mat();
            int num = ml.Mats.Count;
            ml.Mats.Add(m);
            m.SetI(Mat.InUse, 1);
            m.SetI(Mat.Shade, 1);
            m.SetI(Mat.BlendType, 1);
            m.SetI(Mat.TwoSide, A.I(am, AseMats.TwoSide));
            int texCount = A.I(am, AseMats.TextureCounter);
            int reform = 0;
            string opacity = A.S(am, AseMats.MAP_OPACITY);
            int n8 = Math.Min(Math.Max(texCount, 0), 8);
            for (int c = 0; c < n8; c++)
            {
                string bmp = A.S(am, AseMats.BITMAP + 64 * c);
                bool withA = opacity.Length > 0 && (texCount <= 1 || c < texCount - 1);   // (a light map gets no alpha)
                m.Tex[c] = ml.Tex.Add(bmp, withA ? opacity : null);
                m.SetI(Mat.TextureStageState + 4 * c, A.I(am, AseMats.BitmapStateState + 4 * c));
                int fs = A.I(am, AseMats.BitmapFormState + 4 * c);
                m.SetI(Mat.TextureFormState + 4 * c, fs);
                reform += fs;
            }
            m.SetI(Mat.ReformTexture, reform);
            m.SetI(Mat.MapOpacity, opacity.Length > 0 ? 1 : 0);
            if (reform != 0) ml.ReformTexture++;
            m.SetI(Mat.TextureCounter, texCount);
            m.SetF(Mat.Transparency, A.F(am, AseMats.Transparency));
            m.SetF(Mat.SelfIllum, A.F(am, AseMats.SelfIllum));
            for (int i = 0; i < 3; i++) m.SetF(Mat.Diffuse + 4 * i, A.F(am, AseMats.Diffuse + 4 * i));
            int ss = A.I(am, AseMats.ScriptState);
            m.SetI(Mat.UseState, ss);
            m.SetI(Mat.TextureType, 0);
            int bt = A.I(am, AseMats.BlendType);
            if (bt != 0) m.SetI(Mat.BlendType, bt);
            if (m.F(Mat.Transparency) == 0) m.SetI(Mat.MeshState, 1);
            void Wind(int bit, int code) { if ((ss & bit) != 0) { m.SetI(Mat.WindMeshBottom, code); m.SetI(Mat.MeshState, 0); } }
            Wind(0x1, 0x20); Wind(0x80, 0x80); Wind(0x100, 0x100); Wind(0x20, 0x20); Wind(0x40, 0x40); Wind(0x200, 0x200);
            if ((ss & 0x1000) != 0) m.SetI(Mat.MeshState, 1);
            else if ((ss & 0x800) != 0) m.SetI(Mat.MeshState, 0);
            if ((ss & 0x2000) != 0) m.SetI(Mat.MeshState, m.I(Mat.MeshState) | 0x2000);
            if ((ss & 0x8000) != 0) m.SetI(Mat.MeshState, m.I(Mat.MeshState) | 0x8000);
            if ((ss & 0x10000) != 0) m.SetI(Mat.MeshState, 0x10000);

            int animCount = 0;
            if (script != null)
            {
                if ((ss & 0x2) != 0) animCount = 2;
                if ((ss & 0x4) != 0) animCount = 4;
                if ((ss & 0x8) != 0) animCount = 8;
                if ((ss & 0x10) != 0) animCount = 16;
            }
            if (animCount != 0)
            {
                int len = script.Length, cnt;
                for (cnt = 0; cnt < len; cnt++)
                    if (cnt + 3 < len && script[cnt] == 'a' && script[cnt + 1] == 'n' && script[cnt + 2] == 'i' && script[cnt + 3] == 'm')
                    {
                        for (; cnt < len; cnt++) if (script[cnt] == ':') break;
                        break;
                    }
                if (cnt < len)
                {
                    cnt++;
                    int start = cnt, frameSpeed = 0, stop = len;
                    for (; cnt < len; cnt++)
                        if (script[cnt] == ':') { frameSpeed = Atoi(script.Substring(cnt + 1)); stop = cnt; break; }
                    string pattern = script.Substring(start, stop - start);
                    string b0 = A.S(am, AseMats.BITMAP);
                    int bs = b0.LastIndexOf('\\');
                    string dir = bs >= 0 ? b0.Substring(0, bs + 1) : "";
                    // ChangeMaterialToAnimation
                    for (int i = 0; i < animCount; i++) m.Anim[i] = ml.Tex.Add(Printf(dir + pattern, i));
                    m.SetI(Mat.MapOpacity, 0);
                    m.SetI(Mat.TextureCounter, 1);
                    m.SetI(Mat.AnimTexCounter, animCount);
                    m.SetI(Mat.FrameMask, animCount - 1);
                    m.SetI(Mat.Shift_FrameSpeed, 6);
                    m.SetI(Mat.UseState, 0);
                    m.SetI(Mat.TextureType, 1);
                    m.SetI(Mat.AnimationFrame, 0x100);
                    m.SetI(Mat.InUse, m.I(Mat.InUse) + 1);
                    if (frameSpeed != 0) m.SetI(Mat.Shift_FrameSpeed, frameSpeed);
                    m.SetF(Mat.Transparency, A.F(am, AseMats.Transparency));
                }
            }
            if ((ss & 0x4000) != 0 && m.I(Mat.WindMeshBottom) == 0)
            {
                int c;
                for (c = 0; c < BlinkScripts.Length; c++) if (Has(script ?? "", BlinkScripts[c])) break;
                m.SetI(Mat.WindMeshBottom, c >= BlinkScripts.Length ? 9 : 9 + c);
            }
            A.SetI(am, AseMats.Regist, A.I(am, AseMats.Regist) + 1);
            A.SetI(am, AseMats.RegistNum, num);
            return num;
        }

        // ------------------------------------------------------------------ the stage being built
        const int FONE = 256, FLOATNS = 8;
        internal const int SMC_B = 0, SMC_G = 1, SMC_R = 2, SMC_A = 3;

        internal sealed class StageBuild
        {
            public List<int> X = new List<int>(), Y = new List<int>(), Z = new List<int>();
            public List<short[]> Col = new List<short[]>();
            public List<bool> Baked = new List<bool>();
            public List<int[]> Face = new List<int[]>();            // a, b, c, mat
            public List<int> FaceTex = new List<int>();             // first TexLink or -1
            public List<short[]> Normal = new List<short[]>();
            public List<float[]> TexUV = new List<float[]>();        // u0 u1 u2 v0 v1 v2
            public List<uint> TexH = new List<uint>();
            public List<int> TexNext = new List<int>();
            public int Left, Top, Right, Bottom;
            public List<int[]> Lights = new List<int[]>();           // type x y z range r g b

            public int AddVertex(int x, int y, int z)
            {
                if (X.Count == 0) { Top = Bottom = z; Left = Right = x; }
                else
                {
                    if (Top > z) Top = z;
                    if (Bottom < z) Bottom = z;
                    if (Left > x) Left = x;
                    if (Right < x) Right = x;
                }
                X.Add(x); Y.Add(y); Z.Add(z);
                Col.Add(new short[] { 255, 255, 255, 255 });
                Baked.Add(false);
                return X.Count - 1;
            }

            public void AddTexLink(int face, uint hTex, float[] uv)
            {
                int n = TexUV.Count;
                TexUV.Add(uv); TexH.Add(hTex); TexNext.Add(-1);
                if (FaceTex[face] < 0) FaceTex[face] = n;
                else
                {
                    int t = FaceTex[face];
                    for (int c = 0; c < 8; c++)
                    {
                        if (TexNext[t] < 0) { TexNext[t] = n; break; }
                        t = TexNext[t];
                    }
                }
            }
        }

        // fake heap addresses for the pointers the game saves (only TexLink's is used: links are
        // relative to it; the others must merely be non-zero where the game tests them)
        const uint PtrAreaList = 0x235BA0B8, PtrVertex = 0x2EE60020, PtrFace = 0x2EF80020, PtrTexLink = 0x2F0C0020,
            PtrLight = 0x234BDC48, PtrGroup = 0x234BD760, PtrStageObject = 0x2356F090, PtrMaterial = 0x23556448,
            PtrAreaBuff = 0x2F640020, PtrTexture = 0x04A00338;
        const int TextureHandleSize = 172;

        static uint HTex(int mat, int layer) => (uint)(PtrMaterial + mat * Smd.MaterialSize + Mat.smTexture + 4 * layer);

        // ------------------------------------------------------------------ fixed-point helpers
        static readonly int[] Sin = new int[4097], Cos = new int[4097];
        static AseToSmd()
        {
            const float PI = 3.14159265358979323846f;
            for (int c = 0; c <= 4096; c++)
            {
                float ang = (float)c * PI / 2048f;
                Sin[c] = (int)(Math.Sin(ang) * 65536);
                Cos[c] = (int)(Math.Cos(ang) * 65536);
            }
        }
        const double MultPie = (2048f / 3.14159265358979323846f) + 0.5;

        // (int) of a float/double: out of range -> 0x80000000; NaN -> 0 (what the shipped maps show)
        static int Trunc(double d)
        {
            if (double.IsNaN(d)) return 0;
            if (d >= 2147483648.0 || d <= -2147483649.0) return int.MinValue;
            return (int)d;
        }

        // SetNormal (smMap3d.cpp) as the shipped maps have it: the three divisions by d were compiled
        // as one multiplication by a float 1/d, the rest in double; 0/0 (a face without area) gave 0
        static void SetNormal(int[] p1, int[] p2, int[] p3, int[] n, bool single)
        {
            unchecked
            {
                if (single)
                {
                    float fi = (float)((p2[1] - p1[1]) * (p3[2] - p1[2]) - (p2[2] - p1[2]) * (p3[1] - p1[1]));
                    float fj = (float)((p2[2] - p1[2]) * (p3[0] - p1[0]) - (p2[0] - p1[0]) * (p3[2] - p1[2]));
                    float fk = (float)((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0]));
                    float fd = (float)Math.Sqrt((float)((float)((float)(fi * fi) + (float)(fj * fj)) + (float)(fk * fk)));
                    float fr = (float)(1f / fd);
                    n[0] = Trunc((float)((float)(fi * fr) * 32767f)); n[1] = Trunc((float)((float)(fj * fr) * 32767f));
                    n[2] = Trunc((float)((float)(fk * fr) * 32767f));
                    return;
                }
                double i = (float)((p2[1] - p1[1]) * (p3[2] - p1[2]) - (p2[2] - p1[2]) * (p3[1] - p1[1]));
                double j = (float)((p2[2] - p1[2]) * (p3[0] - p1[0]) - (p2[0] - p1[0]) * (p3[2] - p1[2]));
                double k = (float)((p2[0] - p1[0]) * (p3[1] - p1[1]) - (p2[1] - p1[1]) * (p3[0] - p1[0]));
                float d = (float)Math.Sqrt(i * i + j * j + k * k);
                double r = (float)(1.0 / d);
                n[0] = Trunc(i * r * 32767); n[1] = Trunc(j * r * 32767); n[2] = Trunc(k * r * 32767);
            }
        }

        // ------------------------------------------------------------------ GEOMOBJECT
        sealed class UvList
        {
            public List<float> U = new List<float>(), V = new List<float>();
            public List<int[]> F = new List<int[]>();
        }

        static void ReadGeomObject(Lines rd, StageBuild st, MatList ml, bool own, bool single, EncodeResult res)
        {
            int objFace = st.Face.Count, objVertex = st.X.Count;
            int strLevel = 0, nVertex = -1, nFace = -1, nTVertex = -1, vertexCnt = 0, faceCnt = 0, mCount = 0, matrialRef = 0;
            int[] faceMat = new int[0];
            bool lightMap = false, inChannel = false;
            int chNum = 1, chLevel = 0;
            UvList main = null, gameLm = null, target = null;
            var channels = new Dictionary<int, UvList>();
            var cPoint = new List<float[]>();
            var cFace = new List<int[]>();
            while (true)
            {
                string line = rd.Need();
                int p = 0;
                string decode = Word(line, ref p);
                bool channelLine = false;

                if (decode == "*MESH_NUMVERTEX") nVertex = Atoi(Word(line, ref p));
                if (decode == "*MESH_NUMFACES") { nFace = Atoi(Word(line, ref p)); faceMat = new int[Math.Max(nFace, 0)]; }
                if (decode == "*MESH_NUMTVERTEX")
                {
                    nTVertex = Atoi(Word(line, ref p));
                    var l = new UvList();
                    if (lightMap) gameLm = l; else main = l;
                    channels[inChannel ? chNum : 1] = l;
                    target = l;
                }
                if (decode == "*MESH_MAPPINGCHANNEL")
                {
                    chNum = Atoi(Word(line, ref p));
                    lightMap = true;
                    inChannel = true;
                    chLevel = strLevel;
                    channelLine = true;
                }
                if (decode == "*MESH_VERTEX")
                {
                    Word(line, ref p);
                    int x = Fixed(Atof(Word(line, ref p)), own);
                    int z = Fixed(Atof(Word(line, ref p)), own);
                    int y = Fixed(Atof(Word(line, ref p)), own);
                    st.AddVertex(x, y, z);
                    vertexCnt++;
                }
                if (decode == "*MESH_FACE")
                {
                    Word(line, ref p);
                    Word(line, ref p); int a = Atoi(Word(line, ref p));
                    Word(line, ref p); int b = Atoi(Word(line, ref p));
                    Word(line, ref p); int c = Atoi(Word(line, ref p));
                    for (int k = 0; k < 16; k++)
                        if (Word(line, ref p) == "*MESH_MTLID")
                        {
                            int id = Atoi(Word(line, ref p));
                            if (mCount < faceMat.Length) faceMat[mCount] = id;
                            mCount++;
                            break;
                        }
                    st.Face.Add(new[] { a + objVertex, b + objVertex, c + objVertex, 0 });
                    st.FaceTex.Add(-1);
                    st.Normal.Add(new short[4]);
                    faceCnt++;
                }
                if (decode == "*MESH_TVERT" && target != null)
                {
                    Word(line, ref p);
                    target.U.Add((float)Atof(Word(line, ref p)));
                    target.V.Add(-(float)Atof(Word(line, ref p)));
                }
                if (decode == "*MESH_TFACE" && target != null)
                {
                    Word(line, ref p);
                    target.F.Add(new[] { Atoi(Word(line, ref p)), Atoi(Word(line, ref p)), Atoi(Word(line, ref p)) });
                }
                if (decode == "*MESH_VERTCOL")
                {
                    Word(line, ref p);
                    cPoint.Add(new[] { (float)Atof(Word(line, ref p)), (float)Atof(Word(line, ref p)), (float)Atof(Word(line, ref p)) });
                }
                if (decode == "*MESH_CFACE")
                {
                    Word(line, ref p);
                    cFace.Add(new[] { Atoi(Word(line, ref p)), Atoi(Word(line, ref p)), Atoi(Word(line, ref p)) });
                }
                if (decode == "*MATERIAL_REF") matrialRef = Atoi(Word(line, ref p));

                string w2 = Word(line, ref p);
                if (decode == "{" || w2 == "{") strLevel++;
                if (decode == "}" || w2 == "}")
                {
                    strLevel--;
                    if (strLevel < 0) break;
                    if (inChannel && !channelLine && strLevel == chLevel) inChannel = false;
                }
            }

            int nv = st.X.Count;
            for (int f = objFace; f < st.Face.Count; f++)
                for (int k = 0; k < 3; k++)
                    if (st.Face[f][k] < objVertex || st.Face[f][k] >= nv)
                    {
                        res.BadFaces++;
                        st.Face[f][k] = Math.Min(objVertex, nv - 1);
                    }

            // ---- materials and texture coordinates
            if (own) channels.TryGetValue(1, out main);              // (our files put the extra channels first)
            bool textured = own ? (main != null && main.U.Count > 0) : nTVertex > 0;
            int subPoint = ml.A.I(matrialRef, AseMats.SubPoint);
            ml.SubCount.TryGetValue(matrialRef, out int subN);
            float[] Corner(UvList l, int face, int k)
            {
                if (l == null || face >= l.F.Count) return new float[] { 0, 0 };
                int t = l.F[face][k];
                if (t < 0 || t >= l.U.Count) return new float[] { 0, 0 };
                return new[] { l.U[t], l.V[t] };
            }
            float[] Xform(UvList l, int face, int fmat, int layer)
            {
                var A = ml.A;
                double ou = A.F(fmat, AseMats.U_OFFSET + 4 * layer), ov = A.F(fmat, AseMats.V_OFFSET + 4 * layer);
                double tu = A.F(fmat, AseMats.U_TILING + 4 * layer), tv = A.F(fmat, AseMats.V_TILING + 4 * layer);
                float ang = (float)(A.F(fmat, AseMats.ANGLE + 4 * layer) * MultPie);
                int ai = Trunc(ang) & 4095;
                double fs = (double)Sin[ai] / 65536, fc = (double)Cos[ai] / 65536;
                var uv = new float[6];
                if (single)
                {
                    float sfs = (float)fs, sfc = (float)fc, sou = (float)ou, sov = (float)ov, stu = (float)tu, stv = (float)tv;
                    for (int k = 0; k < 3; k++)
                    {
                        var c = Corner(l, face, k);
                        float fU = (float)(c[0] - 0.5f), fV = (float)(c[1] - 0.5f);
                        float fu = (float)((float)(fU * sfc) + (float)(fV * sfs));
                        float fv = (float)((float)(fV * sfc) - (float)(fU * sfs));
                        fu = (float)(fu - sou); fv = (float)(fv - sov);
                        fu = (float)(fu * stu); fv = (float)(fv * stv);
                        uv[k] = (float)(fu + 0.5f); uv[3 + k] = (float)(fv + 0.5f);
                    }
                    return uv;
                }
                for (int k = 0; k < 3; k++)                          // (the shipped maps keep the values exact:
                {                                                    //  the game worked in double, stored float)
                    var c = Corner(l, face, k);
                    double fU = c[0] - 0.5, fV = c[1] - 0.5;
                    double fu = fU * fc + fV * fs;
                    double fv = fV * fc - fU * fs;
                    fu -= ou; fv -= ov;
                    fu *= tu; fv *= tv;
                    uv[k] = (float)(fu + 0.5); uv[3 + k] = (float)(fv + 0.5);
                }
                return uv;
            }

            int fcount = st.Face.Count - objFace;
            bool untexturedObject = true;                     // (every face's material without textures)
            for (int cnt = 0; cnt < fcount && untexturedObject; cnt++)
            {
                int id = cnt < faceMat.Length ? faceMat[cnt] : 0;
                if (own && subN > 0) id = ((id % subN) + subN) % subN;
                int mn = ml.A.I(subPoint != 0 ? subPoint + id : matrialRef, AseMats.RegistNum);
                if (mn >= 0 && mn < ml.Mats.Count && ml.Mats[mn].I(Mat.TextureCounter) > 0) untexturedObject = false;
            }
            if (textured || own)
            {
                for (int cnt = 0; cnt < fcount; cnt++)
                {
                    int id = cnt < faceMat.Length ? faceMat[cnt] : 0;
                    if (own && subN > 0) id = ((id % subN) + subN) % subN;
                    int fmat = subPoint != 0 ? subPoint + id : matrialRef;
                    int mNum = ml.A.I(fmat, AseMats.RegistNum);
                    if (mNum < 0 || mNum >= ml.Mats.Count) mNum = 0;
                    if (ml.Mats.Count == 0) { st.Face[cnt + objFace][3] = 0; continue; }
                    var mat = ml.Mats[mNum];
                    mat.SetI(Mat.InUse, mat.I(Mat.InUse) + 1);
                    int texCnt = mat.I(Mat.TextureCounter);
                    bool lm = !own && lightMap;
                    if (lm) texCnt--;
                    int t;
                    for (t = 0; t < texCnt; t++)
                    {
                        UvList src = main;
                        if (own && channels.TryGetValue(t + 1, out UvList ch) && ch.U.Count > 0) src = ch;
                        float[] uv = textured ? Xform(src, cnt, fmat, t) : new float[6];
                        st.AddTexLink(cnt + objFace, HTex(mNum, t), uv);
                    }
                    if (own && texCnt <= 0 && untexturedObject)    // (the game: an untextured object gets one empty link)
                        st.AddTexLink(cnt + objFace, 0, new float[6]);
                    if (lm)
                    {
                        t = Math.Max(texCnt, 0);
                        st.AddTexLink(cnt + objFace, HTex(mNum, t), Xform(gameLm, cnt, fmat, t));
                    }
                    st.Face[cnt + objFace][3] = mNum;
                }
            }
            else
            {
                for (int cnt = 0; cnt < fcount; cnt++)
                {
                    st.Face[cnt + objFace][3] = 0;
                    st.AddTexLink(cnt + objFace, 0, new float[6]);
                }
            }

            // ---- vertex colours
            int ovc = st.X.Count - objVertex;
            if (cFace.Count > 0 && ovc > 0)
            {
                var sum = new float[ovc][];
                var num = new int[ovc];
                for (int i = 0; i < ovc; i++) { sum[i] = own ? new float[3] : new float[] { 1, 1, 1 }; num[i] = own ? 0 : 1; }
                for (int cnt = 0; cnt < fcount && cnt < cFace.Count; cnt++)
                    for (int k = 0; k < 3; k++)
                    {
                        int v = st.Face[cnt + objFace][k] - objVertex;
                        int ci = cFace[cnt][k];
                        if (v < 0 || v >= ovc || ci < 0 || ci >= cPoint.Count) continue;
                        for (int c = 0; c < 3; c++) sum[v][c] += cPoint[ci][c];
                        num[v]++;
                    }
                for (int i = 0; i < ovc; i++)
                {
                    if (num[i] == 0) continue;
                    var col = st.Col[objVertex + i];
                    if (own)
                    {
                        for (int c = 0; c < 3; c++) sum[i][c] /= num[i];
                        col[SMC_R] = Sat(Math.Round(sum[i][0] * 255.0));
                        col[SMC_G] = Sat(Math.Round(sum[i][1] * 255.0));
                        col[SMC_B] = Sat(Math.Round(sum[i][2] * 255.0));
                        col[SMC_A] = 255;
                        st.Baked[objVertex + i] = true;
                    }
                    else
                    {
                        for (int c = 0; c < 3; c++) sum[i][c] /= num[i];
                        col[SMC_R] = (byte)Trunc(sum[i][0] * 255f);
                        col[SMC_G] = (byte)Trunc(sum[i][1] * 255f);
                        col[SMC_B] = (byte)Trunc(sum[i][2] * 255f);
                        col[SMC_A] = 255;
                    }
                }
                if (own) res.BakedObjects++;
            }
            else res.ShadedObjects++;
        }

        // x 256 to whole numbers: the game truncates; files from our tools are rounded, because 3ds Max and
        // Blender write world positions with float noise (313.23827 for 313.23828 = 80189 / 256)
        static int Fixed(double v, bool own) => own ? Trunc(Math.Round(v * FONE, MidpointRounding.AwayFromZero)) : Trunc(v * FONE);

        static short Sat(double v) => (short)Math.Max(-32768, Math.Min(32767, v));

        // ------------------------------------------------------------------ LIGHTOBJECT
        static int[] ReadLight(Lines rd, bool own)
        {
            int strLevel = 0, intens = 0, type = 0, x = 0, y = 0, z = 0, range = 0, r = 0, g = 0, b = 0;
            double attnEnd = -1;
            while (true)
            {
                string line = rd.Need();
                int p = 0;
                string decode = Word(line, ref p);
                if (decode == "*NODE_NAME")
                {
                    string n = Str(line, ref p);
                    if (n.Length > 31) n = n.Substring(0, 31);
                    if (Has(n, "dynamic:")) type |= 0x80000;
                    if (Has(n, "night:")) type |= 0x80000 | 0x1;
                    if (Has(n, "lens:")) type |= 0x80000 | 0x2;
                    if (Has(n, "obj:")) type |= 0x80000 | 0x8;
                }
                if (decode == "*LIGHT_COLOR")
                {
                    double cr = Atof(Word(line, ref p)), cg = Atof(Word(line, ref p)), cb = Atof(Word(line, ref p));
                    if (own) { r = (int)Math.Round(cr * 255); g = (int)Math.Round(cg * 255); b = (int)Math.Round(cb * 255); }
                    else { r = Trunc(cr * 255); g = Trunc(cg * 255); b = Trunc(cb * 255); }
                }
                if (decode == "*LIGHT_INTENS") intens = Trunc(Atof(Word(line, ref p)) * FONE);
                if (decode == "*TM_POS")
                {
                    x = Fixed(Atof(Word(line, ref p)), own);
                    z = Fixed(Atof(Word(line, ref p)), own);
                    y = Fixed(Atof(Word(line, ref p)), own);
                }
                if (decode == "*LIGHT_MAPRANGE") range = Trunc(Atof(Word(line, ref p)) * FONE / 4 * FONE);
                if (decode == "*LIGHT_ATTNEND") attnEnd = Atof(Word(line, ref p));
                string w2 = Word(line, ref p);
                if (decode == "{" || w2 == "{") strLevel++;
                if (decode == "}" || w2 == "}") { strLevel--; if (strLevel < 0) break; }
            }
            if (own && attnEnd > 0) range = (int)Math.Round(attnEnd * 256);
            if (intens != 0)
            {
                if (intens >= 0 && intens < 64) intens = 64;
                if (intens < 0 && intens > -64) intens = -64;
                unchecked { r = (r * intens) >> FLOATNS; g = (g * intens) >> FLOATNS; b = (b * intens) >> FLOATNS; }
            }
            return new[] { type, x, y, z, range, r, g, b };
        }

        // ------------------------------------------------------------------ the client's maps
        // name -> the folder its textures are named with, and whether it was lit with the
        // 300 / 160 / (256, -256, 128) setting instead of 300 / 130 / (0, -372, -93)  (KPT client)
        static readonly Dictionary<string, (string dir, bool b160)> Maps = new Dictionary<string, (string, bool)>(StringComparer.OrdinalIgnoreCase)
        {
            { "Login", (@"cSelect\", true) },
            { "ancientW", (@"field\ancientW\", false) },
            { "Boss", (@"field\Boss\", false) },
            { "dark_boss", (@"field\boss\", false) },
            { "castle", (@"field\castle\", false) },
            { "Dcave", (@"field\cave\", false) },
            { "Mcave", (@"field\cave\", false) },
            { "Tcave", (@"field\cave\", false) },
            { "CrystalNest", (@"field\CrystalNest\", false) },
            { "De-1", (@"field\desert\", false) },
            { "De-2", (@"field\desert\", false) },
            { "De-3", (@"field\desert\", false) },
            { "De-4", (@"field\desert\", false) },
            { "Dun-6a", (@"field\dungeon\", false) },
            { "dun-1", (@"field\dungeon\", false) },
            { "dun-2", (@"field\dungeon\", false) },
            { "dun-3", (@"field\dungeon\", false) },
            { "dun-4", (@"field\dungeon\", false) },
            { "dun-5", (@"field\dungeon\", false) },
            { "Endless_4", (@"field\endless\", false) },
            { "dun-7", (@"field\endless\", false) },
            { "dun-8", (@"field\endless\", false) },
            { "dun-9", (@"field\endless\", false) },
            { "fall_game", (@"field\Fall_Game\", false) },
            { "fore-1", (@"field\forest\", false) },
            { "fore-2", (@"field\forest\", false) },
            { "fore-3", (@"field\forest\", false) },
            { "village-1", (@"field\forest\", true) },
            { "forever-fall-01", (@"field\forever-fall\", false) },
            { "forever-fall-02", (@"field\forever-fall\", false) },
            { "forever-fall-03", (@"field\forever-fall\", true) },
            { "forever-fall-04", (@"field\forever-fall\", true) },
            { "pilai", (@"field\forever-fall\", true) },
            { "Greedy", (@"field\Greedy\", false) },
            { "HeartOfFire", (@"field\HeartOfFire\", false) },
            { "ice1", (@"field\Ice\", false) },
            { "ice_2", (@"field\Ice\", false) },
            { "ice_ura", (@"field\Ice\", true) },
            { "iron-1", (@"field\Iron\", false) },
            { "iron-2", (@"field\Iron\", false) },
            { "LandofNurwn", (@"field\LandofNurwn\", false) },
            { "lostisland", (@"field\lost\", false) },
            { "lost_temple", (@"field\Losttemple\", false) },
            { "mine-1", (@"field\Mine\", false) },
            { "oblivion", (@"field\oblivion\", false) },
            { "quest_IV", (@"field\quest\", false) },
            { "village-2", (@"field\ricarten\", false) },
            { "office", (@"field\room\", false) },
            { "ruin-1", (@"field\Ruin\", false) },
            { "ruin-2", (@"field\Ruin\", true) },
            { "ruin-3", (@"field\Ruin\", false) },
            { "ruin-4", (@"field\Ruin\", false) },
            { "R_Ground", (@"field\R_Ground\", false) },
            { "SeaA", (@"field\SeaA\", false) },
            { "Stemple", (@"field\SeaA\", false) },
            { "Slab", (@"field\Slab\", false) },
            { "sod-1", (@"field\Sod\", false) },
            { "sod-2", (@"field\Sod\", false) },
            { "swamp", (@"field\swamp\", false) },
            { "stage", (@"StartImage\Opening\map\", true) },
        };

        public static bool KnownMap(string name, out string dir, out bool b160)
        {
            dir = ""; b160 = false;
            if (name == null || !Maps.TryGetValue(name, out var m)) return false;
            dir = m.dir; b160 = m.b160;
            return true;
        }

        public static void SetLighting(EncodeOptions o, bool b160)
        {
            o.Contrast = 300;
            if (b160) { o.Bright = 160; o.LightX = 256; o.LightY = -256; o.LightZ = 128; }
            else { o.Bright = 130; o.LightX = 0; o.LightY = -372; o.LightZ = -93; }
        }

        /// <summary>The lighting a map .smd was built with (to rebuild it the same way).</summary>
        public static bool ReadLighting(string smdPath, EncodeOptions o)
        {
            try
            {
                if (!File.Exists(smdPath) || Smd.KindOf(smdPath) != SmdKind.Stage) return false;
                var b = new byte[Smd.FileHeaderSize + 0x40074];
                using (var f = File.OpenRead(smdPath)) if (f.Read(b, 0, b.Length) < b.Length) return false;
                int s = Smd.FileHeaderSize;
                o.Contrast = Bin.I(b, s + 0x40048); o.Bright = Bin.I(b, s + 0x4004C);
                o.LightX = Bin.I(b, s + 0x40050); o.LightY = Bin.I(b, s + 0x40054); o.LightZ = Bin.I(b, s + 0x40058);
                if (o.Contrast == 0) { SetLighting(o, false); return false; }
                return true;
            }
            catch (Exception) { return false; }
        }

        /// <summary>What the .ase holds, from a quick look: a map (vertex colours or lights, no bones
        /// or animation) or a model.  hint = the map's name in files from our tools ("PT_village-2...").</summary>
        public static bool LooksLikeStage(string asePath, out string hint)
        {
            hint = null;
            bool col = false, light = false, anim = false;
            foreach (var line in File.ReadLines(asePath, Bin.Latin1))
            {
                string t = line.TrimStart();
                if (t.StartsWith("*MESH_NUMCVERTEX", StringComparison.Ordinal)) { if (Atoi(t.Substring(16)) > 0) col = true; }
                else if (t.StartsWith("*LIGHTOBJECT", StringComparison.Ordinal)) light = true;
                else if (t.StartsWith("*TM_ANIMATION", StringComparison.Ordinal) || t.StartsWith("*PHYSIQUE", StringComparison.Ordinal) ||
                         t.StartsWith("*PT_ANIMATION", StringComparison.Ordinal) || t.StartsWith("*SKIN", StringComparison.Ordinal)) anim = true;
                else if (hint == null && t.StartsWith("*MATERIAL_NAME", StringComparison.Ordinal))
                {
                    int i = t.IndexOf("PT_", StringComparison.Ordinal);
                    if (i >= 0)
                    {
                        string n = t.Substring(i + 3).TrimEnd('"', ' ', '\t');
                        var m = System.Text.RegularExpressions.Regex.Match(n, @"^(.+?)_\d{3}(_|$)");
                        hint = m.Success ? m.Groups[1].Value : n;
                    }
                }
            }
            if (anim) return false;
            return col || light || (hint != null && Maps.ContainsKey(hint));
        }

        // ------------------------------------------------------------------ the whole stage
        /// <summary>True when our decoder or one of our exporters wrote the file.</summary>
        public static bool IsOwnFile(string asePath)
        {
            using (var f = new StreamReader(asePath, Bin.Latin1))
                for (int i = 0; i < 5; i++)
                {
                    string l = f.ReadLine();
                    if (l == null) break;
                    if (l.StartsWith("*COMMENT", StringComparison.Ordinal) && (l.Contains("PT smd2ase") || l.Contains("PT ASE Exporter"))) return true;
                }
            return false;
        }

        /// <summary>Build a map (.smd "SMD Stage data Ver 0.72") from an .ase, the way the game does.</summary>
        public static EncodeResult Stage(string asePath, string smdPath, EncodeOptions opt = null)
        {
            opt = opt ?? new EncodeOptions();
            var res = new EncodeResult { Kind = "stage" };
            bool own = opt.OwnFile ?? IsOwnFile(asePath);
            res.OwnFile = own;
            string dataDir = opt.DataDir ?? "";
            if (dataDir.Length > 0 && !dataDir.EndsWith("\\")) dataDir += "\\";
            var rd = new Lines(asePath);

            // pass 1: materials, and which objects have a mesh
            MatList ml = null;
            var objFlag = new List<bool>();
            while (rd.Next(out string line))
            {
                int p = 0;
                string decode = Word(line, ref p);
                if (decode == "*MATERIAL_LIST") ml = ReadMaterials(rd, dataDir, own);
                if (decode == "*GEOMOBJECT")
                {
                    int strLevel = 0, nV = -1, nF = -1;
                    while (true)
                    {
                        string l2 = rd.Need();
                        int q = 0;
                        string d2 = Word(l2, ref q);
                        if (d2 == "*MESH_NUMVERTEX") nV = Atoi(Word(l2, ref q));
                        if (d2 == "*MESH_NUMFACES") nF = Atoi(Word(l2, ref q));
                        string w2 = Word(l2, ref q);
                        if (d2 == "{" || w2 == "{") strLevel++;
                        if (d2 == "}" || w2 == "}") { strLevel--; if (strLevel < 0) break; }
                    }
                    objFlag.Add(nV != 0 && nF != 0);
                }
            }
            if (ml == null) throw new SmdException("the .ase has no *MATERIAL_LIST (the game needs one to build a map)");

            // pass 2: lights and meshes
            var st = new StageBuild();
            var lights = new List<int[]>();
            rd.Rewind();
            int obj = 0;
            while (rd.Next(out string line))
            {
                int p = 0;
                string decode = Word(line, ref p);
                if (decode == "*LIGHTOBJECT") lights.Add(ReadLight(rd, own));
                if (decode == "*GEOMOBJECT")
                {
                    if (obj < objFlag.Count && objFlag[obj]) { ReadGeomObject(rd, st, ml, own, opt.SinglePrecision, res); res.Objects++; }
                    else
                    {
                        res.Skipped++;
                        int strLevel = 0;
                        while (true)
                        {
                            string l2 = rd.Need();
                            int q = 0;
                            string d2 = Word(l2, ref q), w2 = Word(l2, ref q);
                            if (d2 == "{" || w2 == "{") strLevel++;
                            if (d2 == "}" || w2 == "}") { strLevel--; if (strLevel < 0) break; }
                        }
                    }
                    obj++;
                }
            }

            int nVertex = st.X.Count, nFace = st.Face.Count;
            res.TooManyVertices = nVertex > 65535;                 // (faces store vertex numbers in 16 bits)
            res.TooManyFaces = !opt.WideAreas && nFace > 65535;    // (2012 area lists store face numbers in 16 bits)

            // area grid (SetupPolyAreas): 64-unit cells, 256 x 256 wrapping
            var areaCount = new int[256, 256];
            var faceCells = new List<(int x, int y)>[nFace];
            int lastAreaListCnt = 0;
            for (int f = 0; f < nFace; f++)
            {
                int l = 0, r = 0, t = 0, b = 0;
                for (int k = 0; k < 3; k++)
                {
                    int v = st.Face[f][k];
                    int x = st.X[v] >> FLOATNS, z = st.Z[v] >> FLOATNS;
                    if (k == 0) { l = r = x; t = b = z; }
                    else { if (x < l) l = x; if (x > r) r = x; if (z < t) t = z; if (z > b) b = z; }
                }
                l >>= 6; r >>= 6; t >>= 6; b >>= 6; r++; b++;
                var cells = new List<(int, int)>();
                for (int cx = l; cx < r; cx++)
                    for (int cy = t; cy < b; cy++)
                    {
                        cells.Add((cx & 0xFF, cy & 0xFF));
                        areaCount[cx & 0xFF, cy & 0xFF]++;
                    }
                faceCells[f] = cells;
                lastAreaListCnt = cells.Count;
            }
            var area = new List<int>[256, 256];
            for (int f = 0; f < nFace; f++)
                foreach (var c in faceCells[f])
                {
                    if (area[c.x, c.y] == null) area[c.x, c.y] = new List<int>();
                    area[c.x, c.y].Add(f);
                }
            Crowded(st, area, res);

            // SetVertexShade
            var normal = new int[nVertex][];
            var normalCnt = new int[nVertex];
            for (int i = 0; i < nVertex; i++) normal[i] = new int[3];
            var pp = new int[3][];
            for (int k = 0; k < 3; k++) pp[k] = new int[3];
            var pn = new int[3];
            unchecked
            {
                for (int f = 0; f < nFace; f++)
                {
                    for (int k = 0; k < 3; k++)
                    {
                        int v = st.Face[f][k];
                        pp[k][0] = st.X[v] >> FLOATNS; pp[k][1] = st.Y[v] >> FLOATNS; pp[k][2] = st.Z[v] >> FLOATNS;
                    }
                    SetNormal(pp[0], pp[1], pp[2], pn, opt.SinglePrecision);
                    var fnrm = st.Normal[f];
                    fnrm[0] = (short)pn[0]; fnrm[1] = (short)pn[1]; fnrm[2] = (short)pn[2];
                    for (int k = 0; k < 3; k++)
                    {
                        int v = st.Face[f][k];
                        normal[v][0] += pn[0]; normal[v][1] += pn[1]; normal[v][2] += pn[2];
                        normalCnt[v]++;
                    }
                }
                bool setLight = !ml.LightMapStage;
                for (int i = 0; i < nVertex; i++)
                {
                    if (normalCnt[i] > 0) for (int c = 0; c < 3; c++) normal[i][c] /= normalCnt[i];
                    if (!setLight || (own && st.Baked[i])) continue;
                    int gShade = (normal[i][0] * opt.LightX + normal[i][1] * opt.LightY + normal[i][2] * opt.LightZ) >> FLOATNS;
                    gShade /= opt.Contrast;
                    gShade += opt.Bright;
                    var col = st.Col[i];
                    col[SMC_R] = (short)((col[SMC_R] * gShade) >> 8);
                    col[SMC_G] = (short)((col[SMC_G] * gShade) >> 8);
                    col[SMC_B] = (short)((col[SMC_B] * gShade) >> 8);
                    col[SMC_A] = 255;
                }
                for (int f = 0; f < nFace; f++)
                {
                    int m = st.Face[f][3];
                    float transp = m >= 0 && m < ml.Mats.Count ? ml.Mats[m].F(Mat.Transparency) : 0f;
                    if (transp > 0)
                        for (int k = 0; k < 3; k++)
                            st.Col[st.Face[f][k]][SMC_A] = (short)(255 - (byte)Trunc(transp * 255f));
                }

                // static lights, then dynamic ones
                foreach (var L in lights)
                {
                    if ((L[0] & 0x80000) != 0) continue;
                    int dRange = ((L[4] / 256) * 72) >> FLOATNS;
                    dRange *= dRange;
                    for (int i = 0; i < nVertex; i++)
                    {
                        int x = (L[1] - st.X[i]) >> FLOATNS, y = (L[2] - st.Y[i]) >> FLOATNS, z = (L[3] - st.Z[i]) >> FLOATNS;
                        int ddist = x * x + y * y + z * z;
                        if (ddist >= dRange || dRange == 0) continue;
                        int dist = Trunc(Math.Sqrt(ddist));
                        int eLight = (L[4] >> FLOATNS) - dist;
                        eLight = FONE - ((eLight << FLOATNS) / dRange);
                        var col = st.Col[i];
                        col[SMC_R] = (short)(col[SMC_R] + ((L[5] * eLight) >> FLOATNS));
                        col[SMC_G] = (short)(col[SMC_G] + ((L[6] * eLight) >> FLOATNS));
                        col[SMC_B] = (short)(col[SMC_B] + ((L[7] * eLight) >> FLOATNS));
                        if (col[SMC_R] > 360) col[SMC_R] = 360;
                        if (col[SMC_G] > 360) col[SMC_G] = 360;
                        if (col[SMC_B] > 360) col[SMC_B] = 360;
                    }
                }
            }
            foreach (var L in lights) if ((L[0] & 0x80000) != 0) st.Lights.Add(L);

            Write(smdPath, st, ml, area, lastAreaListCnt, opt);

            res.Vertices = nVertex; res.Faces = nFace; res.TexLinks = st.TexUV.Count;
            res.Materials = ml.Mats.Count; res.Lights = lights.Count; res.DynLights = st.Lights.Count;
            res.Textures = ml.Tex.List.Count;
            return res;
        }

        /// <summary>For walking, the game gathers the faces of the 2 x 2 cells around a character that
        /// have a corner within its height (MakeAreaFaceList) into a list of 1000 (SMSFACE_MAX in the
        /// 2012 code, never checked: more crashes those clients when a character comes there).  Every
        /// map of 2012 stays at 991 or less; newer clients keep more.</summary>
        public const int CrowdedLimit = 1000;

        static void Crowded(StageBuild st, List<int>[,] area, EncodeResult res)
        {
            const int H = 64 * FONE;                              // (a character's height band, about)
            int nFace = st.Face.Count;
            var mark = new int[nFace];
            int stamp = 0;
            var faces = new List<int>();
            for (int x = 0; x < 256; x++)
                for (int y = 0; y < 256; y++)
                {
                    if (area[x, y] == null) continue;
                    stamp++;
                    faces.Clear();
                    for (int dx = 0; dx < 2; dx++)
                        for (int dy = 0; dy < 2; dy++)
                        {
                            var l = area[(x + dx) & 0xFF, (y + dy) & 0xFF];
                            if (l == null) continue;
                            foreach (int f in l) if (mark[f] != stamp) { mark[f] = stamp; faces.Add(f); }
                        }
                    if (faces.Count <= Math.Max(CrowdedLimit, res.CrowdedFaces)) continue;
                    // the height that takes in the most faces
                    var ys = new List<int>();
                    foreach (int f in faces) for (int k = 0; k < 3; k++) ys.Add(st.Y[st.Face[f][k]]);
                    ys.Sort();
                    int step = Math.Max(1, ys.Count / 200);
                    for (int i = 0; i < ys.Count; i += step)
                    {
                        int Y = ys[i], n = 0;
                        foreach (int f in faces)
                            for (int k = 0; k < 3; k++)
                            {
                                int vy = st.Y[st.Face[f][k]];
                                if (vy > Y - H && vy < Y + H) { n++; break; }
                            }
                        if (n > res.CrowdedFaces)
                        {
                            res.CrowdedFaces = n;
                            int v = st.Face[faces[0]][0];
                            res.CrowdedX = st.X[v] / 256.0;
                            res.CrowdedY = st.Z[v] / 256.0;            // (map z = 3ds Max Y)
                        }
                    }
                }
        }

        // ------------------------------------------------------------------ smSTAGE3D::SaveFile
        static void Write(string path, StageBuild st, MatList ml, List<int>[,] area, int areaListCnt, EncodeOptions opt)
        {
            int nVertex = st.X.Count, nFace = st.Face.Count, nTexLink = st.TexUV.Count, nLight = st.Lights.Count;
            var ms = new MemoryStream(1 << 20);
            var w = new BinaryWriter(ms);

            // the material group's size on file
            int groupSize = Smd.MatGroupHeaderSize;
            var names = new List<byte[]>();
            foreach (var m in ml.Mats)
            {
                groupSize += Smd.MaterialSize;
                byte[] nb = new byte[0];
                if (m.I(Mat.InUse) != 0)
                {
                    var s = new MemoryStream();
                    int tc = Math.Min(Math.Max(m.I(Mat.TextureCounter), 0), 8), ac = Math.Min(Math.Max(m.I(Mat.AnimTexCounter), 0), 32);
                    for (int t = 0; t < tc + ac; t++)
                    {
                        int h = t < tc ? m.Tex[t] : m.Anim[t - tc];
                        var (n, na) = h >= 0 ? ml.Tex.List[h] : ("", "");
                        byte[] a = Bin.Latin1.GetBytes(n), b = Bin.Latin1.GetBytes(na);
                        s.Write(a, 0, a.Length); s.WriteByte(0);
                        s.Write(b, 0, b.Length); s.WriteByte(0);
                    }
                    nb = s.ToArray();
                    groupSize += 4 + nb.Length;
                }
                names.Add(nb);
            }

            // smDFILE_HEADER
            var hdr = new byte[Smd.FileHeaderSize];
            Encoding.ASCII.GetBytes(Smd.StageHeader).CopyTo(hdr, 0);
            BitConverter.GetBytes(ml.Mats.Count).CopyTo(hdr, 28);
            BitConverter.GetBytes(Smd.FileHeaderSize).CopyTo(hdr, 32);
            BitConverter.GetBytes(Smd.FileHeaderSize + groupSize).CopyTo(hdr, 36);
            w.Write(hdr);

            // smSTAGE3D
            const int stageSize = 0x40074;
            var S = new byte[stageSize];
            void PutI(int o, int v) => BitConverter.GetBytes(v).CopyTo(S, o);
            void PutU(int o, uint v) => BitConverter.GetBytes(v).CopyTo(S, o);
            int wb = 0, es = opt.WideAreas ? 4 : 2;                  // (entry size: DWORD in current clients, WORD in 2012)
            for (int y = 0; y < 256; y++)
                for (int x = 0; x < 256; x++)
                    if (area[x, y] != null)
                    {
                        PutU(4 + (x * 256 + y) * 4, (uint)(PtrAreaBuff + wb * es));
                        wb += es * area[x, y].Count + 1;                  // (the game counts faces with the entry pointer: +es per face)
                    }
            PutU(0x40004, PtrAreaList);
            PutI(0x40008, areaListCnt);
            PutU(0x40018, PtrVertex);
            PutU(0x4001C, PtrFace);
            PutU(0x40020, PtrTexLink);
            PutU(0x40024, nLight > 0 ? PtrLight : 0);
            PutU(0x40028, PtrGroup);
            PutU(0x4002C, PtrStageObject);
            PutU(0x40030, PtrMaterial);
            PutI(0x40034, nVertex);
            PutI(0x40038, nFace);
            PutI(0x4003C, nTexLink);
            PutI(0x40040, nLight);
            PutI(0x40048, opt.Contrast);
            PutI(0x4004C, opt.Bright);
            PutI(0x40050, opt.LightX);
            PutI(0x40054, opt.LightY);
            PutI(0x40058, opt.LightZ);
            PutU(0x4005C, PtrAreaBuff);
            PutI(0x40060, wb);
            PutI(0x40064, st.Left);
            PutI(0x40068, st.Top);
            PutI(0x4006C, st.Right);
            PutI(0x40070, st.Bottom);
            w.Write(S);

            // smMATERIAL_GROUP
            w.Write(0);
            w.Write(PtrMaterial);
            w.Write(ml.Mats.Count);
            w.Write(ml.ReformTexture);
            w.Write(ml.Mats.Count);
            w.Write(0);
            w.Write(new byte[64]);
            for (int i = 0; i < ml.Mats.Count; i++)
            {
                var m = ml.Mats[i];
                var b = (byte[])m.B.Clone();
                for (int t = 0; t < 8; t++)
                    if (m.Tex[t] >= 0) BitConverter.GetBytes((uint)(PtrTexture + m.Tex[t] * TextureHandleSize)).CopyTo(b, Mat.smTexture + 4 * t);
                for (int t = 0; t < 32; t++)
                    if (m.Anim[t] >= 0) BitConverter.GetBytes((uint)(PtrTexture + m.Anim[t] * TextureHandleSize)).CopyTo(b, Mat.smAnimTexture + 4 * t);
                w.Write(b);
                if (m.I(Mat.InUse) != 0) { w.Write(names[i].Length); w.Write(names[i]); }
            }

            // vertices, faces, texture links, lights
            for (int i = 0; i < nVertex; i++)
            {
                w.Write(0); w.Write(0);
                w.Write(st.X[i]); w.Write(st.Y[i]); w.Write(st.Z[i]);
                var c = st.Col[i];
                w.Write(c[0]); w.Write(c[1]); w.Write(c[2]); w.Write(c[3]);
            }
            for (int f = 0; f < nFace; f++)
            {
                var fc = st.Face[f];
                w.Write(0); w.Write(0);
                w.Write((ushort)fc[0]); w.Write((ushort)fc[1]); w.Write((ushort)fc[2]); w.Write((ushort)fc[3]);
                w.Write(st.FaceTex[f] >= 0 ? (uint)(PtrTexLink + st.FaceTex[f] * 32) : 0u);
                var n = st.Normal[f];
                w.Write(n[0]); w.Write(n[1]); w.Write(n[2]); w.Write(n[3]);
            }
            for (int t = 0; t < nTexLink; t++)
            {
                var uv = st.TexUV[t];
                for (int k = 0; k < 6; k++) w.Write(uv[k]);
                w.Write(st.TexH[t]);
                w.Write(st.TexNext[t] >= 0 ? (uint)(PtrTexLink + st.TexNext[t] * 32) : 0u);
            }
            foreach (var L in st.Lights)
            {
                for (int k = 0; k < 5; k++) w.Write(L[k]);
                w.Write((short)L[5]); w.Write((short)L[6]); w.Write((short)L[7]); w.Write((short)0);
            }

            // area lists
            for (int y = 0; y < 256; y++)
                for (int x = 0; x < 256; x++)
                    if (area[x, y] != null)
                    {
                        var l = area[x, y];
                        w.Write(l.Count + 1);
                        if (opt.WideAreas) { w.Write(l.Count); foreach (int f in l) w.Write(f); }
                        else { w.Write((ushort)l.Count); foreach (int f in l) w.Write((ushort)f); }
                    }

            w.Flush();
            string d = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(d)) Directory.CreateDirectory(d);
            File.WriteAllBytes(path, ms.ToArray());
        }
    }
}
