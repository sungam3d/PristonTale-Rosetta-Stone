// SMD -> ASE conversion (port of tools/ptsmd/convert.py; output is byte-identical).
//
// Conventions in the generated ASE (read by the PT Max/Blender importers and PT's own loader):
//   * one Multi/Sub-Object material per file; sub-material N == SMD material
//   * sub-material names carry PT keyword flags ("wind:", "wall:", "BLEND_LAMP:", "anim8:flame%d.tga:6")
//   * texture layer 0 -> *MAP_DIFFUSE (channel 1); layer k -> *MAP_SELFILLUM (MESH_MAPPINGCHANNEL k+1)
//   * stage vertex colours = the game's baked lighting (sDef_Color / 255)
//   * collision faces ('wall:' / untextured) -> separate "<map>__collision" object

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace PTSmd
{
    public class ConvertOptions
    {
        public string GameRoot;                 // folder containing 'Field' (auto if null)
        public string TextureOut;               // copy+decrypt textures here (null = reference in place)
        public bool SplitCollision = true;
        public bool DropCollision = false;
        public bool SplitObjects = true;        // maps: one object per original part (false = one mesh)
        public bool CompactMaterials = true;
        public bool VertexColors = true;
        public bool ClampColors = true;
        public double ColorScale = 1.0;
        public bool IncludeBones = false;       // (unused since characters always get their skeleton)
        public bool IncludeLights = true;
        public string TextureDirOverride;       // copy every texture flat into this folder
        public string Animation = "auto";       // auto | embed | shared | none
        public string Lod = "high";             // high | all  (monster detail levels)
        public Dictionary<string, SortedSet<string>> MissingTextures;   // texture -> smd names
    }

    public class GeomObject
    {
        public string Name, Parent = "";
        public double[][] Rows = { new double[] { 1, 0, 0 }, new double[] { 0, 1, 0 }, new double[] { 0, 0, 1 } };
        public double[] Pos = { 0.0, 0.0, 0.0 };
        public List<double[]> Verts = new List<double[]>();
        public List<int[]> Faces = new List<int[]>();                  // a, b, c, submat
        public List<double[][]> Channels = new List<double[][]>();     // [ch][face] -> u0,v0,u1,v1,u2,v2
        public List<double[]> Colors;
        public List<(int t, double x, double y, double z)> PosKeys = new List<(int, double, double, double)>();
        public List<(int t, double[] axis, double ang)> RotKeys = new List<(int, double[], double)>();
        public List<(int t, double x, double y, double z)> ScaleKeys = new List<(int, double, double, double)>();
        public bool IsBone;                    // skeleton bone (written as a helper)
        public string[] Physique;              // per-vertex bone name (skinned meshes)
        public GeomObject(string name) { Name = name; }
    }

    public class Scene
    {
        public string Name, Source, Kind;
        public List<Material> Materials = new List<Material>();
        public List<GeomObject> Objects = new List<GeomObject>();
        public List<Light> Lights = new List<Light>();
        public int LastFrame = 100;
        public Dictionary<string, string> TexturePaths = new Dictionary<string, string>();
        public List<string> MissingBoneNames = new List<string>();
        public bool MissingBones => MissingBoneNames.Count > 0;
        public string AnimMode = "none";        // embed | shared | none
        public string AnimFile = "";            // shared motion file (class skeletons)
        public string MotionFile = "";          // the game's separate motion file of a monster (mGknight.ASE ...)
        public string SkeletonFile = "";
        public List<Motion> Motions = new List<Motion>();
        public Rig Rig;
        public Model Skeleton;
        public int FaceCount => Objects.Sum(o => o.Faces.Count);
        public int VertexCount => Objects.Sum(o => o.Verts.Count);
    }

    public static class Converter
    {
        static readonly CultureInfo CI = CultureInfo.InvariantCulture;

        // ------------------------------------------------------------------ math
        static double[][] Inv3(double[][] m)
        {
            double a = m[0][0], b = m[0][1], c = m[0][2];
            double d = m[1][0], e = m[1][1], f = m[1][2];
            double g = m[2][0], h = m[2][1], i = m[2][2];
            double A = e * i - f * h;
            double B = -(d * i - f * g);
            double C = d * h - e * g;
            double det = a * A + b * B + c * C;
            if (Math.Abs(det) < 1e-12)
                return new[] { new double[] { 1, 0, 0 }, new double[] { 0, 1, 0 }, new double[] { 0, 0, 1 } };
            double[][] inv =
            {
                new[] { A, -(b * i - c * h), b * f - c * e },
                new[] { B, a * i - c * g, -(a * f - c * d) },
                new[] { C, -(a * h - b * g), a * e - b * d },
            };
            return inv.Select(r => r.Select(v => v / det).ToArray()).ToArray();
        }

        static double[] Xform(double x, double y, double z, double[][] r, double[] t)
        {
            return new[]
            {
                x * r[0][0] + y * r[1][0] + z * r[2][0] + t[0],
                x * r[0][1] + y * r[1][1] + z * r[2][1] + t[1],
                x * r[0][2] + y * r[1][2] + z * r[2][2] + t[2],
            };
        }

        static (double[] axis, double ang) QuatToAxisAngle(double x, double y, double z, double w)
        {
            w = Math.Max(-1.0, Math.Min(1.0, w));
            double ang = 2.0 * Math.Acos(w);
            double s = Math.Sqrt(Math.Max(0.0, 1.0 - w * w));
            if (s < 1e-7) return (new[] { 0.0, 0.0, 0.0 }, 0.0);
            return (new[] { x / s, y / s, z / s }, ang);
        }

        // Animation key.  atan2 rather than acos(w): the deltas are tiny turns whose
        // w is within float32 rounding of 1.0, so the angle must come from x, y, z.
        static (double[] axis, double ang) KeyAxisAngle(double x, double y, double z, double w)
        {
            double s = Math.Sqrt(x * x + y * y + z * z);
            if (s < 1e-12) return (new[] { 0.0, 0.0, 0.0 }, 0.0);
            return (new[] { x / s, y / s, z / s }, 2.0 * Math.Atan2(s, w));
        }

        /// <summary>(x, y, z, w) of the rotation whose standard (column-vector) matrix is m.</summary>
        static double[] QuatFromMatrix(double m00, double m01, double m02, double m10, double m11, double m12,
                                       double m20, double m21, double m22)
        {
            double tr = m00 + m11 + m22, s;
            double[] q;
            if (tr > 0.0)
            {
                s = Math.Sqrt(tr + 1.0) * 2.0;
                q = new[] { (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s };
            }
            else if (m00 > m11 && m00 > m22)
            {
                s = Math.Sqrt(1.0 + m00 - m11 - m22) * 2.0;
                q = new[] { 0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s };
            }
            else if (m11 > m22)
            {
                s = Math.Sqrt(1.0 + m11 - m00 - m22) * 2.0;
                q = new[] { (m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s };
            }
            else
            {
                s = Math.Sqrt(1.0 + m22 - m00 - m11) * 2.0;
                q = new[] { (m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s };
            }
            double n = Math.Sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            return new[] { q[0] / n, q[1] / n, q[2] / n, q[3] / n };
        }

        static double[] QuatFromCache(float[] f) =>
            QuatFromMatrix(f[0], f[1], f[2], f[4], f[5], f[6], f[8], f[9], f[10]);

        static double[] QMul(double[] a, double[] b)
        {
            double ax = a[0], ay = a[1], az = a[2], aw = a[3], bx = b[0], by = b[1], bz = b[2], bw = b[3];
            return new[]
            {
                aw * bx + ax * bw + ay * bz - az * by,
                aw * by - ax * bz + ay * bw + az * bx,
                aw * bz + ax * by - ay * bx + az * bw,
                aw * bw - ax * bx - ay * by - az * bz,
            };
        }

        static (int t, double[] axis, double ang) Delta(int t, double[] last, double[] p)
        {
            var q = QMul(new[] { -last[0], -last[1], -last[2], last[3] }, p);
            // shortest way round: some keys store "no turn" as w = -1, which read
            // literally would spin the bone a full circle
            if (q[3] < 0.0) q = new[] { -q[0], -q[1], -q[2], -q[3] };
            var aa = KeyAxisAngle(q[0], q[1], q[2], q[3]);
            return (t, aa.axis, aa.ang);
        }

        /// <summary>ASE rotation samples that reproduce the rotation the game uses at every key
        /// (its TmPrevRot cache): q_i = conj(p_{i-1}) * p_i.</summary>
        static List<(int t, double[] axis, double ang)> RotationKeys(ModelObject o)
        {
            var outl = new List<(int, double[], double)>();
            if (o.PrevRot.Count != o.RotKeys.Count)
            {
                foreach (var k in o.RotKeys)
                {
                    var aa = KeyAxisAngle(k.x, k.y, k.z, k.w);
                    outl.Add((k.t, aa.axis, aa.ang));
                }
                return outl;
            }
            var last = new[] { 0.0, 0.0, 0.0, 1.0 };
            for (int i = 0; i < o.RotKeys.Count; i++)
            {
                var p = QuatFromCache(o.PrevRot[i]);
                outl.Add(Delta(o.RotKeys[i].t, last, p));
                last = p;
            }
            return outl;
        }

        class Piece { public int S, E; public int[] Idx = new int[3], N = new int[3]; }

        /// <summary>Glued motion pieces that have length, or null for a plain single-timeline file.</summary>
        static List<Piece> Pieces(ModelObject o)
        {
            if (o.Frames[0] == null || o.Frames[0].Length == 0) return null;
            var outl = new List<Piece>();
            for (int i = 0; i < o.Frames[0].Length; i++)
            {
                var r = o.Frames[0][i];
                if (r[1] > r[0] && r[0] >= 0)
                {
                    var pc = new Piece { S = r[0], E = r[1] };
                    for (int t = 0; t < 3; t++) { pc.Idx[t] = o.Frames[t][i][2]; pc.N[t] = o.Frames[t][i][3]; }
                    outl.Add(pc);
                }
            }
            return outl.Count > 0 ? outl : null;
        }

        /// <summary>Per-piece keys -> one continuous track of (tick, key index; -1 = the piece's fixed
        /// value, piece index). The game only looks at the keys of the piece being played, so each
        /// piece is held flat up to 1 tick before the next one starts.</summary>
        static List<(int t, int j, int pc)> PieceTrack(List<Piece> pieces, int which, IList<int> keyTicks,
                                                       Func<int, bool> fixedPiece = null)
        {
            var outl = new List<(int t, int j, int pc)>();
            for (int pi = 0; pi < pieces.Count; pi++)
            {
                var pc = pieces[pi];
                int s = pc.S, e = pc.E, idx = pc.Idx[which], n = pc.N[which];
                if (n <= 0 || idx < 0 || idx + n > keyTicks.Count || (fixedPiece != null && fixedPiece(pi)))
                {
                    outl.Add((s, -1, pi));
                    outl.Add((e - 1, -1, pi));
                    continue;
                }
                if (keyTicks[idx] > s) outl.Add((s, idx, pi));                     // hold the first key
                for (int j = idx; j < idx + n; j++)
                {
                    int t = Math.Min(keyTicks[j], e - 1);
                    if (outl.Count > 0 && outl[outl.Count - 1].t >= Math.Max(t, s))
                    {
                        outl[outl.Count - 1] = (outl[outl.Count - 1].t, j, pi);     // same tick: later key wins
                        continue;
                    }
                    outl.Add((t, j, pi));
                }
                if (outl[outl.Count - 1].t < e - 1) outl.Add((e - 1, idx + n - 1, pi));   // hold the last key
            }
            return outl;
        }

        static double[] NormQuat(double[] q)
        {
            double n = Math.Sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]);
            if (n == 0) n = 1.0;
            return new[] { q[0] / n, q[1] / n, q[2] / n, q[3] / n };
        }

        /// <summary>What the game shows for a node without keys (smOBJ3D::TmAnimation): Tm x
        /// parent->TmInvert from the 8.8 world matrices -> (rotation, position, scale).</summary>
        static (double[] q, double[] p, double[] s) EngineLocal(ModelObject o, ModelObject parent)
        {
            var tm = new double[4, 4];
            for (int r = 0; r < 4; r++) for (int c = 0; c < 4; c++) tm[r, c] = o.Tm[r, c] / 256.0;
            if (parent != null)
            {
                var ti = new double[4, 4];
                for (int r = 0; r < 4; r++) for (int c = 0; c < 4; c++) ti[r, c] = parent.TmInv[r, c] / 256.0;
                var m = new double[4, 4];
                for (int r = 0; r < 4; r++)
                    for (int c = 0; c < 4; c++)
                    {
                        double v = 0.0;
                        for (int k = 0; k < 4; k++) v += tm[r, k] * ti[k, c];
                        m[r, c] = v;
                    }
                tm = m;
            }
            // a mirrored local (IceSerpent's wing bones): negative scale next to a proper rotation
            double det = tm[0, 0] * (tm[1, 1] * tm[2, 2] - tm[1, 2] * tm[2, 1]) - tm[0, 1] * (tm[1, 0] * tm[2, 2] - tm[1, 2] * tm[2, 0])
                       + tm[0, 2] * (tm[1, 0] * tm[2, 1] - tm[1, 1] * tm[2, 0]);
            double sign = det < 0 ? -1.0 : 1.0;
            var scl = new double[3];
            var rows = new double[3, 3];
            for (int r = 0; r < 3; r++)
            {
                double a = tm[r, 0], b = tm[r, 1], c = tm[r, 2];
                double ln = Math.Sqrt(a * a + b * b + c * c);
                if (ln == 0) ln = 1.0;
                ln *= sign;
                scl[r] = ln;
                rows[r, 0] = a / ln; rows[r, 1] = b / ln; rows[r, 2] = c / ln;
            }
            var q = QuatFromMatrix(rows[0, 0], rows[0, 1], rows[0, 2], rows[1, 0], rows[1, 1], rows[1, 2],
                                   rows[2, 0], rows[2, 1], rows[2, 2]);
            return (q, new[] { tm[3, 0], tm[3, 1], tm[3, 2] }, scl);
        }

        static bool Scaled(double[] s) => Math.Abs(s[0] - 1.0) > 1e-3 || Math.Abs(s[1] - 1.0) > 1e-3 || Math.Abs(s[2] - 1.0) > 1e-3;

        static (int t, double[] axis, double ang) AbsKey(int t, double[] q)
        {
            var aa = KeyAxisAngle(q[0], q[1], q[2], q[3]);
            return (t, aa.axis, aa.ang);
        }

        /// <summary>(pos, rot, scale) keys reproducing what the game shows at every tick
        /// (smOBJ3D::TmAnimation), as convert.py _anim_keys. Where the game falls back to values an
        /// ASE does not carry they are written as keys: a channel without keys while others have
        /// some -> the stored local value (TmRotate, px/py/pz, no scale); no keys at all (unkeyed,
        /// bones of an animated skeleton) or a glued piece without any key -> Tm x parent->TmInvert;
        /// single timeline: from a channel's last key on, the stored value again.</summary>
        static void AnimKeys(ModelObject o, GeomObject go, ModelObject parent = null, int end = 0, bool unkeyed = false)
        {
            var staticQ = NormQuat(o.Quat);
            var staticP = new[] { o.Pos[0], o.Pos[1], o.Pos[2] };
            var pieces = Pieces(o);
            go.PosKeys = new List<(int, double, double, double)>();
            go.ScaleKeys = new List<(int, double, double, double)>();
            go.RotKeys = new List<(int, double[], double)>();
            bool has = o.PosKeys.Count > 0 || o.RotKeys.Count > 0 || o.ScaleKeys.Count > 0;
            if (!has)
            {
                if (!unkeyed || end <= 0) return;
                var e0 = EngineLocal(o, parent);
                ConstantKeys(go, e0.q, e0.p, e0.s, new[] { 0, end });
                return;
            }
            if (pieces == null)
            {
                go.PosKeys.AddRange(o.PosKeys);
                go.RotKeys = RotationKeys(o);
                go.ScaleKeys.AddRange(o.ScaleKeys);
                FillStatic(o, go);
                if (end > 0) SnapAfterLast(go, end, staticQ, staticP);
                return;
            }
            var eng = EngineLocal(o, parent);
            // a piece the game plays without keys (smOBJ3D::TmAnimation: NumTmRot >= 0 || NumTmPos >= 0 ||
            // NumTmScale > 0, so scale keys starting at the first one do not count - frost's weapons)
            bool Bare(int pi) => pieces[pi].N[0] <= 0 && pieces[pi].N[1] <= 0 && !(pieces[pi].N[2] > 0 && pieces[pi].Idx[2] > 0);
            foreach (var k in PieceTrack(pieces, 1, o.PosKeys.Select(x => x.t).ToList()))
            {
                if (k.j >= 0) go.PosKeys.Add((k.t, o.PosKeys[k.j].x, o.PosKeys[k.j].y, o.PosKeys[k.j].z));
                else
                {
                    var v = Bare(k.pc) ? eng.p : staticP;
                    go.PosKeys.Add((k.t, v[0], v[1], v[2]));
                }
            }
            bool anyBare = false;
            for (int pi = 0; pi < pieces.Count; pi++) if (Bare(pi)) anyBare = true;
            if (o.ScaleKeys.Count > 0 || (Scaled(eng.s) && anyBare))
                foreach (var k in PieceTrack(pieces, 2, o.ScaleKeys.Select(x => x.t).ToList(), Bare))
                {
                    if (k.j >= 0) go.ScaleKeys.Add((k.t, o.ScaleKeys[k.j].x, o.ScaleKeys[k.j].y, o.ScaleKeys[k.j].z));
                    else
                    {
                        var v = Bare(k.pc) ? eng.s : new[] { 1.0, 1.0, 1.0 };
                        go.ScaleKeys.Add((k.t, v[0], v[1], v[2]));
                    }
                }
            var last = new[] { 0.0, 0.0, 0.0, 1.0 };
            foreach (var k in PieceTrack(pieces, 0, o.RotKeys.Select(x => x.t).ToList()))
            {
                var p = k.j >= 0 ? QuatFromCache(o.PrevRot[k.j]) : (Bare(k.pc) ? eng.q : staticQ);
                go.RotKeys.Add(Delta(k.t, last, p));
                last = p;
            }
        }

        static void ConstantKeys(GeomObject go, double[] q, double[] p, double[] s, int[] ticks)
        {
            var ts = ticks.Distinct().OrderBy(t => t).ToList();
            foreach (int t in ts) go.PosKeys.Add((t, p[0], p[1], p[2]));
            go.RotKeys.Add(AbsKey(ts[0], q));
            for (int i = 1; i < ts.Count; i++) go.RotKeys.Add((ts[i], new[] { 0.0, 0.0, 0.0 }, 0.0));
            if (Scaled(s)) foreach (int t in ts) go.ScaleKeys.Add((t, s[0], s[1], s[2]));
        }

        /// <summary>A node keyed in rotation but not in position (or the other way round): the game
        /// uses its stored local position / rotation, written as keys (convert.py _fill_static).</summary>
        static void FillStatic(ModelObject o, GeomObject go)
        {
            int first, lastT;
            if (go.RotKeys.Count > 0) { first = go.RotKeys[0].t; lastT = go.RotKeys[go.RotKeys.Count - 1].t; }
            else if (go.PosKeys.Count > 0) { first = go.PosKeys[0].t; lastT = go.PosKeys[go.PosKeys.Count - 1].t; }
            else if (go.ScaleKeys.Count > 0) { first = go.ScaleKeys[0].t; lastT = go.ScaleKeys[go.ScaleKeys.Count - 1].t; }
            else return;
            var ts = new SortedSet<int> { first, lastT }.ToList();
            if (go.RotKeys.Count > 0 && go.PosKeys.Count == 0)
                foreach (int t in ts) go.PosKeys.Add((t, o.Pos[0], o.Pos[1], o.Pos[2]));
            if (go.PosKeys.Count > 0 && go.RotKeys.Count == 0)
            {
                go.RotKeys.Add(AbsKey(ts[0], NormQuat(o.Quat)));
                for (int i = 1; i < ts.Count; i++) go.RotKeys.Add((ts[i], new[] { 0.0, 0.0, 0.0 }, 0.0));
            }
        }

        /// <summary>Single timeline: past a channel's last key the game shows the stored value again,
        /// so a channel that ends before the skeleton gets one more key, 1 tick later.</summary>
        static void SnapAfterLast(GeomObject go, int end, double[] staticQ, double[] staticP)
        {
            if (go.PosKeys.Count > 0 && go.PosKeys[go.PosKeys.Count - 1].t + 1 <= end)
                go.PosKeys.Add((go.PosKeys[go.PosKeys.Count - 1].t + 1, staticP[0], staticP[1], staticP[2]));
            if (go.ScaleKeys.Count > 0 && go.ScaleKeys[go.ScaleKeys.Count - 1].t + 1 <= end)
                go.ScaleKeys.Add((go.ScaleKeys[go.ScaleKeys.Count - 1].t + 1, 1.0, 1.0, 1.0));
            if (go.RotKeys.Count > 0 && go.RotKeys[go.RotKeys.Count - 1].t + 1 <= end)
            {
                var last = new[] { 0.0, 0.0, 0.0, 1.0 };              // absolute orientation at the last key
                foreach (var k in go.RotKeys)
                {
                    double sn = Math.Sin(0.5 * k.ang);
                    last = QMul(last, new[] { k.axis[0] * sn, k.axis[1] * sn, k.axis[2] * sn, Math.Cos(0.5 * k.ang) });
                }
                go.RotKeys.Add(Delta(go.RotKeys[go.RotKeys.Count - 1].t + 1, last, staticQ));
            }
        }

        static int SkeletonEnd(Model skel)
        {
            int end = 0;
            foreach (var b in skel.Objects)
            {
                if (b.PosKeys.Count > 0 && b.PosKeys[b.PosKeys.Count - 1].t > end) end = b.PosKeys[b.PosKeys.Count - 1].t;
                if (b.RotKeys.Count > 0 && b.RotKeys[b.RotKeys.Count - 1].t > end) end = b.RotKeys[b.RotKeys.Count - 1].t;
                if (b.ScaleKeys.Count > 0 && b.ScaleKeys[b.ScaleKeys.Count - 1].t > end) end = b.ScaleKeys[b.ScaleKeys.Count - 1].t;
            }
            return end;
        }

        static Dictionary<string, ModelObject> ByName(Model m)
        {
            var d = new Dictionary<string, ModelObject>();
            foreach (var o in m.Objects) d[o.Name] = o;               // later ones win, as a Python dict
            return d;
        }

        static (double[] axis, double ang, double[] scale) RowsToAxisAngle(double[][] rows)
        {
            var sc = new double[3];
            for (int r = 0; r < 3; r++)
            {
                double s = Math.Sqrt(0 + rows[r][0] * rows[r][0] + rows[r][1] * rows[r][1] + rows[r][2] * rows[r][2]);
                sc[r] = s == 0 ? 1.0 : s;
            }
            var R = new double[3, 3];
            for (int r = 0; r < 3; r++) for (int c = 0; c < 3; c++) R[r, c] = rows[r][c] / sc[r];
            var M = new double[3, 3];
            for (int r = 0; r < 3; r++) for (int c = 0; c < 3; c++) M[r, c] = R[c, r];
            double tr = M[0, 0] + M[1, 1] + M[2, 2];
            double x, y, z, w, s2;
            if (tr > 0)
            {
                s2 = Math.Sqrt(tr + 1.0) * 2; w = 0.25 * s2;
                x = (M[1, 2] - M[2, 1]) / s2; y = (M[2, 0] - M[0, 2]) / s2; z = (M[0, 1] - M[1, 0]) / s2;
            }
            else if (M[0, 0] > M[1, 1] && M[0, 0] > M[2, 2])
            {
                s2 = Math.Sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2; w = (M[1, 2] - M[2, 1]) / s2;
                x = 0.25 * s2; y = (M[1, 0] + M[0, 1]) / s2; z = (M[2, 0] + M[0, 2]) / s2;
            }
            else if (M[1, 1] > M[2, 2])
            {
                s2 = Math.Sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2; w = (M[2, 0] - M[0, 2]) / s2;
                x = (M[1, 0] + M[0, 1]) / s2; y = 0.25 * s2; z = (M[2, 1] + M[1, 2]) / s2;
            }
            else
            {
                s2 = Math.Sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2; w = (M[0, 1] - M[1, 0]) / s2;
                x = (M[2, 0] + M[0, 2]) / s2; y = (M[2, 1] + M[1, 2]) / s2; z = 0.25 * s2;
            }
            var aa = QuatToAxisAngle(x, y, z, w);
            return (aa.axis, aa.ang, sc);
        }

        // ------------------------------------------------------------------ paths
        // a char folder converted on its own keeps char\monster\<name>\ (written next to each other,
        // same-named models overwrote each other)
        static readonly string[] GameTopFolders = { "field", "char", "image", "effect" };

        /// <summary>Folders found right inside a game folder (a game folder, or a copy of one, holds two or more).</summary>
        static readonly string[] ClientTopFolders = { "char", "field", "image", "effect", "wav", "sky", "rain", "weapons", "cselect", "startimage" };
        static readonly Dictionary<string, bool> clientCache = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);

        /// <summary>True when dir holds at least two of char, Field, image, Effect, wav ... (cached).</summary>
        public static bool LooksLikeClient(string dir)
        {
            lock (clientCache)
                if (clientCache.TryGetValue(dir, out bool known)) return known;
            int n = 0;
            try
            {
                foreach (var d in Directory.GetDirectories(dir))
                    if (Array.Exists(ClientTopFolders, t => string.Equals(Path.GetFileName(d), t, StringComparison.OrdinalIgnoreCase))) n++;
            }
            catch (Exception) { }
            lock (clientCache) clientCache[dir] = n >= 2;
            return n >= 2;
        }

        public static void ClearClientCache() { lock (clientCache) clientCache.Clear(); }

        /// <summary>The game folder a file belongs to: the nearest folder above it that looks like a
        /// game folder (some game folders hold folders named like top ones: Effect\Sky\Field,
        /// image\Sinimage\Effect, StartImage\sky), else the folder above the nearest Field / char /
        /// image / Effect (a copy of single folders), else the file's own folder.</summary>
        public static string GuessGameRoot(string path)
        {
            string start = Path.GetDirectoryName(Path.GetFullPath(path));
            for (string a = start; a != null; a = Path.GetDirectoryName(a))
                if (LooksLikeClient(a)) return a;
            string d = start;
            while (true)
            {
                string parent = Path.GetDirectoryName(d);
                if (Array.Exists(GameTopFolders, n => string.Equals(Path.GetFileName(d), n, StringComparison.OrdinalIgnoreCase)))
                    return parent ?? d;
                if (parent == null || parent == d) return start;
                d = parent;
            }
        }

        public static string RelPath(string path, string root)
        {
            string p = Path.GetFullPath(path), r = Path.GetFullPath(root).TrimEnd('\\', '/');
            if (p.StartsWith(r + "\\", StringComparison.OrdinalIgnoreCase)) return p.Substring(r.Length + 1);
            return null;
        }

        public static string FindBoneFile(string path)
        {
            string b = Path.Combine(Path.GetDirectoryName(path) ?? "", Path.GetFileNameWithoutExtension(path)) + ".smb";
            return File.Exists(b) ? b : null;
        }

        // ------------------------------------------------------------------ builders
        static (List<Material> order, Dictionary<int, int> remap) MaterialRemap(List<Material> mats, HashSet<int> used, bool compact)
        {
            var remap = new Dictionary<int, int>();
            if (!compact)
            {
                foreach (var m in mats) remap[m.Index] = m.Index;
                return (new List<Material>(mats), remap);
            }
            var order = mats.Where(m => used.Contains(m.Index)).ToList();
            for (int i = 0; i < order.Count; i++) remap[order[i].Index] = i;
            return (order, remap);
        }

        static List<double[][]> ChannelsFromLayers(IList<List<TexLayer>> faceLayers, int nLayers, bool negV)
        {
            var chans = new List<double[][]>();
            for (int k = 0; k < nLayers; k++)
            {
                var ch = new double[faceLayers.Count][];
                for (int f = 0; f < faceLayers.Count; f++)
                {
                    var layers = faceLayers[f];
                    if (k < layers.Count)
                    {
                        var L = layers[k];
                        ch[f] = negV
                            ? new[] { L.U0, -L.V0, L.U1, -L.V1, L.U2, -L.V2 }
                            : new[] { L.U0, 1.0 - L.V0, L.U1, 1.0 - L.V1, L.U2, 1.0 - L.V2 };
                    }
                    else ch[f] = new double[6];
                }
                chans.Add(ch);
            }
            if (chans.Count == 0)
            {
                var ch = new double[faceLayers.Count][];
                for (int f = 0; f < ch.Length; f++) ch[f] = new double[6];
                chans.Add(ch);
            }
            return chans;
        }

        public const double PartMergeDistance = 300.0;
        public const int PartLookback = 1;

        /// <summary>Split a map's faces into the objects it was built from, as far as the file still tells.
        /// The game appends every ASE object's vertex list as is and keeps the faces in object order, so a
        /// real object boundary always lies where every vertex used before a face is lower than every vertex
        /// used from it on. Those cuts also fall between loose parts of one object, so a part joins the object
        /// before it when they share a material and lie within PartMergeDistance of each other; it may also
        /// join the object PartLookback places back (taking the ones in between along). Returns lists of face indices, in file order (same as convert.py _stage_parts).</summary>
        public static List<List<int>> StageParts(Stage st)
        {
            var faces = st.Faces;
            int n = faces.Length;
            if (n == 0) return new List<List<int>> { new List<int>() };
            var suf = new int[n];
            int lo = 1 << 30;
            for (int i = n - 1; i >= 0; i--)
            {
                lo = Math.Min(lo, Math.Min(faces[i].A, Math.Min(faces[i].B, faces[i].C)));
                suf[i] = lo;
            }
            var bounds = new List<int> { 0 };
            int hi = -1;
            for (int i = 1; i < n; i++)
            {
                hi = Math.Max(hi, Math.Max(faces[i - 1].A, Math.Max(faces[i - 1].B, faces[i - 1].C)));
                if (hi < suf[i]) bounds.Add(i);
            }
            bounds.Add(n);
            var P = st.Positions;
            double d = PartMergeDistance;
            var groups = new List<(int first, int end, HashSet<int> mats, double[] bb)>();
            for (int k = 0; k + 1 < bounds.Count; k++)
            {
                var mats = new HashSet<int>();
                double[] bb = null;
                for (int fi = bounds[k]; fi < bounds[k + 1]; fi++)
                {
                    var f = faces[fi];
                    mats.Add(f.Mat);
                    foreach (int v in new[] { f.A, f.B, f.C })
                    {
                        if (bb == null) { bb = new[] { P[v * 3], P[v * 3 + 1], P[v * 3 + 2], P[v * 3], P[v * 3 + 1], P[v * 3 + 2] }; continue; }
                        for (int j = 0; j < 3; j++)
                        {
                            double p = P[v * 3 + j];
                            if (p < bb[j]) bb[j] = p;
                            if (p > bb[j + 3]) bb[j + 3] = p;
                        }
                    }
                }
                int hit = -1;
                for (int g = groups.Count - 1; g > Math.Max(-1, groups.Count - 2 - PartLookback); g--)
                {
                    var gb = groups[g].bb;
                    bool near = true;
                    for (int j = 0; j < 3; j++)
                        if (!(gb[j] <= bb[j + 3] + d && bb[j] <= gb[j + 3] + d)) near = false;
                    if (near && groups[g].mats.Overlaps(mats)) { hit = g; break; }
                }
                if (hit < 0) { groups.Add((bounds[k], bounds[k + 1], mats, bb)); continue; }
                while (groups.Count - 1 > hit)              // the groups in between become part of it too
                {
                    var last = groups[groups.Count - 1];
                    groups.RemoveAt(groups.Count - 1);
                    mats.UnionWith(last.mats);
                    bb = Union(bb, last.bb);
                }
                var h = groups[hit];
                h.mats.UnionWith(mats);
                groups[hit] = (h.first, bounds[k + 1], h.mats, Union(h.bb, bb));
            }
            return groups.Select(g => Enumerable.Range(g.first, g.end - g.first).ToList()).ToList();
        }

        static double[] Union(double[] a, double[] b)
        {
            return new[] { Math.Min(a[0], b[0]), Math.Min(a[1], b[1]), Math.Min(a[2], b[2]),
                           Math.Max(a[3], b[3]), Math.Max(a[4], b[4]), Math.Max(a[5], b[5]) };
        }

        /// <summary>"_jandi": the texture most of a part's faces use (helps to find parts in the editor).</summary>
        static string PartLabel(Stage st, List<int> fidx)
        {
            var count = new SortedDictionary<int, int>();
            foreach (int fi in fidx)
            {
                int m = st.Faces[fi].Mat;
                count[m] = count.TryGetValue(m, out int c) ? c + 1 : 1;
            }
            int best = -1;
            foreach (var kv in count)
                if (best < 0 || kv.Value > count[best]) best = kv.Key;
            if (best < 0 || best >= st.Materials.Count || st.Materials[best].Textures.Count == 0) return "";
            string name = st.Materials[best].Textures[0].name.Replace('\\', '/');
            name = name.Substring(name.LastIndexOf('/') + 1);
            int dot = name.LastIndexOf('.');
            if (dot >= 0) name = name.Substring(0, dot);
            var sb = new StringBuilder();
            foreach (char ch in name)
                sb.Append((ch < 128 && char.IsLetterOrDigit(ch)) || ch == '-' || ch == '_' ? ch : '_');
            name = sb.ToString();
            if (name.Length > 24) name = name.Substring(0, 24);
            return name.Length > 0 ? "_" + name : "";
        }

        public static Scene BuildStage(string path, ConvertOptions opt)
        {
            var st = new Stage(path);
            var sc = new Scene { Name = Path.GetFileNameWithoutExtension(path), Kind = "stage", Source = path };
            int nmat = st.Materials.Count;
            var used = new HashSet<int>(st.Faces.Where(f => f.Mat < nmat).Select(f => f.Mat));
            var mr = MaterialRemap(st.Materials, used, opt.CompactMaterials);
            sc.Materials = mr.order;
            int nLayers = st.MaxLayers();

            double[][] colors = null;
            if (opt.VertexColors)
            {
                int nv = st.Positions.Length / 3;
                colors = new double[nv][];
                for (int i = 0; i < nv; i++)
                {
                    var c = new double[3];
                    for (int k = 0; k < 3; k++)
                    {
                        double v = st.Colors[i * 4 + k] * opt.ColorScale / 255.0;
                        if (opt.ClampColors) v = Math.Min(1.0, Math.Max(0.0, v));
                        c[k] = v;
                    }
                    colors[i] = c;
                }
            }

            var coll = new List<int>();
            var parts = new List<List<int>>();
            var split = opt.SplitObjects ? StageParts(st)
                                         : new List<List<int>> { Enumerable.Range(0, st.Faces.Length).ToList() };
            foreach (var part in split)
            {
                var keep = new List<int>();
                foreach (int fi in part)
                {
                    var f = st.Faces[fi];
                    Material m = f.Mat < nmat ? st.Materials[f.Mat] : null;
                    if (opt.SplitCollision && (m == null || m.IsCollision)) coll.Add(fi);
                    else keep.Add(fi);
                }
                if (keep.Count > 0) parts.Add(keep);
            }
            var groups = new List<(string suffix, List<int> faces)>();
            if (parts.Count <= 1)
                groups.Add(("", parts.Count > 0 ? parts[0] : new List<int>()));
            else
                for (int k = 0; k < parts.Count; k++)
                    groups.Add(("_" + (k + 1).ToString("000", CI) + PartLabel(st, parts[k]), parts[k]));
            if (coll.Count > 0 && !opt.DropCollision) groups.Add(("__collision", coll));

            foreach (var g in groups)
            {
                if (g.faces.Count == 0 && g.suffix.Length > 0) continue;
                var go = new GeomObject(sc.Name + g.suffix);
                var vmap = new Dictionary<int, int>();
                var order = new List<int>();
                foreach (int fi in g.faces)
                {
                    var f = st.Faces[fi];
                    var o = new int[4];
                    int[] src = { f.A, f.B, f.C };
                    for (int j = 0; j < 3; j++)
                    {
                        int v = src[j];
                        if (!vmap.TryGetValue(v, out int nvx))
                        {
                            nvx = vmap[v] = go.Verts.Count;
                            go.Verts.Add(new[] { st.Positions[v * 3], st.Positions[v * 3 + 1], st.Positions[v * 3 + 2] });
                            order.Add(v);
                        }
                        o[j] = nvx;
                    }
                    o[3] = mr.remap.TryGetValue(f.Mat, out int rm) ? rm : 0;
                    go.Faces.Add(o);
                }
                if (colors != null) go.Colors = order.Select(k => colors[k]).ToList();
                go.Channels = ChannelsFromLayers(g.faces.Select(fi => st.FaceUVs[fi]).ToList(), nLayers, true);
                if (opt.SplitObjects && go.Verts.Count > 0)
                {
                    // pivot in the middle of the object (vertices stay in world space), so moving
                    // one object in the editor shows the gizmo on it, not at the world origin. Whole
                    // units: editors keep vertices in single precision relative to the pivot, and a
                    // whole-unit pivot gives back every world position exactly.
                    var c = new double[3];
                    for (int j = 0; j < 3; j++)
                        c[j] = Math.Floor((go.Verts.Min(v => v[j]) + go.Verts.Max(v => v[j])) / 2.0 + 0.5);
                    go.Pos = c;
                }
                sc.Objects.Add(go);
            }
            if (opt.IncludeLights) sc.Lights = st.Lights;
            return sc;
        }

        static (double[][] rows, double[] t) ModelWorld(ModelObject o)
        {
            var ti = new double[3][];
            for (int r = 0; r < 3; r++) ti[r] = new[] { o.TmInv[r, 0] / 256.0, o.TmInv[r, 1] / 256.0, o.TmInv[r, 2] / 256.0 };
            var t = new[] { o.Tm[3, 0] / 256.0, o.Tm[3, 1] / 256.0, o.Tm[3, 2] / 256.0 };
            if (!SaneTm(o.TmInv))
            {
                // some files leave junk (uninitialised memory or zeros) in TmInvert; the game never
                // uses it for a skinned mesh (every vertex rides on its bone): plain pivot
                return (new[] { new[] { 1.0, 0.0, 0.0 }, new[] { 0.0, 1.0, 0.0 }, new[] { 0.0, 0.0, 1.0 } }, t);
            }
            return (Inv3(ti), t);
        }

        /// <summary>A real 8.8 fixed-point smMATRIX: last column 0 0 0 256, sensible size, not flat.</summary>
        static bool SaneTm(int[,] m)
        {
            if (m[0, 3] != 0 || m[1, 3] != 0 || m[2, 3] != 0 || m[3, 3] != 256) return false;
            for (int r = 0; r < 3; r++)
                for (int c = 0; c < 3; c++)
                    if (Math.Abs((long)m[r, c]) > 65536) return false;
            var a = new double[3, 3];
            for (int r = 0; r < 3; r++)
                for (int c = 0; c < 3; c++) a[r, c] = m[r, c] / 256.0;
            double det = a[0, 0] * (a[1, 1] * a[2, 2] - a[1, 2] * a[2, 1]) - a[0, 1] * (a[1, 0] * a[2, 2] - a[1, 2] * a[2, 0])
                       + a[0, 2] * (a[1, 0] * a[2, 1] - a[1, 1] * a[2, 0]);
            return Math.Abs(det) > 1e-4 && Math.Abs(det) < 1e4;
        }

        static List<Motion> DedupeMotions(List<Motion> motions)
        {
            var seen = new HashSet<(int, int)>();
            var outl = new List<Motion>();
            foreach (var m in motions)
                if (seen.Add((m.Start, m.End))) outl.Add(m);
            outl = outl.OrderBy(m => m.Start).ThenBy(m => m.End).ToList();     // stable, like Python's sort
            var count = new Dictionary<string, int>();
            foreach (var m in outl)                                            // renumber: walk_01, walk_02 ...
            {
                int us = m.Name.LastIndexOf('_');
                string label = us >= 0 ? m.Name.Substring(0, us) : m.Name;
                count[label] = count.TryGetValue(label, out int c) ? c + 1 : 1;
                m.Name = label + "_" + count[label].ToString("00", CI);
            }
            return outl;
        }

        static GeomObject BoneObject(ModelObject b, bool keys, ModelObject parent = null, int end = 0)
        {
            var w = ModelWorld(b);
            var go = new GeomObject(b.Name) { Parent = b.Parent, Rows = w.rows, Pos = w.t, IsBone = true };
            if (b.Faces.Length > 0)
            {
                // the bone's own Biped shape, when the .smb still has it
                int nv = b.LocalVerts.Length / 3;
                for (int i = 0; i < nv; i++)
                    go.Verts.Add(Xform(b.LocalVerts[i * 3], b.LocalVerts[i * 3 + 1], b.LocalVerts[i * 3 + 2], w.rows, w.t));
                foreach (var f in b.Faces) go.Faces.Add(new[] { f.A, f.B, f.C, 0 });
            }
            else
            {
                // the small diamond 3ds Max Biped gives a bone (6 vertices, 8 faces)
                double x = w.t[0], y = w.t[1], z = w.t[2], r = 0.5;
                go.Verts.AddRange(new[] { new[] { x, y, z + r }, new[] { x, y - r, z }, new[] { x + r, y, z },
                                          new[] { x, y + r, z }, new[] { x - r, y, z }, new[] { x, y, z - r } });
                foreach (var f in new[] { new[] { 0, 1, 2 }, new[] { 0, 2, 3 }, new[] { 0, 3, 4 }, new[] { 0, 4, 1 },
                                          new[] { 5, 4, 3 }, new[] { 5, 3, 2 }, new[] { 5, 2, 1 }, new[] { 5, 1, 4 } })
                    go.Faces.Add(new[] { f[0], f[1], f[2], 0 });
            }
            if (keys) AnimKeys(b, go, parent, end, true);
            return go;
        }

        /// <summary>Objects, characters and monsters (.smd), or a skeleton/motion file (.smb).</summary>
        public static Scene BuildModel(string path, ConvertOptions opt)
        {
            var md = new Model(path);
            var sc = new Scene { Name = Path.GetFileNameWithoutExtension(path), Kind = "model", Source = path };
            bool isSmb = path.EndsWith(".smb", StringComparison.OrdinalIgnoreCase);

            // ---- skeleton
            var needs = new SortedSet<string>(StringComparer.Ordinal);
            foreach (var o in md.Objects)
                if (o.Physique != null)
                    foreach (string n in o.Physique) if (n.Length > 0) needs.Add(n);
            Model skel = null;
            Rig rig = null;
            if (isSmb)
            {
                skel = md;
                rig = MotionInfo.FindRigForSmb(path);
            }
            else if (needs.Count > 0)
            {
                rig = MotionInfo.FindRig(path, needs);
                if (rig.Smb != null) skel = new Model(rig.Smb);
            }
            var bones = new Dictionary<string, (double[][] rows, double[] t)>();
            if (skel != null) foreach (var b in skel.Objects) bones[b.Name] = ModelWorld(b);
            sc.Rig = rig;
            sc.Skeleton = skel;
            sc.MissingBoneNames = needs.Where(n => !bones.ContainsKey(n)).ToList();

            // ---- animation placement
            if (skel != null)
            {
                string mode = opt.Animation ?? "auto";
                if (mode == "auto") mode = rig != null && rig.Shared && !isSmb ? "shared" : "embed";
                sc.AnimMode = mode;
                string smbPath = rig != null && rig.Smb != null ? rig.Smb : path;
                sc.SkeletonFile = Path.GetFileName(smbPath);
                if (rig?.Info != null) sc.Motions = DedupeMotions(rig.Info.Motions(MotionInfo.SmbSegments(smbPath)));
                if (mode == "shared") sc.AnimFile = Path.GetFileNameWithoutExtension(sc.SkeletonFile) + "_motions.ase";
                else if (!isSmb && mode == "embed" &&
                         !string.Equals(Path.GetFileNameWithoutExtension(sc.SkeletonFile), sc.Name, StringComparison.OrdinalIgnoreCase))
                    // the game keeps this monster's animation in its own motion file (mGknight ...): the
                    // animation is included for viewing, but it does not belong in the model file
                    sc.MotionFile = Path.GetFileNameWithoutExtension(sc.SkeletonFile) + ".ASE";
            }

            // ---- detail levels: keep the high one
            var drop = new HashSet<string>();
            if (rig?.Info != null && opt.Lod == "high")
            {
                var high = new HashSet<string>(rig.Info.Lod[0].Select(n => n.ToLowerInvariant()));
                foreach (string n in rig.Info.Lod[1].Concat(rig.Info.Lod[2]))
                    if (!high.Contains(n.ToLowerInvariant())) drop.Add(n.ToLowerInvariant());
            }
            var meshes = isSmb ? new List<ModelObject>()
                : md.Objects.Where(o => !drop.Contains(o.Name.ToLowerInvariant()) && (o.Faces.Length > 0 || skel == null)).ToList();

            int nmat = md.Materials.Count;
            var used = new HashSet<int>();
            foreach (var o in meshes) foreach (var f in o.Faces) if (f.Mat < nmat) used.Add(f.Mat);
            var mr = MaterialRemap(md.Materials, used, opt.CompactMaterials);
            sc.Materials = mr.order;

            if (skel != null)
            {
                var sb = ByName(skel);
                int send = SkeletonEnd(skel);
                foreach (var b in skel.Objects)
                    sc.Objects.Add(BoneObject(b, sc.AnimMode == "embed", sb.TryGetValue(b.Parent, out var bp) ? bp : null, send));
            }
            var meshNames = new HashSet<string>(meshes.Select(m => m.Name));
            var modelByName = ByName(md);
            int modelEnd = SkeletonEnd(md);
            foreach (var o in meshes)
            {
                var w = ModelWorld(o);
                var go = new GeomObject(o.Name)
                {
                    Parent = bones.ContainsKey(o.Parent) || meshNames.Contains(o.Parent) ? o.Parent : "",
                    Rows = w.rows, Pos = w.t,
                };
                int nv = o.LocalVerts.Length / 3;
                for (int i = 0; i < nv; i++)
                {
                    double x = o.LocalVerts[i * 3], y = o.LocalVerts[i * 3 + 1], z = o.LocalVerts[i * 3 + 2];
                    var bw = w;
                    if (o.Physique != null && bones.TryGetValue(o.Physique[i], out var bb)) bw = bb;
                    go.Verts.Add(Xform(x, y, z, bw.rows, bw.t));
                }
                go.Physique = o.Physique;
                foreach (var f in o.Faces)
                    go.Faces.Add(new[] { f.A, f.B, f.C, mr.remap.TryGetValue(f.Mat, out int rm) ? rm : 0 });
                int nl = 0;
                foreach (var l in o.FaceUVs) nl = Math.Max(nl, l.Count);
                go.Channels = ChannelsFromLayers(o.FaceUVs, nl, false);
                AnimKeys(o, go, modelByName.TryGetValue(o.Parent, out var mp) ? mp : null, modelEnd);
                sc.Objects.Add(go);
            }
            int ticks = md.LastFrameTicks();
            if (skel != null) ticks = Math.Max(ticks, skel.LastFrameTicks());
            sc.LastFrame = ticks != 0 ? Math.Max(1, ticks / 160) : 100;
            return sc;
        }

        /// <summary>The shared motion file of a class skeleton: bones + every animation key.</summary>
        public static Scene BuildAnimScene(Scene sc)
        {
            var skel = sc.Skeleton;
            var an = new Scene
            {
                Name = Path.GetFileNameWithoutExtension(sc.AnimFile), Kind = "motion", Source = skel.Path,
                AnimMode = "embed", SkeletonFile = sc.SkeletonFile, Motions = sc.Motions,
            };
            var ab = ByName(skel);
            int aend = SkeletonEnd(skel);
            foreach (var b in skel.Objects) an.Objects.Add(BoneObject(b, true, ab.TryGetValue(b.Parent, out var ap) ? ap : null, aend));
            an.LastFrame = Math.Max(1, skel.LastFrameTicks() / 160);
            return an;
        }

        public static Scene Build(string path, ConvertOptions opt)
        {
            switch (Smd.KindOf(path))
            {
                case SmdKind.Stage: return BuildStage(path, opt);
                case SmdKind.Model: return BuildModel(path, opt);
                default: throw new SmdException(Path.GetFileName(path) + ": not a Priston Tale SMD file");
            }
        }

        // ------------------------------------------------------------------ textures
        /// <summary>Locate a texture named in an SMD ('char\monster\Tees\Tees.tga').  Paths are relative
        /// to the game folder, which is whichever ancestor of the SMD makes the path exist (Field, char,
        /// copies of single folders ...).  Last resort: the bare file name next to the SMD.</summary>
        public static (string src, string root) FindTexture(string rel, string smdPath, string root)
        {
            rel = rel.Replace('\\', '/');
            var tried = new List<string> { root ?? GuessGameRoot(smdPath) };
            string d = Path.GetDirectoryName(Path.GetFullPath(smdPath));
            while (d != null)
            {
                tried.Add(d);
                string parent = Path.GetDirectoryName(d);
                if (parent == d) break;
                d = parent;
            }
            foreach (string r in tried)
            {
                string src = Textures.Resolve(r, rel);
                if (src != null) return (src, r);
            }
            string here = Textures.Resolve(Path.GetDirectoryName(Path.GetFullPath(smdPath)), rel.Split('/').Last());
            return (here, null);
        }

        public static void ResolveTextures(Scene sc, ConvertOptions opt, string smdPath)
        {
            string root = opt.GameRoot ?? GuessGameRoot(smdPath);
            var names = new SortedSet<string>(StringComparer.Ordinal);
            foreach (var m in sc.Materials)
                foreach (var t in m.Textures.Concat(m.AnimTextures))
                {
                    if (t.name.Length > 0) names.Add(t.name);
                    if (t.nameA.Length > 0) names.Add(t.nameA);
                }
            foreach (string n in names)
            {
                string rel = n.Replace('\\', '/');
                var found = FindTexture(n, smdPath, opt.GameRoot);
                string src = found.src;
                if (src == null && opt.MissingTextures != null)
                {
                    lock (opt.MissingTextures)
                    {
                        if (!opt.MissingTextures.TryGetValue(n, out var set))
                            opt.MissingTextures[n] = set = new SortedSet<string>(StringComparer.Ordinal);
                        set.Add(Path.GetFileName(smdPath));
                    }
                }
                string outp;
                if (opt.TextureDirOverride != null)
                {
                    outp = Path.Combine(opt.TextureDirOverride, (src != null ? Path.GetFileName(src) : rel.Split('/').Last()));
                    if (src != null && opt.TextureOut != null) Textures.DecodeIfNeeded(src, outp);
                }
                else if (opt.TextureOut != null)
                {
                    // (a texture found next to the model keeps its place below the game folder too:
                    // same-named ones of other folders - sky day / evening / night ... - differ)
                    string relpath = src != null
                        ? (RelPath(src, found.root ?? root) ?? Path.GetFileName(src))
                        : rel;
                    outp = Path.Combine(opt.TextureOut, relpath.Replace('/', '\\'));
                    if (src != null) Textures.DecodeIfNeeded(src, outp);
                }
                else outp = src ?? Path.Combine(root, rel.Replace('/', '\\'));
                sc.TexturePaths[n] = Path.GetFullPath(outp).Replace('/', '\\');
            }
        }

        // ------------------------------------------------------------------ number formatting (== Python)
        // Exact, correctly rounded (half-even) fixed-point formatting like Python's '%.nf'.
        // (.NET Framework formats from only 15 significant digits, and .NET 8's "F9" does not
        // always round the 9th decimal the same way.)
        static readonly System.Numerics.BigInteger[] Pow10 =
            Enumerable.Range(0, 10).Select(i => System.Numerics.BigInteger.Pow(10, i)).ToArray();

        static string Fixed(double x, int n)
        {
            long bits = BitConverter.DoubleToInt64Bits(x);
            bool neg = bits < 0;
            int exp = (int)((bits >> 52) & 0x7FF);
            long man = bits & 0xFFFFFFFFFFFFFL;
            if (exp == 0x7FF) return x.ToString(CI);
            if (exp == 0) exp = 1; else man |= 1L << 52;
            int e = exp - 1075;                                   // value = man * 2^e
            System.Numerics.BigInteger q;
            if (e >= 0) q = (new System.Numerics.BigInteger(man) << e) * Pow10[n];
            else
            {
                var num = new System.Numerics.BigInteger(man) * Pow10[n];
                int k = -e;
                q = num >> k;
                var rem = num - (q << k);
                var half = System.Numerics.BigInteger.One << (k - 1);
                int c = rem.CompareTo(half);
                if (c > 0 || (c == 0 && !q.IsEven)) q += 1;
            }
            string digits = q.ToString(CI).PadLeft(n + 1, '0');
            string s = digits.Substring(0, digits.Length - n) + "." + digits.Substring(digits.Length - n);
            return neg ? "-" + s : s;
        }

        static string F(double x)        // '%.8f' then strip zeros, keep >= 4 decimals
        {
            string s = Fixed(x, 8).TrimEnd('0');
            int dot = s.IndexOf('.');
            if (s.EndsWith(".")) s += "0000";
            else if (s.Length - dot < 5) s += new string('0', 5 - (s.Length - dot));
            if (s == "-0.0000") s = "0.0000";
            return s;
        }

        static string F4(double x)
        {
            string s = Fixed(x, 4);
            return s == "-0.0000" ? "0.0000" : s;
        }

        static string F6(double x)
        {
            string s = Fixed(x, 6);
            return s == "-0.000000" ? "0.000000" : s;
        }

        static string F9(double x)
        {
            string s = Fixed(x, 9);
            return s == "-0.000000000" ? "0.000000000" : s;
        }

        static string Q(string s) => "\"" + s.Replace("\"", "'") + "\"";

        static string Tp(Scene sc, string n) => sc.TexturePaths.TryGetValue(n, out string p) ? p : n;

        // ------------------------------------------------------------------ writer
        class W
        {
            public readonly StringBuilder Sb = new StringBuilder(1 << 20);
            public void L(string s) { Sb.Append(s).Append("\r\n"); }
            public void L(string fmt, params object[] a) { Sb.AppendFormat(CI, fmt, a).Append("\r\n"); }
        }

        static void WriteMap(W w, string ind, string tag, string mapName, int subno, string bitmap, int channel)
        {
            w.L(ind + tag + " {");
            string i2 = ind + "\t";
            w.L(i2 + "*MAP_NAME " + Q(mapName));
            w.L(i2 + "*MAP_CLASS \"Bitmap\"");
            w.L(i2 + "*MAP_SUBNO " + subno.ToString(CI));
            w.L(i2 + "*MAP_AMOUNT 1.0000");
            w.L(i2 + "*BITMAP " + Q(bitmap));
            w.L(i2 + "*MAP_TYPE Screen");
            w.L(i2 + "*MAP_CHANNEL " + channel.ToString(CI));
            foreach (var kv in new[]
            {
                ("UVW_U_OFFSET", "0.0000"), ("UVW_V_OFFSET", "0.0000"), ("UVW_U_TILING", "1.0000"),
                ("UVW_V_TILING", "1.0000"), ("UVW_ANGLE", "0.0000"), ("UVW_BLUR", "1.0000"),
                ("UVW_BLUR_OFFSET", "0.0000"), ("UVW_NOUSE_AMT", "1.0000"), ("UVW_NOISE_SIZE", "1.0000"),
                ("UVW_NOISE_LEVEL", "1"), ("UVW_NOISE_PHASE", "0.0000"),
            })
                w.L(i2 + "*" + kv.Item1 + " " + kv.Item2);
            w.L(i2 + "*BITMAP_FILTER Pyramidal");
            w.L(ind + "}");
        }

        static void WriteMaterial(W w, Scene sc, int idx, Material m, string ind)
        {
            string name = m.PtName();
            if (name.Length == 0) name = (m.Index + 1).ToString(CI) + " - Default";
            w.L(ind + "*SUBMATERIAL " + idx.ToString(CI) + " {");
            string i2 = ind + "\t";
            var d = m.Diffuse;
            w.L(i2 + "*MATERIAL_NAME " + Q(name));
            w.L(i2 + "*MATERIAL_CLASS \"Standard\"");
            w.L(i2 + "*MATERIAL_AMBIENT " + F4(d[0]) + "\t" + F4(d[1]) + "\t" + F4(d[2]));
            w.L(i2 + "*MATERIAL_DIFFUSE " + F4(d[0]) + "\t" + F4(d[1]) + "\t" + F4(d[2]));
            w.L(i2 + "*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000");
            w.L(i2 + "*MATERIAL_SHINE 0.1000");
            w.L(i2 + "*MATERIAL_SHINESTRENGTH 0.0000");
            w.L(i2 + "*MATERIAL_TRANSPARENCY " + F4(m.Transparency));
            w.L(i2 + "*MATERIAL_WIRESIZE 1.0000");
            w.L(i2 + "*MATERIAL_SHADING Blinn");
            w.L(i2 + "*MATERIAL_XP_FALLOFF 0.0000");
            w.L(i2 + "*MATERIAL_SELFILLUM " + F4(m.SelfIllum));
            if (m.TwoSided != 0) w.L(i2 + "*MATERIAL_TWOSIDED");
            w.L(i2 + "*MATERIAL_FALLOFF In");
            w.L(i2 + "*MATERIAL_XP_TYPE " + (m.BlendType == 4 || m.BlendType == 5 ? "Additive" : "Filter"));
            w.L(i2 + "*PT_MATERIAL {");
            w.L(i2 + "\t*PT_INDEX " + m.Index.ToString(CI));
            w.L(i2 + "\t*PT_BLEND " + (Material.BlendTypeNames.TryGetValue(m.BlendType, out string bn) ? bn : m.BlendType.ToString(CI)));
            w.L(i2 + "\t*PT_USESTATE " + m.UseState.ToString(CI));
            w.L(i2 + "\t*PT_COLLISION " + (m.IsCollision ? "1" : "0"));
            w.L(i2 + "\t*PT_TEXTYPE " + m.TextureType.ToString(CI));
            if (m.AnimTextures.Count > 0)
            {
                w.L(i2 + "\t*PT_ANIM_SPEED " + m.AnimSpeedShift.ToString(CI));
                foreach (var t in m.AnimTextures) w.L(i2 + "\t*PT_ANIM_FRAME " + Q(Tp(sc, t.name)));
            }
            w.L(i2 + "}");
            var layers = new List<(string name, string nameA)>(m.Textures);
            if (layers.Count == 0 && m.AnimTextures.Count > 0) layers.Add(m.AnimTextures[0]);
            for (int k = 0; k < layers.Count; k++)
            {
                string lm = k < 8 ? m.LayerMapName(k) : "";
                if (k == 0)
                    WriteMap(w, i2, "*MAP_DIFFUSE", lm.Length > 0 ? lm : "Map #" + (m.Index * 8 + 1).ToString(CI), 1, Tp(sc, layers[k].name), 1);
                else
                    WriteMap(w, i2, "*MAP_SELFILLUM", lm.Length > 0 ? lm : "Map #" + (m.Index * 8 + 1 + k).ToString(CI), 5, Tp(sc, layers[k].name), k + 1);
            }
            if (layers.Count > 0)
            {
                var l0 = layers[0];
                if (m.MapOpacity != 0 || l0.nameA.Length > 0)
                {
                    string op = l0.nameA.Length > 0 ? l0.nameA : l0.name;
                    WriteMap(w, i2, "*MAP_OPACITY", "Map #" + (m.Index * 8 + 7).ToString(CI), 6, Tp(sc, op), 1);
                }
            }
            w.L(ind + "}");
        }

        static void WriteTm(W w, GeomObject go, string ind)
        {
            w.L(ind + "*NODE_TM {");
            string i2 = ind + "\t";
            var aa = RowsToAxisAngle(go.Rows);
            w.L(i2 + "*NODE_NAME " + Q(go.Name));
            w.L(i2 + "*INHERIT_POS 0 0 0");
            w.L(i2 + "*INHERIT_ROT 0 0 0");
            w.L(i2 + "*INHERIT_SCL 0 0 0");
            for (int r = 0; r < 3; r++)
                w.L(i2 + "*TM_ROW" + r + " " + F4(go.Rows[r][0]) + "\t" + F4(go.Rows[r][1]) + "\t" + F4(go.Rows[r][2]));
            var p = go.Pos;
            w.L(i2 + "*TM_ROW3 " + F(p[0]) + "\t" + F(p[1]) + "\t" + F(p[2]));
            w.L(i2 + "*TM_POS " + F(p[0]) + "\t" + F(p[1]) + "\t" + F(p[2]));
            w.L(i2 + "*TM_ROTAXIS " + F4(aa.axis[0]) + "\t" + F4(aa.axis[1]) + "\t" + F4(aa.axis[2]));
            w.L(i2 + "*TM_ROTANGLE " + F4(aa.ang));
            w.L(i2 + "*TM_SCALE " + F4(aa.scale[0]) + "\t" + F4(aa.scale[1]) + "\t" + F4(aa.scale[2]));
            w.L(i2 + "*TM_SCALEAXIS 0.0000\t0.0000\t0.0000");
            w.L(i2 + "*TM_SCALEAXISANG 0.0000");
            w.L(ind + "}");
        }

        static void WriteUvBlock(W w, string ind, double[][] chFaces)
        {
            var tv = new Dictionary<string, int>(StringComparer.Ordinal);
            var tlist = new List<string>();
            var tfaces = new List<int[]>(chFaces.Length);
            foreach (var tri in chFaces)
            {
                var idx = new int[3];
                for (int j = 0; j < 3; j++)
                {
                    string key = F6(tri[j * 2]) + "\t" + F6(tri[j * 2 + 1]);
                    if (!tv.TryGetValue(key, out int k))
                    {
                        k = tv[key] = tlist.Count;
                        tlist.Add(key);
                    }
                    idx[j] = k;
                }
                tfaces.Add(idx);
            }
            w.L(ind + "*MESH_NUMTVERTEX " + tlist.Count.ToString(CI));
            if (tlist.Count > 0)
            {
                w.L(ind + "*MESH_TVERTLIST {");
                for (int i = 0; i < tlist.Count; i++)
                    w.L(ind + "\t*MESH_TVERT " + i.ToString(CI) + "\t" + tlist[i] + "\t0.0000");
                w.L(ind + "}");
            }
            w.L(ind + "*MESH_NUMTVFACES " + tfaces.Count.ToString(CI));
            if (tfaces.Count > 0)
            {
                w.L(ind + "*MESH_TFACELIST {");
                for (int i = 0; i < tfaces.Count; i++)
                    w.L(ind + "\t*MESH_TFACE " + i.ToString(CI) + "\t" + tfaces[i][0] + "\t" + tfaces[i][1] + "\t" + tfaces[i][2]);
                w.L(ind + "}");
            }
        }

        static void WriteGeom(W w, GeomObject go)
        {
            w.L("*GEOMOBJECT {");
            w.L("\t*NODE_NAME " + Q(go.Name));
            if (go.Parent.Length > 0) w.L("\t*NODE_PARENT " + Q(go.Parent));
            WriteTm(w, go, "\t");
            w.L("\t*MESH {");
            w.L("\t\t*TIMEVALUE 0");
            w.L("\t\t*MESH_NUMVERTEX " + go.Verts.Count.ToString(CI));
            w.L("\t\t*MESH_NUMFACES " + go.Faces.Count.ToString(CI));
            w.L("\t\t*MESH_VERTEX_LIST {");
            for (int i = 0; i < go.Verts.Count; i++)
            {
                var v = go.Verts[i];
                w.L("\t\t\t*MESH_VERTEX " + i.ToString(CI).PadLeft(5) + "\t" + F(v[0]) + "\t" + F(v[1]) + "\t" + F(v[2]));
            }
            w.L("\t\t}");
            w.L("\t\t*MESH_FACE_LIST {");
            for (int i = 0; i < go.Faces.Count; i++)
            {
                var f = go.Faces[i];
                w.L("\t\t\t*MESH_FACE " + i.ToString(CI).PadLeft(5) + ":    A: " + f[0].ToString(CI).PadLeft(5) +
                    " B: " + f[1].ToString(CI).PadLeft(5) + " C: " + f[2].ToString(CI).PadLeft(5) +
                    " AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID " + f[3].ToString(CI));
            }
            w.L("\t\t}");
            // Extra mapping channels BEFORE the main UV list: legacy ASE importers that
            // don't understand MESH_MAPPINGCHANNEL still end up with channel 1.
            for (int k = 1; k < go.Channels.Count; k++)
            {
                w.L("\t\t*MESH_MAPPINGCHANNEL " + (k + 1).ToString(CI) + " {");
                WriteUvBlock(w, "\t\t\t", go.Channels[k]);
                w.L("\t\t}");
            }
            WriteUvBlock(w, "\t\t", go.Channels.Count > 0 ? go.Channels[0] : new double[0][]);
            if (go.Colors != null)
            {
                w.L("\t\t*MESH_NUMCVERTEX " + go.Colors.Count.ToString(CI));
                w.L("\t\t*MESH_CVERTLIST {");
                for (int i = 0; i < go.Colors.Count; i++)
                {
                    var c = go.Colors[i];
                    w.L("\t\t\t*MESH_VERTCOL " + i.ToString(CI) + "\t" + F4(c[0]) + "\t" + F4(c[1]) + "\t" + F4(c[2]));
                }
                w.L("\t\t}");
                w.L("\t\t*MESH_NUMCVFACES " + go.Faces.Count.ToString(CI));
                w.L("\t\t*MESH_CFACELIST {");
                for (int i = 0; i < go.Faces.Count; i++)
                {
                    var f = go.Faces[i];
                    w.L("\t\t\t*MESH_CFACE " + i.ToString(CI) + "\t" + f[0] + "\t" + f[1] + "\t" + f[2]);
                }
                w.L("\t\t}");
            }
            w.L("\t}");
            w.L("\t*PROP_MOTIONBLUR 0");
            w.L("\t*PROP_CASTSHADOW 1");
            w.L("\t*PROP_RECVSHADOW 1");
            WriteAnim(w, go);
            w.L("\t*MATERIAL_REF 0");
            if (go.Physique != null && go.Physique.Length > 0)
            {
                // one bone per vertex - exactly what 3ds Max Physique exported for PT
                // (a few monsters leave vertices without a bone: they stay put, so they are not assigned)
                var assigned = new List<int>();
                for (int i = 0; i < go.Physique.Length; i++) if (go.Physique[i].Length > 0) assigned.Add(i);
                w.L("\t*PHYSIQUE {");
                w.L("\t\t*PHYSIQUE_NUMVERTEXASSIGNMENT\t" + assigned.Count.ToString(CI));
                foreach (int i in assigned)
                    w.L("\t\t*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE " + i.ToString(CI) + "\t" + Q(go.Physique[i]));
                w.L("\t}");
            }
            w.L("}");
        }

        // Keys exactly as 3ds Max's ASE exporter wrote them for PT: position = parent-relative,
        // rotation = delta from the previous key (axis + angle; the first key is absolute),
        // scale = absolute.  Rotation deltas get nine decimals: a class skeleton chains ~10000 of them.
        static void WriteAnim(W w, GeomObject go)
        {
            if (go.PosKeys.Count == 0 && go.RotKeys.Count == 0 && go.ScaleKeys.Count == 0) return;
            w.L("\t*TM_ANIMATION {");
            w.L("\t\t*NODE_NAME " + Q(go.Name));
            if (go.PosKeys.Count > 0)
            {
                w.L("\t\t*CONTROL_POS_TRACK {");
                foreach (var k in go.PosKeys)
                    w.L("\t\t\t*CONTROL_POS_SAMPLE " + k.t.ToString(CI) + "\t" + F6(k.x) + "\t" + F6(k.y) + "\t" + F6(k.z));
                w.L("\t\t}");
            }
            if (go.RotKeys.Count > 0)
            {
                w.L("\t\t*CONTROL_ROT_TRACK {");
                foreach (var k in go.RotKeys)
                    w.L("\t\t\t*CONTROL_ROT_SAMPLE " + k.t.ToString(CI) + "\t" + F9(k.axis[0]) + "\t" + F9(k.axis[1]) + "\t" + F9(k.axis[2]) + "\t" + F9(k.ang));
                w.L("\t\t}");
            }
            if (go.ScaleKeys.Count > 0)
            {
                w.L("\t\t*CONTROL_SCALE_TRACK {");
                foreach (var k in go.ScaleKeys)
                    w.L("\t\t\t*CONTROL_SCALE_SAMPLE " + k.t.ToString(CI) + "\t" + F6(k.x) + "\t" + F6(k.y) + "\t" + F6(k.z) + "\t0.0000\t0.0000\t0.0000\t0.0000");
                w.L("\t\t}");
            }
            w.L("\t}");
        }

        // Skeleton bone as a 3ds Max helper (PT's own Biped exports used Dummy helpers for the
        // Nub bones; the game reads helpers and meshes alike).
        static void WriteBone(W w, GeomObject go)
        {
            // a mesh object WITHOUT a material, exactly as 3ds Max Biped exported bones for PT:
            // the game puts material-less meshes (with their animation) into the .smb and ignores helpers
            w.L("*GEOMOBJECT {");
            w.L("\t*NODE_NAME " + Q(go.Name));
            if (go.Parent.Length > 0) w.L("\t*NODE_PARENT " + Q(go.Parent));
            WriteTm(w, go, "\t");
            w.L("\t*MESH {");
            w.L("\t\t*TIMEVALUE 0");
            w.L("\t\t*MESH_NUMVERTEX " + go.Verts.Count.ToString(CI));
            w.L("\t\t*MESH_NUMFACES " + go.Faces.Count.ToString(CI));
            w.L("\t\t*MESH_VERTEX_LIST {");
            for (int i = 0; i < go.Verts.Count; i++)
            {
                var v = go.Verts[i];
                w.L("\t\t\t*MESH_VERTEX " + i.ToString(CI).PadLeft(5) + "\t" + F4(v[0]) + "\t" + F4(v[1]) + "\t" + F4(v[2]));
            }
            w.L("\t\t}");
            w.L("\t\t*MESH_FACE_LIST {");
            for (int i = 0; i < go.Faces.Count; i++)
            {
                var f = go.Faces[i];
                w.L("\t\t\t*MESH_FACE " + i.ToString(CI).PadLeft(5) + ":    A: " + f[0].ToString(CI).PadLeft(5) +
                    " B: " + f[1].ToString(CI).PadLeft(5) + " C: " + f[2].ToString(CI).PadLeft(5) +
                    " AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID 0");
            }
            w.L("\t\t}");
            w.L("\t\t*MESH_NUMTVERTEX 0");
            w.L("\t}");
            w.L("\t*PROP_MOTIONBLUR 0");
            w.L("\t*PROP_CASTSHADOW 1");
            w.L("\t*PROP_RECVSHADOW 1");
            WriteAnim(w, go);
            w.L("\t*WIREFRAME_COLOR 0.6510\t0.7922\t0.9412");
            w.L("}");
        }

        // PT extension: which skeleton animates this file and the named motions on its timeline
        // (from the game's .inx motion table).  Other ASE readers skip it.
        static void WriteMotions(W w, Scene sc)
        {
            if (sc.AnimMode == "none" && sc.Motions.Count == 0) return;
            w.L("*PT_ANIMATION {");
            w.L("\t*PT_SKELETON " + Q(sc.SkeletonFile));
            if (sc.AnimFile.Length > 0) w.L("\t*PT_ANIMATION_FILE " + Q(sc.AnimFile));
            if (sc.MotionFile.Length > 0) w.L("\t*PT_MOTION_FILE " + Q(sc.MotionFile));
            foreach (var m in sc.Motions)
                w.L("\t*PT_MOTION " + Q(m.Name) + "\t" + m.Start.ToString(CI) + "\t" + m.End.ToString(CI) + "\t" + (m.Loop ? "1" : "0"));
            w.L("}");
        }

        static void WriteLight(W w, int i, Light L)
        {
            string nm = L.Name() + i.ToString("00", CI);
            w.L("*LIGHTOBJECT {");
            w.L("\t*NODE_NAME " + Q(nm));
            w.L("\t*LIGHT_TYPE Omni");
            w.L("\t*NODE_TM {");
            w.L("\t\t*NODE_NAME " + Q(nm));
            w.L("\t\t*INHERIT_POS 0 0 0");
            w.L("\t\t*INHERIT_ROT 0 0 0");
            w.L("\t\t*INHERIT_SCL 0 0 0");
            w.L("\t\t*TM_ROW0 1.0000\t0.0000\t0.0000");
            w.L("\t\t*TM_ROW1 0.0000\t1.0000\t0.0000");
            w.L("\t\t*TM_ROW2 0.0000\t0.0000\t1.0000");
            w.L("\t\t*TM_ROW3 " + F(L.X) + "\t" + F(L.Y) + "\t" + F(L.Z));
            w.L("\t\t*TM_POS " + F(L.X) + "\t" + F(L.Y) + "\t" + F(L.Z));
            w.L("\t\t*TM_ROTAXIS 0.0000\t0.0000\t0.0000");
            w.L("\t\t*TM_ROTANGLE 0.0000");
            w.L("\t\t*TM_SCALE 1.0000\t1.0000\t1.0000");
            w.L("\t\t*TM_SCALEAXIS 0.0000\t0.0000\t0.0000");
            w.L("\t\t*TM_SCALEAXISANG 0.0000");
            w.L("\t}");
            w.L("\t*LIGHT_SHADOWS Off");
            w.L("\t*LIGHT_USELIGHT 1");
            w.L("\t*LIGHT_SPOTSHAPE Circle");
            w.L("\t*LIGHT_USEGLOBAL 0");
            w.L("\t*LIGHT_ABSMAPBIAS 0");
            w.L("\t*LIGHT_OVERSHOOT 0");
            w.L("\t*LIGHT_SETTINGS {");
            w.L("\t\t*TIMEVALUE 0");
            w.L("\t\t*LIGHT_COLOR " + F4(L.R / 255.0) + "\t" + F4(L.G / 255.0) + "\t" + F4(L.B / 255.0));
            w.L("\t\t*LIGHT_INTENS 1.0000");
            w.L("\t\t*LIGHT_ASPECT -1.0000");
            w.L("\t\t*LIGHT_ATTNSTART 0.0000");
            w.L("\t\t*LIGHT_ATTNEND " + F4(L.Range));
            w.L("\t\t*LIGHT_MAPBIAS 1.0000");
            w.L("\t\t*LIGHT_MAPRANGE 4.0000");
            w.L("\t\t*LIGHT_MAPSIZE 512");
            w.L("\t\t*LIGHT_RAYBIAS 0.0000");
            w.L("\t}");
            w.L("}");
        }

        public static void WriteAse(Scene sc, string outPath)
        {
            var w = new W();
            w.L("*3DSMAX_ASCIIEXPORT\t200");
            w.L("*COMMENT \"AsciiExport Version  2.00 - PT smd2ase from " + Path.GetFileName(sc.Source) + "\"");
            w.L("*SCENE {");
            w.L("\t*SCENE_FILENAME " + Q(sc.Name + ".max"));
            w.L("\t*SCENE_FIRSTFRAME 0");
            w.L("\t*SCENE_LASTFRAME " + sc.LastFrame.ToString(CI));
            w.L("\t*SCENE_FRAMESPEED 30");
            w.L("\t*SCENE_TICKSPERFRAME 160");
            w.L("\t*SCENE_BACKGROUND_STATIC 0.0000\t0.0000\t0.0000");
            w.L("\t*SCENE_AMBIENT_STATIC 0.0000\t0.0000\t0.0000");
            w.L("}");
            WriteMotions(w, sc);
            w.L("*MATERIAL_LIST {");
            w.L("\t*MATERIAL_COUNT 1");
            w.L("\t*MATERIAL 0 {");
            w.L("\t\t*MATERIAL_NAME " + Q("PT_" + sc.Name));
            w.L("\t\t*MATERIAL_CLASS \"Multi/Sub-Object\"");
            w.L("\t\t*MATERIAL_AMBIENT 0.5880\t0.5880\t0.5880");
            w.L("\t\t*MATERIAL_DIFFUSE 0.5880\t0.5880\t0.5880");
            w.L("\t\t*MATERIAL_SPECULAR 0.9000\t0.9000\t0.9000");
            w.L("\t\t*MATERIAL_SHINE 0.1000");
            w.L("\t\t*MATERIAL_SHINESTRENGTH 0.0000");
            w.L("\t\t*MATERIAL_TRANSPARENCY 0.0000");
            w.L("\t\t*MATERIAL_WIRESIZE 1.0000");
            w.L("\t\t*NUMSUBMTLS " + sc.Materials.Count.ToString(CI));
            for (int i = 0; i < sc.Materials.Count; i++) WriteMaterial(w, sc, i, sc.Materials[i], "\t\t");
            w.L("\t}");
            w.L("}");
            foreach (var go in sc.Objects)
            {
                if (go.IsBone) WriteBone(w, go);
                else WriteGeom(w, go);
            }
            for (int i = 0; i < sc.Lights.Count; i++) WriteLight(w, i, sc.Lights[i]);
            string d = Path.GetDirectoryName(Path.GetFullPath(outPath));
            if (!string.IsNullOrEmpty(d)) Directory.CreateDirectory(d);
            File.WriteAllText(outPath, w.Sb.ToString(), Bin.Latin1);
        }

        /// <summary>Convert one .smd to .ase (textures resolved/decoded per options).</summary>
        public static Scene ConvertFile(string smdPath, string outPath, ConvertOptions opt = null)
        {
            opt = opt ?? new ConvertOptions();
            var sc = Build(smdPath, opt);
            ResolveTextures(sc, opt, smdPath);
            WriteAse(sc, outPath);
            if (sc.AnimFile.Length > 0)
            {
                // shared class animation (m1_motions.ase ...): written once per output folder
                string ap = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(outPath)), sc.AnimFile);
                if (!File.Exists(ap) || File.GetLastWriteTimeUtc(ap) < File.GetLastWriteTimeUtc(sc.Skeleton.Path))
                    WriteAse(BuildAnimScene(sc), ap);
            }
            return sc;
        }
    }
}
