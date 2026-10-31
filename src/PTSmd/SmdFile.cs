// Reader for Priston Tale SMD / SMB binary files.
//
//   "SMD Stage data Ver 0.72"  - field/terrain meshes (one merged mesh per map)
//   "SMD Model data Ver 0.62"  - objects (animated map props) and .smb bone files
//
// Both the 2012-era files and the current KPT client share this layout; nothing is
// encrypted.  Verified against the original 3ds Max ASE exports (371/378 exact).
//
// Coordinates: stage vertices are int(x*256), int(z*256), int(y*256) of the Max
// position (Y/Z swapped).  Model vertices are local (Max axes, x256) and are
// brought back to world space with inverse(TmInvert rotation) + Tm translation.

using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace PTSmd
{
    public class SmdException : Exception
    {
        public SmdException(string msg) : base(msg) { }
    }

    public enum SmdKind { Unknown, Stage, Model }

    internal static class Bin
    {
        public static int I(byte[] b, int o) => BitConverter.ToInt32(b, o);
        public static uint U(byte[] b, int o) => BitConverter.ToUInt32(b, o);
        public static ushort W(byte[] b, int o) => BitConverter.ToUInt16(b, o);
        public static short S(byte[] b, int o) => BitConverter.ToInt16(b, o);
        public static double F(byte[] b, int o) => BitConverter.ToSingle(b, o);

        public static readonly Encoding Latin1 = Encoding.GetEncoding(28591);

        public static string CStr(byte[] b, int o, int max)
        {
            int n = 0;
            while (n < max && o + n < b.Length && b[o + n] != 0) n++;
            return Latin1.GetString(b, o, n);
        }

        public static bool StartsWith(byte[] b, string s)
        {
            if (b.Length < s.Length) return false;
            for (int i = 0; i < s.Length; i++) if (b[i] != (byte)s[i]) return false;
            return true;
        }
    }

    /// <summary>One TexLink entry: per-corner u[3], v[3] (SMD convention).</summary>
    public struct TexLayer
    {
        public double U0, U1, U2, V0, V1, V2;
    }

    public static class Smd
    {
        public const string StageHeader = "SMD Stage data Ver 0.72";
        public const string ModelHeader = "SMD Model data Ver 0.62";

        internal const int FileHeaderSize = 0x22C;
        internal const int MatGroupHeaderSize = 88;
        internal const int MaterialSize = 320;

        public static SmdKind KindOf(string path)
        {
            byte[] h = new byte[24];
            using (var f = File.OpenRead(path))
            {
                int n = f.Read(h, 0, 24);
                if (n < 23) return SmdKind.Unknown;
            }
            if (Bin.StartsWith(h, StageHeader)) return SmdKind.Stage;
            if (Bin.StartsWith(h, ModelHeader)) return SmdKind.Model;
            return SmdKind.Unknown;
        }

        internal static List<Material> ReadMaterials(byte[] b, ref int off, int count)
        {
            var mats = new List<Material>(count);
            for (int m = 0; m < count; m++)
            {
                if (off + MaterialSize > b.Length) throw new SmdException("material table truncated at #" + m);
                int inUse = Bin.I(b, off);
                int start = off;
                off += MaterialSize;
                string[] names = new string[0];
                if (inUse != 0)
                {
                    int sz = Bin.I(b, off);
                    off += 4;
                    if (sz < 0 || off + sz > b.Length) throw new SmdException("material strings truncated at #" + m);
                    names = Bin.Latin1.GetString(b, off, sz).Split('\0');
                    off += sz;
                }
                mats.Add(new Material(m, b, start, inUse != 0 ? names : new string[0]));
            }
            return mats;
        }

        /// <summary>Follow a face's TexLink chain (pointers are relative to basePtr).</summary>
        internal static List<TexLayer> WalkTexLinks(byte[] b, int tlOff, int nTex, uint basePtr, uint ptr)
        {
            var outl = new List<TexLayer>(2);
            while (ptr != 0 && outl.Count < 8)
            {
                long rel = (long)ptr - basePtr;
                if (rel < 0 || rel % 32 != 0) break;
                long idx = rel / 32;
                if (idx >= nTex) break;
                int o = tlOff + (int)idx * 32;
                outl.Add(new TexLayer
                {
                    U0 = Bin.F(b, o), U1 = Bin.F(b, o + 4), U2 = Bin.F(b, o + 8),
                    V0 = Bin.F(b, o + 12), V1 = Bin.F(b, o + 16), V2 = Bin.F(b, o + 20)
                });
                ptr = Bin.U(b, o + 28);
            }
            return outl;
        }
    }

    public class Light
    {
        public int Type;
        public double X, Y, Z;          // Max axes
        public double Range;
        public int R, G, B;

        static readonly (int bit, string name)[] FlagNames = { (0x1, "night:"), (0x2, "lens:"), (0x8, "obj:") };

        public Light(byte[] b, int o)
        {
            Type = Bin.I(b, o);
            int x = Bin.I(b, o + 4), y = Bin.I(b, o + 8), z = Bin.I(b, o + 12);
            X = x / 256.0; Y = z / 256.0; Z = y / 256.0;
            Range = Bin.I(b, o + 16) / 256.0;
            R = Bin.S(b, o + 20); G = Bin.S(b, o + 22); B = Bin.S(b, o + 24);
        }

        public string Name()
        {
            var sb = new StringBuilder();
            foreach (var f in FlagNames) if ((Type & f.bit) != 0) sb.Append(f.name);
            return sb.Length > 0 ? sb.ToString() : "dynamic:";
        }
    }

    public struct StageFace
    {
        public int A, B, C, Mat;
    }

    /// <summary>A parsed 'SMD Stage data' file. Geometry in 3ds Max axes.</summary>
    public class Stage
    {
        const int NVertex = 0x40260, NFace = 0x40264, NTexLink = 0x40268, NLight = 0x4026C;
        const int TexLinkPtr = 0x4024C, MatGroup = 0x402A0, MatCount = 0x402A8;

        public string Path;
        public List<Material> Materials;
        public double[] Positions;      // xyz triples
        public short[] Colors;          // rgba quads (sDef_Color)
        public StageFace[] Faces;
        public List<TexLayer>[] FaceUVs;
        public List<Light> Lights = new List<Light>();
        public int Contrast, Bright;

        public Stage(string path)
        {
            Path = path;
            byte[] b = File.ReadAllBytes(path);
            if (!Bin.StartsWith(b, Smd.StageHeader)) throw new SmdException(path + ": not a stage SMD");
            int nV = Bin.I(b, NVertex), nF = Bin.I(b, NFace), nT = Bin.I(b, NTexLink), nL = Bin.I(b, NLight);
            Contrast = Bin.I(b, 0x40274);
            Bright = Bin.I(b, 0x40278);
            int nMat = Bin.I(b, MatCount);
            if (nV < 0 || nF < 0 || nT < 0 || nL < 0 || nMat < 0 || nMat > 100000) throw new SmdException(path + ": bad header");
            int off = MatGroup + Smd.MatGroupHeaderSize;
            Materials = Smd.ReadMaterials(b, ref off, nMat);
            long need = (long)off + nV * 28L + nF * 28L + nT * 32L + nL * 28L;
            if (need > b.Length) throw new SmdException(string.Format("{0}: file truncated (need {1}, have {2})", path, need, b.Length));

            Positions = new double[nV * 3];
            Colors = new short[nV * 4];
            for (int i = 0; i < nV; i++, off += 28)
            {
                int x = Bin.I(b, off + 8), y = Bin.I(b, off + 12), z = Bin.I(b, off + 16);
                Positions[i * 3] = x / 256.0;
                Positions[i * 3 + 1] = z / 256.0;
                Positions[i * 3 + 2] = y / 256.0;
                for (int k = 0; k < 4; k++) Colors[i * 4 + k] = Bin.S(b, off + 20 + 2 * k);
            }
            int faceOff = off;
            int tlOff = faceOff + nF * 28;
            uint basePtr = Bin.U(b, TexLinkPtr);
            Faces = new StageFace[nF];
            FaceUVs = new List<TexLayer>[nF];
            for (int i = 0; i < nF; i++)
            {
                int o = faceOff + i * 28;
                Faces[i] = new StageFace { A = Bin.W(b, o + 8), B = Bin.W(b, o + 10), C = Bin.W(b, o + 12), Mat = Bin.W(b, o + 14) };
                FaceUVs[i] = Smd.WalkTexLinks(b, tlOff, nT, basePtr, Bin.U(b, o + 16));
            }
            off = tlOff + nT * 32;
            for (int k = 0; k < nL; k++, off += 28) Lights.Add(new Light(b, off));
        }

        public int MaxLayers()
        {
            int m = 0;
            foreach (var l in FaceUVs) if (l.Count > m) m = l.Count;
            return m;
        }
    }

    public class ModelObject
    {
        public string Name = "", Parent = "";
        public int[,] Tm = new int[4, 4];
        public int[,] TmInv = new int[4, 4];
        public double[] Quat = new double[4];
        public double[] Scale = new double[3];
        public double[] Pos = new double[3];
        public double[] LocalVerts;                 // xyz triples
        public StageFace[] Faces;
        public List<TexLayer>[] FaceUVs;
        public List<(int t, double x, double y, double z, double w)> RotKeys = new List<(int, double, double, double, double)>();
        public List<(int t, double x, double y, double z)> PosKeys = new List<(int, double, double, double)>();
        public List<(int t, double x, double y, double z)> ScaleKeys = new List<(int, double, double, double)>();
        public string[] Physique;                   // bone name per vertex, or null
        /// <summary>TmPrevRot: the local rotation (rows, 4x4 floats) the game uses at each rotation key.</summary>
        public List<float[]> PrevRot = new List<float[]>();
        /// <summary>Per glued motion piece: {start tick, end tick, first key, key count} for rot / pos / scale.</summary>
        public int[][][] Frames = new int[3][][];
    }

    /// <summary>A parsed 'SMD Model data' file (.smd object or .smb bones).</summary>
    public class Model
    {
        const int ObjSize = 2236;
        public string Path;
        public List<Material> Materials = new List<Material>();
        public List<ModelObject> Objects = new List<ModelObject>();
        public int FrameCounter;

        public Model(string path)
        {
            Path = path;
            byte[] b = File.ReadAllBytes(path);
            if (!Bin.StartsWith(b, Smd.ModelHeader)) throw new SmdException(path + ": not a model SMD");
            int nObj = Bin.I(b, 0x18), nMat = Bin.I(b, 0x1C);
            if (nObj < 0 || nObj > 10000 || nMat < 0 || nMat > 100000) throw new SmdException(path + ": bad header counts");
            FrameCounter = Bin.I(b, 0x28);
            int npc = Math.Max(0, Math.Min(32, FrameCounter));
            int off = Smd.FileHeaderSize + nObj * 40;
            if (nMat > 0)
            {
                off += Smd.MatGroupHeaderSize;
                Materials = Smd.ReadMaterials(b, ref off, nMat);
            }
            for (int k = 0; k < nObj; k++)
            {
                if (off + ObjSize > b.Length || b[off] != 'D' || b[off + 1] != 'C' || b[off + 2] != 'B')
                    throw new SmdException(path + ": object " + k + " header invalid");
                var o = new ModelObject();
                o.Name = Bin.CStr(b, off + 172, 32);
                o.Parent = Bin.CStr(b, off + 204, 32);
                int nV = Bin.I(b, off + 84), nF = Bin.I(b, off + 80), nT = Bin.I(b, off + 92);
                int nR = Bin.I(b, off + 684), nP = Bin.I(b, off + 688), nS = Bin.I(b, off + 692);
                bool phys = Bin.I(b, off + 16) != 0;
                // the game only looks at the keys of the motion piece being played
                for (int t = 0; t < 3; t++)
                {
                    o.Frames[t] = new int[npc][];
                    for (int i = 0; i < npc; i++)
                    {
                        int fo = off + 696 + 512 * t + 16 * i;
                        o.Frames[t][i] = new[] { Bin.I(b, fo), Bin.I(b, fo + 4), Bin.I(b, fo + 8), Bin.I(b, fo + 12) };
                    }
                }
                for (int r = 0; r < 4; r++)
                    for (int c = 0; c < 4; c++)
                    {
                        o.Tm[r, c] = Bin.I(b, off + 240 + 16 * r + 4 * c);
                        o.TmInv[r, c] = Bin.I(b, off + 304 + 16 * r + 4 * c);
                    }
                for (int i = 0; i < 4; i++) o.Quat[i] = Bin.F(b, off + 628 + 4 * i);
                for (int i = 0; i < 3; i++)
                {
                    o.Scale[i] = Bin.I(b, off + 644 + 4 * i) / 256.0;
                    o.Pos[i] = Bin.I(b, off + 656 + 4 * i) / 256.0;
                }
                uint basePtr = Bin.U(b, off + 12);
                int p = off + ObjSize;
                long need = (long)p + nV * 24L + nF * 36L + nT * 32L + nR * 84L + nP * 16L + nS * 16L + (phys ? nV * 32L : 0);
                if (need > b.Length) throw new SmdException(path + ": object " + k + " truncated");
                o.LocalVerts = new double[nV * 3];
                for (int i = 0; i < nV; i++)
                    for (int c = 0; c < 3; c++) o.LocalVerts[i * 3 + c] = Bin.I(b, p + i * 24 + 4 * c) / 256.0;
                p += nV * 24;
                int faceOff = p;
                p += nF * 36;
                int tlOff = p;
                p += nT * 32;
                o.Faces = new StageFace[nF];
                o.FaceUVs = new List<TexLayer>[nF];
                for (int i = 0; i < nF; i++)
                {
                    int fo = faceOff + i * 36;
                    o.Faces[i] = new StageFace { A = Bin.W(b, fo), B = Bin.W(b, fo + 2), C = Bin.W(b, fo + 4), Mat = Bin.W(b, fo + 6) };
                    o.FaceUVs[i] = Smd.WalkTexLinks(b, tlOff, nT, basePtr, Bin.U(b, fo + 32));
                }
                for (int i = 0; i < nR; i++, p += 20)
                    o.RotKeys.Add((Bin.I(b, p), Bin.F(b, p + 4), Bin.F(b, p + 8), Bin.F(b, p + 12), Bin.F(b, p + 16)));
                for (int i = 0; i < nP; i++, p += 16)
                    o.PosKeys.Add((Bin.I(b, p), Bin.F(b, p + 4), Bin.F(b, p + 8), Bin.F(b, p + 12)));
                for (int i = 0; i < nS; i++, p += 16)
                    o.ScaleKeys.Add((Bin.I(b, p), Bin.I(b, p + 4) / 256.0, Bin.I(b, p + 8) / 256.0, Bin.I(b, p + 12) / 256.0));
                for (int i = 0; i < nR; i++, p += 64)
                {
                    var m = new float[16];
                    for (int c = 0; c < 16; c++) m[c] = (float)Bin.F(b, p + 4 * c);
                    o.PrevRot.Add(m);
                }
                if (phys)
                {
                    o.Physique = new string[nV];
                    for (int i = 0; i < nV; i++) o.Physique[i] = Bin.CStr(b, p + 32 * i, 32);
                    p += nV * 32;
                }
                Objects.Add(o);
                off = p;
            }
        }

        public int LastFrameTicks()
        {
            int t = 0;
            foreach (var o in Objects)
            {
                if (o.RotKeys.Count > 0) t = Math.Max(t, o.RotKeys[o.RotKeys.Count - 1].t);
                if (o.PosKeys.Count > 0) t = Math.Max(t, o.PosKeys[o.PosKeys.Count - 1].t);
                if (o.ScaleKeys.Count > 0) t = Math.Max(t, o.ScaleKeys[o.ScaleKeys.Count - 1].t);
            }
            return t;
        }
    }
}
