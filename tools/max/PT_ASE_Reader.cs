// PT_ASE_Reader.cs - fast ASE (3ds Max ASCII Scene Export) parser for the
// PT ASE Importer MAXScript.  Compiled at runtime by MAXScript (no SDK needed).
//
// Produces, per GEOMOBJECT, MAXScript array literals (1-based indices) that the
// script turns into data with execute() - much faster than looping in MAXScript.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace PTAse
{
    public class Node
    {
        public string Key;
        public string Args;
        public List<Node> Kids;
        public Node(string k, string a) { Key = k; Args = a; }
        public Node Find(string k)
        {
            if (Kids == null) return null;
            foreach (Node n in Kids) if (n.Key == k) return n;
            return null;
        }
        public List<Node> FindAll(string k)
        {
            List<Node> r = new List<Node>();
            if (Kids != null) foreach (Node n in Kids) if (n.Key == k) r.Add(n);
            return r;
        }
        public string Val(string k, string def)
        {
            Node n = Find(k);
            return n == null ? def : n.Args;
        }
    }

    public static class U
    {
        public static readonly CultureInfo CI = CultureInfo.InvariantCulture;
        public static double D(string s)
        {
            double v;
            if (double.TryParse(s, NumberStyles.Float, CI, out v) && !double.IsNaN(v) && !double.IsInfinity(v)) return v;
            return 0.0;
        }
        public static int I(string s)
        {
            int v;
            if (int.TryParse(s, NumberStyles.Integer, CI, out v)) return v;
            return (int)D(s);
        }
        public static string[] Split(string s)
        {
            return s.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        }
        public static double[] Ds(string s, int n)
        {
            string[] p = Split(s);
            double[] r = new double[n];
            for (int i = 0; i < n && i < p.Length; i++) r[i] = D(p[i]);
            return r;
        }
        public static string Unq(string s)
        {
            if (s == null) return "";
            s = s.Trim();
            if (s.Length >= 2 && s[0] == '"' && s[s.Length - 1] == '"') return s.Substring(1, s.Length - 2);
            return s;
        }
        public static string F(double v)
        {
            if (Math.Abs(v) < 1e-9) return "0.0";
            string s = v.ToString("0.0#######", CI);
            return s;
        }
        // MAXScript verbatim string literal
        public static string MS(string s)
        {
            return "@\"" + (s ?? "").Replace("\"", "'") + "\"";
        }
    }

    public class Parser
    {
        public static Node Parse(string path)
        {
            Node root = new Node("ROOT", "");
            root.Kids = new List<Node>();
            Stack<Node> st = new Stack<Node>();
            st.Push(root);
            using (StreamReader r = new StreamReader(path, Encoding.GetEncoding(1252)))
            {
                string line;
                while ((line = r.ReadLine()) != null)
                {
                    string s = line.Trim();
                    if (s.Length == 0) continue;
                    if (s[0] == '}') { if (st.Count > 1) st.Pop(); continue; }
                    if (s[0] != '*') continue;
                    int sp = s.IndexOfAny(new char[] { ' ', '\t' });
                    string key = sp < 0 ? s : s.Substring(0, sp);
                    string args = sp < 0 ? "" : s.Substring(sp + 1).Trim();
                    Node parent = st.Peek();
                    if (parent.Kids == null) parent.Kids = new List<Node>();
                    if (args.EndsWith("{"))
                    {
                        Node n = new Node(key, args.Substring(0, args.Length - 1).Trim());
                        n.Kids = new List<Node>();
                        parent.Kids.Add(n);
                        st.Push(n);
                    }
                    else parent.Kids.Add(new Node(key, args));
                }
            }
            return root;
        }
    }

    // ------------------------------------------------------------------ materials
    public class MapDef
    {
        public string Name = "", Bitmap = "";
        public int Channel = 1;
        public double UOff, VOff, UTile = 1, VTile = 1, Angle;
        public MapDef(Node n)
        {
            Name = U.Unq(n.Val("*MAP_NAME", ""));
            Node bm = FirstBitmap(n);
            if (bm != null)
            {
                Bitmap = U.Unq(bm.Val("*BITMAP", ""));
                Channel = Math.Max(1, U.I(bm.Val("*MAP_CHANNEL", "1")));
                UOff = U.D(bm.Val("*UVW_U_OFFSET", "0"));
                VOff = U.D(bm.Val("*UVW_V_OFFSET", "0"));
                UTile = U.D(bm.Val("*UVW_U_TILING", "1"));
                VTile = U.D(bm.Val("*UVW_V_TILING", "1"));
                Angle = U.D(bm.Val("*UVW_ANGLE", "0"));
            }
        }
        static Node FirstBitmap(Node n)
        {
            if (n.Find("*BITMAP") != null) return n;
            if (n.Kids != null)
                foreach (Node k in n.Kids)
                    if (k.Kids != null) { Node r = FirstBitmap(k); if (r != null) return r; }
            return null;
        }
    }

    public class MatDef
    {
        public string Name, Cls;
        public double[] Diffuse;
        public double Transparency, SelfIllum;
        public bool TwoSided, Additive, Collision, IsPT;
        public MapDef DiffuseMap, OpacityMap;
        public List<MapDef> Layers = new List<MapDef>();
        public int NumSubs;
        public SortedDictionary<int, MatDef> Subs = new SortedDictionary<int, MatDef>();

        public MatDef(Node n)
        {
            Name = U.Unq(n.Val("*MATERIAL_NAME", "Material"));
            Cls = U.Unq(n.Val("*MATERIAL_CLASS", "Standard"));
            Diffuse = U.Ds(n.Val("*MATERIAL_DIFFUSE", "0.588 0.588 0.588"), 3);
            Transparency = U.D(n.Val("*MATERIAL_TRANSPARENCY", "0"));
            SelfIllum = U.D(n.Val("*MATERIAL_SELFILLUM", "0"));
            TwoSided = n.Find("*MATERIAL_TWOSIDED") != null;
            Additive = n.Val("*MATERIAL_XP_TYPE", "") == "Additive";
            Node pt = n.Find("*PT_MATERIAL");
            IsPT = pt != null;
            if (pt != null)
            {
                Collision = pt.Val("*PT_COLLISION", "0") == "1";
                string bl = pt.Val("*PT_BLEND", "");
                if (bl == "lamp" || bl == "addcolor") Additive = true;
            }
            if (n.Kids != null)
                foreach (Node k in n.Kids)
                {
                    if (k.Key == "*MAP_DIFFUSE" && DiffuseMap == null) DiffuseMap = new MapDef(k);
                    else if (k.Key == "*MAP_SELFILLUM") Layers.Add(new MapDef(k));
                    else if (k.Key == "*MAP_OPACITY") OpacityMap = new MapDef(k);
                }
            if (!IsPT && DiffuseMap == null && (Name.Contains("wall:"))) Collision = true;
            NumSubs = U.I(n.Val("*NUMSUBMTLS", "0"));
            foreach (Node s in n.FindAll("*SUBMATERIAL"))
            {
                string[] p = U.Split(s.Args);
                if (p.Length == 0) continue;
                int idx = U.I(p[0]);
                if (!Subs.ContainsKey(idx)) Subs[idx] = new MatDef(s);
            }
        }

        public MatDef Unshell()
        {
            MatDef m = this;
            while (m.Cls == "Shell Material" && m.Subs.Count > 0)
            {
                MatDef s;
                if (!m.Subs.TryGetValue(0, out s)) foreach (MatDef v in m.Subs.Values) { s = v; break; }
                m = s;
            }
            return m;
        }

        // leaf material for a face MTLID (3ds Max semantics: modulo NUMSUBMTLS)
        public MatDef Resolve(int mtlid)
        {
            MatDef m = Unshell();
            if (m.Subs.Count > 0 || m.NumSubs > 0)
            {
                int n = m.NumSubs;
                if (n <= 0) foreach (int k in m.Subs.Keys) n = Math.Max(n, k + 1);
                if (n <= 0) n = 1;
                MatDef s;
                if (!m.Subs.TryGetValue(((mtlid % n) + n) % n, out s)) return null;
                return s.Unshell().Subs.Count > 0 ? s.Unshell().Resolve(0) : s.Unshell();
            }
            return m;
        }
    }

    // ------------------------------------------------------------------ geometry
    // ------------------------------------------------------------------ skeleton + animation
    // Characters / monsters: Bip01 bones (helpers or meshes) with bind-pose NODE_TMs, skinned
    // meshes with a *PHYSIQUE block (one bone per vertex) and TM_ANIMATION per bone:
    //   CONTROL_POS_SAMPLE  tick x y z         position relative to the parent
    //   CONTROL_ROT_SAMPLE  tick ax ay az ang  turn from the previous key (first key absolute)
    //   CONTROL_SCALE_SAMPLE tick sx sy sz ...
    // Player bodies/heads keep the animation in a shared file named by *PT_ANIMATION_FILE.
    public class Rig
    {
        public class Bone
        {
            public string Name, Parent;
            public int ParentIndex = -1;
            public double[] Bind;                 // 12 doubles, rows (orthonormal)
            public double[] Raw;                  // the rows exactly as written in the file (for export)
            public string PosKeys = "#()", RotKeys = "#()", ScaleKeys = "#()";
            public int KeyCount;
            public double Size = 1.0;
        }
        public List<Bone> Bones = new List<Bone>();
        public string Motions = "#()";            // #(#(name, start, end, loop), ...)
        public string AnimFile = "", AnimMissing = "";
        public int LastFrame;
        Dictionary<string, int> index = new Dictionary<string, int>();

        static List<Node> Nodes(Node root)
        {
            List<Node> outl = new List<Node>();
            if (root.Kids == null) return outl;
            foreach (Node k in root.Kids)
            {
                if (k.Key == "*GEOMOBJECT" || k.Key == "*HELPEROBJECT") outl.Add(k);
                else if (k.Key == "*GROUP") outl.AddRange(Nodes(k));
            }
            return outl;
        }
        static string Name(Node n) { return U.Unq(n.Val("*NODE_NAME", "")); }

        public static bool IsCharacter(Node root)
        {
            if (root.Find("*PT_ANIMATION") != null) return true;
            bool any = false, allBip = true;
            foreach (Node n in Nodes(root))
            {
                if (n.Find("*PHYSIQUE") != null) return true;
                if (n.Find("*TM_ANIMATION") != null)
                {
                    any = true;
                    if (!Name(n).ToLowerInvariant().StartsWith("bip")) allBip = false;
                }
            }
            return any && allBip;
        }

        static readonly char[] Blank = { ' ', '\t' };

        // Bone name per vertex of a skinned mesh, as the game's ASE reader (smRead3d.cpp) takes it:
        // line by line at any depth (3ds Max nests them in *PHYSIQUE_VERTEXASSIGNMENT_LIST); a
        // blended vertex takes the node listed first (number 0).
        public static Dictionary<int, string> PhysMap(Node g)
        {
            Dictionary<int, string> r = new Dictionary<int, string>();
            Node ph = g.Find("*PHYSIQUE");
            if (ph != null) PhysWalk(ph, r, new int[] { -1 });
            return r;
        }
        static void PhysWalk(Node n, Dictionary<int, string> r, int[] blended)
        {
            if (n.Kids == null) return;
            foreach (Node c in n.Kids)
            {
                string a = c.Args.Trim();
                if (c.Key == "*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE")
                {
                    int sp = a.IndexOfAny(Blank);
                    int v;
                    if (sp > 0 && int.TryParse(a.Substring(0, sp), NumberStyles.Integer, U.CI, out v)) r[v] = U.Unq(a.Substring(sp + 1));
                }
                else if (c.Key == "*PHYSIQUE_VERTEXASSIGNMENT_BLENDED_RIGIDTYPE")
                {
                    string[] p = U.Split(a);
                    int v;
                    blended[0] = p.Length > 0 && int.TryParse(p[0], NumberStyles.Integer, U.CI, out v) ? v : -1;
                }
                else if (c.Key == "*PHYSIQUE_VERTEXASSIGNMENT_NODE" && blended[0] >= 0)
                {
                    string[] p = a.Split(Blank, 3, StringSplitOptions.RemoveEmptyEntries);
                    if (p.Length == 3 && p[0] == "0") r[blended[0]] = U.Unq(p[2]);
                }
                PhysWalk(c, r, blended);
            }
        }

        public Rig(Node root, string path, bool animate, string picked)
        {
            List<Node> nodes = Nodes(root);
            Dictionary<string, Node> byName = new Dictionary<string, Node>();
            HashSet<string> used = new HashSet<string>();
            foreach (Node n in nodes)
            {
                byName[Name(n)] = n;
                foreach (string b in PhysMap(n).Values) used.Add(b);
            }
            HashSet<string> isBone = new HashSet<string>();
            foreach (Node n in nodes)
            {
                string nm = Name(n);
                if (n.Find("*PHYSIQUE") != null) continue;
                if (n.Key == "*HELPEROBJECT" || used.Contains(nm) || nm.ToLowerInvariant().StartsWith("bip")
                    || (n.Find("*TM_ANIMATION") != null && n.Find("*MESH") == null)
                    || n.Find("*MATERIAL_REF") == null)          // PT bones are meshes without a material
                    isBone.Add(nm);
            }
            foreach (string nm in new List<string>(isBone))         // parents of bones are bones too
            {
                string p = U.Unq(byName[nm].Val("*NODE_PARENT", ""));
                while (p.Length > 0 && byName.ContainsKey(p) && !isBone.Contains(p))
                {
                    isBone.Add(p);
                    p = U.Unq(byName[p].Val("*NODE_PARENT", ""));
                }
            }
            // ---- where the animation comes from (decided first: it also sets the rest pose)
            //   T-pose        : nothing, bones stay as saved in this file
            //   Animated      : 1) the file picked in the importer, 2) this file's own keys when they
            //                   move most of the skeleton, 3) the shared file a converted character
            //                   names (*PT_ANIMATION_FILE), 4) the class file worked out from the name
            //                   (TfbF01.ASE -> m8_motions.ase) for original artist files.
            Node info = root.Find("*PT_ANIMATION");
            Node animRoot = null;
            int ownAnimated = 0;
            foreach (Node n in nodes) if (isBone.Contains(Name(n)) && n.Find("*TM_ANIMATION") != null) ownAnimated++;
            bool ownOk = ownAnimated >= 0.5 * isBone.Count;
            if (animate)
            {
                if (!string.IsNullOrEmpty(picked) && File.Exists(picked))
                {
                    animRoot = Parser.Parse(picked);
                    AnimFile = Path.GetFileName(picked);
                }
                else if (ownOk) animRoot = root;
                else
                {
                    string want = info != null ? U.Unq(info.Val("*PT_ANIMATION_FILE", "")) : "";
                    if (want.Length == 0) want = ClassAnimationName(path);
                    if (want.Length > 0)
                    {
                        string ap = FindNear(path, want) ?? (string.IsNullOrEmpty(picked) ? null : FindNear(picked, want));
                        if (ap != null) { animRoot = Parser.Parse(ap); AnimFile = want; }
                        else AnimMissing = want;
                    }
                    if (animRoot == null && ownAnimated > 0) animRoot = root;     // better than nothing
                }
            }

            // The game skins a character on its class skeleton, not on the bones saved in the
            // character's own file (costume files often carry older, slightly different bones and
            // even a different parent here and there), so with a separate animation file the rest
            // pose and the hierarchy of every bone it contains come from that file.
            Dictionary<string, double[]> ovTm = new Dictionary<string, double[]>();
            Dictionary<string, double[]> ovRaw = new Dictionary<string, double[]>();
            Dictionary<string, string> ovParent = new Dictionary<string, string>();
            if (animRoot != null && animRoot != root)
                foreach (Node n in Nodes(animRoot))
                {
                    ovTm[Name(n)] = Ortho(Tm(n));
                    ovRaw[Name(n)] = Tm(n);
                    ovParent[Name(n)] = U.Unq(n.Val("*NODE_PARENT", ""));
                }
            Dictionary<string, double[]> own = new Dictionary<string, double[]>();
            Dictionary<string, double[]> ownRaw = new Dictionary<string, double[]>();
            Dictionary<string, string> ownParent = new Dictionary<string, string>();
            foreach (Node n in nodes)
            {
                string nm = Name(n);
                if (!isBone.Contains(nm) || own.ContainsKey(nm)) continue;
                own[nm] = Ortho(Tm(n));
                ownRaw[nm] = Tm(n);
                ownParent[nm] = U.Unq(n.Val("*NODE_PARENT", ""));
            }
            Dictionary<string, string> parent = new Dictionary<string, string>();
            foreach (string nm in own.Keys)
                parent[nm] = ovParent.ContainsKey(nm) && own.ContainsKey(ovParent[nm]) ? ovParent[nm] : ownParent[nm];
            Dictionary<string, double[]> world = new Dictionary<string, double[]>();
            foreach (Node n in nodes)
            {
                string nm = Name(n);
                if (!own.ContainsKey(nm) || index.ContainsKey(nm)) continue;
                Bone b = new Bone { Name = nm, Parent = parent[nm], Bind = Place(nm, own, parent, ovTm, world, 0) };
                b.Raw = ovRaw.ContainsKey(nm) ? ovRaw[nm] : (ovTm.Count == 0 ? ownRaw[nm] : b.Bind);
                index[nm] = Bones.Count;
                Bones.Add(b);
            }
            foreach (Bone b in Bones) b.ParentIndex = index.ContainsKey(b.Parent) ? index[b.Parent] : -1;
            // helper size: a third of the distance to the nearest child
            foreach (Bone b in Bones)
                if (b.ParentIndex >= 0)
                {
                    Bone p = Bones[b.ParentIndex];
                    double d = Math.Sqrt(Sq(b.Bind[9] - p.Bind[9]) + Sq(b.Bind[10] - p.Bind[10]) + Sq(b.Bind[11] - p.Bind[11]));
                    if (d > 0.05) p.Size = p.Size == 1.0 ? Math.Max(0.3, d / 3) : Math.Min(p.Size, Math.Max(0.3, d / 3));
                }
            // own keys go back out with an export (monsters); a shared class animation does not
            AnimSource = animRoot == null ? "" : (animRoot == root ? "own" : "shared");
            // monsters whose animation the game keeps in its own motion file (mGknight ...)
            if (animRoot == root && info != null && info.Find("*PT_MOTION_FILE") != null) AnimSource = "shared";
            if (animRoot == null) return;                              // T-pose

            Node motions = animRoot != root ? animRoot.Find("*PT_ANIMATION") : null;
            if (motions == null || motions.FindAll("*PT_MOTION").Count == 0) motions = info;
            if (motions != null)
            {
                StringBuilder sb = new StringBuilder("#(");
                int k = 0;
                foreach (Node m in motions.FindAll("*PT_MOTION"))
                {
                    string[] q = m.Args.Split('"');
                    if (q.Length < 3) continue;
                    string[] nums = U.Split(q[2]);
                    if (nums.Length < 2) continue;
                    if (k++ > 0) sb.Append(',');
                    sb.Append("#(").Append(U.MS(q[1])).Append(',').Append(U.I(nums[0])).Append(',').Append(U.I(nums[1]))
                      .Append(',').Append(nums.Length > 2 && nums[2] == "1" ? "true" : "false").Append(')');
                }
                Motions = sb.Append(')').ToString();
            }
            Node sceneN = animRoot.Find("*SCENE");
            if (sceneN != null) LastFrame = U.I(sceneN.Val("*SCENE_LASTFRAME", "0"));
            Animated = true;
            foreach (Node n in Nodes(animRoot))
            {
                int bi;
                Node a = n.Find("*TM_ANIMATION");
                if (a == null || !index.TryGetValue(Name(n), out bi)) continue;
                Bone b = Bones[bi];
                // channels without keys: the game uses the bone's own stored local transform
                // (TM_POS / TM_ROTAXIS, else the bind pose as written) and no scale
                Track t = ReadTrack(a, EngineStatic(n, RawLocal(b), U.Unq(n.Val("*NODE_PARENT", "")).Length > 0), false);
                b.PosKeys = t.Pos; b.RotKeys = t.Rot; b.ScaleKeys = t.Scale; b.KeyCount = t.Count;
            }
        }

        public bool Animated;

        // The bone's rest pose relative to its parent exactly as written (may be scaled / skewed)
        double[] RawLocal(Bone b)
        {
            double[] w = b.Raw ?? b.Bind;
            if (b.ParentIndex < 0) return w;
            Bone p = Bones[b.ParentIndex];
            return Mul43(w, Scene.Inverse(p.Raw ?? p.Bind));
        }

        // Rest pose of a bone: from the animation file when it has the bone, else the bone's own
        // offset from its parent, so extra costume bones (hair, tails) stay attached.
        static double[] Place(string nm, Dictionary<string, double[]> own, Dictionary<string, string> parent,
                              Dictionary<string, double[]> ov, Dictionary<string, double[]> world, int depth)
        {
            double[] w;
            if (world.TryGetValue(nm, out w)) return w;
            string p = parent[nm];
            if (ov.ContainsKey(nm)) w = ov[nm];
            else if (ov.Count > 0 && own.ContainsKey(p) && depth < 200)
                w = Mul43(Mul43(own[nm], Inv43(own[p])), Place(p, own, parent, ov, world, depth + 1));
            else w = own[nm];
            world[nm] = w;
            return w;
        }

        // 4x3 row-vector transforms (Max matrix3 layout: rows 0-2 rotation, row 3 translation)
        internal static double[] Mul43(double[] a, double[] b)
        {
            double[] r = new double[12];
            for (int i = 0; i < 4; i++)
                for (int j = 0; j < 3; j++)
                    r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j] + (i == 3 ? b[9 + j] : 0.0);
            return r;
        }
        static double[] Inv43(double[] m)              // orthonormal rotation
        {
            double[] r = { m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8], 0, 0, 0 };
            for (int j = 0; j < 3; j++) r[9 + j] = -(m[9] * r[j] + m[10] * r[3 + j] + m[11] * r[6 + j]);
            return r;
        }

        // Player class skeletons: [C] + race(T/M) + sex(m/f) + part(b/h) + class letter
        static readonly System.Text.RegularExpressions.Regex PlayerRe =
            new System.Text.RegularExpressions.Regex("^c?([tm])([mf])([bh])[-_]?m?([a-f])", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        static readonly Dictionary<string, int> ClassOf = new Dictionary<string, int> {
            { "ta", 1 }, { "tb", 1 }, { "tc", 4 }, { "td", 2 }, { "te", 6 }, { "tf", 8 },
            { "ma", 1 }, { "mb", 2 }, { "mc", 5 }, { "md", 3 }, { "me", 7 } };
        public static string ClassAnimationName(string asePath)
        {
            var m = PlayerRe.Match(Path.GetFileName(asePath));
            int c;
            if (!m.Success || !ClassOf.TryGetValue(m.Groups[1].Value.ToLowerInvariant() + m.Groups[4].Value.ToLowerInvariant(), out c)) return "";
            return "m" + c + "_motions.ase";
        }

        static double Sq(double v) { return v * v; }

        static string FindNear(string asePath, string file)
        {
            string dir = Path.GetDirectoryName(Path.GetFullPath(asePath));
            string p = Path.Combine(dir, file);
            if (File.Exists(p)) return p;
            try
            {
                foreach (string f in Directory.GetFiles(dir))
                    if (string.Equals(Path.GetFileName(f), file, StringComparison.OrdinalIgnoreCase)) return f;
            }
            catch (Exception) { }
            return null;
        }

        static double[] Tm(Node g)
        {
            Node tm = g.Find("*NODE_TM");
            if (tm == null) return new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
            double[] r0 = U.Ds(tm.Val("*TM_ROW0", "1 0 0"), 3), r1 = U.Ds(tm.Val("*TM_ROW1", "0 1 0"), 3);
            double[] r2 = U.Ds(tm.Val("*TM_ROW2", "0 0 1"), 3), r3 = U.Ds(tm.Val("*TM_ROW3", "0 0 0"), 3);
            return new double[] { r0[0], r0[1], r0[2], r1[0], r1[1], r1[2], r2[0], r2[1], r2[2], r3[0], r3[1], r3[2] };
        }

        // Rigid part of a TM (PT bind poses are stored in 8.8 fixed point, a hair off orthonormal).
        static double[] Ortho(double[] m)
        {
            double[] x = Norm(m[0], m[1], m[2]);
            double d = x[0] * m[3] + x[1] * m[4] + x[2] * m[5];
            double[] y = Norm(m[3] - d * x[0], m[4] - d * x[1], m[5] - d * x[2]);
            double[] z = { x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0] };
            if (z[0] * m[6] + z[1] * m[7] + z[2] * m[8] < 0) { z[0] = -z[0]; z[1] = -z[1]; z[2] = -z[2]; }
            return new double[] { x[0], x[1], x[2], y[0], y[1], y[2], z[0], z[1], z[2], m[9], m[10], m[11] };
        }
        static double[] Norm(double a, double b, double c)
        {
            double n = Math.Sqrt(a * a + b * b + c * c);
            if (n < 1e-12) return new double[] { 1, 0, 0 };
            return new double[] { a / n, b / n, c / n };
        }

        // Turn by ang about a unit axis (standard column-vector matrix); the game composes
        // rows_i = rows_(i-1) * M, so M is used directly as Max rows.
        static double[] AxisRows(double x, double y, double z, double ang)
        {
            double c = Math.Cos(ang), s = Math.Sin(ang), C = 1 - c;
            return new double[] {
                c + x * x * C, x * y * C - z * s, x * z * C + y * s,
                y * x * C + z * s, c + y * y * C, y * z * C - x * s,
                z * x * C - y * s, z * y * C + x * s, c + z * z * C };
        }
        static double[] Mul3(double[] a, double[] b)
        {
            double[] r = new double[9];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j];
            return r;
        }

        // ---- keys of one node, as MAXScript literals for linear controllers (parent-relative)
        public class Track
        {
            public string Pos = "#()", Rot = "#()", Scale = "#()";
            public int Count;
            public double LastTick;
        }

        static readonly string[] PosTags = { "*CONTROL_POS_SAMPLE", "*CONTROL_TCB_POS_KEY", "*CONTROL_BEZIER_POS_KEY" };
        static readonly string[] RotTags = { "*CONTROL_ROT_SAMPLE", "*CONTROL_TCB_ROT_KEY" };
        static readonly string[] ScaleTags = { "*CONTROL_SCALE_SAMPLE", "*CONTROL_TCB_SCALE_KEY", "*CONTROL_BEZIER_SCALE_KEY" };

        static void KeyLines(Node n, List<double[]> pos, List<double[]> rot, List<double[]> scl)
        {
            if (n.Kids == null) return;
            foreach (Node c in n.Kids)
            {
                if (Array.IndexOf(PosTags, c.Key) >= 0) pos.Add(U.Ds(c.Args, 4));
                else if (Array.IndexOf(RotTags, c.Key) >= 0) rot.Add(U.Ds(c.Args, 5));
                else if (Array.IndexOf(ScaleTags, c.Key) >= 0) scl.Add(U.Ds(c.Args, 4));
                else KeyLines(c, pos, rot, scl);
            }
        }

        // The keys the game's own ASE reader takes (smRead3d.cpp), whatever block they sit in:
        // sampled keys and 3ds Max TCB / Bezier keys alike, first 4 or 5 numbers (no tangents).
        // A channel without keys gets one key with `rest` (the node's own local transform, which
        // the game uses there); its scale only when restScale (the game scales bones only by keys).
        public static Track ReadTrack(Node anim, double[] rest, bool restScale)
        {
            List<double[]> pos = new List<double[]>(), rot = new List<double[]>(), scl = new List<double[]>();
            KeyLines(anim, pos, rot, scl);
            Track t = new Track();
            if (pos.Count + rot.Count + scl.Count == 0) return t;
            double first = double.MaxValue, last = 0;
            foreach (List<double[]> l in new[] { pos, rot, scl })
                if (l.Count > 0) { first = Math.Min(first, l[0][0]); last = Math.Max(last, l[l.Count - 1][0]); }
            t.LastTick = last;
            // rest = scale x rotation rows (det < 0: negative scale), translation
            double[] sc = new double[3], R0 = new double[9];
            double det = rest[0] * (rest[4] * rest[8] - rest[5] * rest[7]) - rest[1] * (rest[3] * rest[8] - rest[5] * rest[6])
                       + rest[2] * (rest[3] * rest[7] - rest[4] * rest[6]);
            double[] o = Ortho(det < 0 ? new double[] { -rest[0], -rest[1], -rest[2], -rest[3], -rest[4], -rest[5],
                                                        -rest[6], -rest[7], -rest[8], 0, 0, 0 } : rest);
            for (int i = 0; i < 3; i++)
            {
                sc[i] = Math.Sqrt(rest[i * 3] * rest[i * 3] + rest[i * 3 + 1] * rest[i * 3 + 1] + rest[i * 3 + 2] * rest[i * 3 + 2]);
                if (det < 0) sc[i] = -sc[i];
            }
            Array.Copy(o, R0, 9);
            if (pos.Count == 0) pos.Add(new double[] { first, rest[9], rest[10], rest[11] });
            if (scl.Count == 0 && restScale) scl.Add(new double[] { first, sc[0], sc[1], sc[2] });
            t.Pos = Vec3Keys(pos);
            t.Scale = Vec3Keys(scl);
            // absolute local rotation at every key (rows), accumulated in doubles: each key turns the
            // previous orientation by its angle about its axis
            StringBuilder sb = new StringBuilder("#(");
            if (rot.Count == 0) RotKey(sb, first, R0);
            else
            {
                double[] R = { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
                for (int k = 0; k < rot.Count; k++)
                {
                    double[] f = rot[k];
                    double l = Math.Sqrt(f[1] * f[1] + f[2] * f[2] + f[3] * f[3]);
                    if (l > 1e-12) R = Mul3(R, AxisRows(f[1] / l, f[2] / l, f[3] / l, f[4]));
                    if (k > 0) sb.Append(',');
                    RotKey(sb, f[0], R);
                }
            }
            t.Rot = sb.Append(')').ToString();
            t.Count = pos.Count + Math.Max(1, rot.Count) + scl.Count;
            return t;
        }

        // What the game uses for a channel without keys (smRead3d.cpp): *TM_POS and *TM_ROTAXIS /
        // *TM_ROTANGLE, which 3ds Max writes relative to the parent (the rows are world space,
        // rounded to 3-4 decimals: a helper scaled to 0.017 is far off there).  Used when the file
        // has them that way (a root node, or TM_POS away from TM_ROW3) and the node is not mirrored;
        // `rest` (the local transform from the rows) keeps its scale.
        internal static double[] EngineStatic(Node g, double[] rest, bool hasParent)
        {
            Node tm = g.Find("*NODE_TM");
            if (tm == null || tm.Find("*TM_POS") == null || tm.Find("*TM_ROTANGLE") == null) return rest;
            double[] r3 = U.Ds(tm.Val("*TM_ROW3", "0 0 0"), 3), tp = U.Ds(tm.Val("*TM_POS", "0 0 0"), 3);
            bool local = !hasParent || Math.Max(Math.Abs(tp[0] - r3[0]), Math.Max(Math.Abs(tp[1] - r3[1]), Math.Abs(tp[2] - r3[2]))) > 0.01;
            double det = rest[0] * (rest[4] * rest[8] - rest[5] * rest[7]) - rest[1] * (rest[3] * rest[8] - rest[5] * rest[6])
                       + rest[2] * (rest[3] * rest[7] - rest[4] * rest[6]);
            if (!local || det <= 0) return rest;
            double[] ax = U.Ds(tm.Val("*TM_ROTAXIS", "0 0 1"), 3);
            double ang = U.D(tm.Val("*TM_ROTANGLE", "0"));
            double l = Math.Sqrt(ax[0] * ax[0] + ax[1] * ax[1] + ax[2] * ax[2]);
            double[] R = l > 1e-9 ? AxisRows(ax[0] / l, ax[1] / l, ax[2] / l, ang) : new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
            double[] o = new double[12];
            for (int i = 0; i < 3; i++)
            {
                double n = Math.Sqrt(rest[i * 3] * rest[i * 3] + rest[i * 3 + 1] * rest[i * 3 + 1] + rest[i * 3 + 2] * rest[i * 3 + 2]);
                for (int j = 0; j < 3; j++) o[i * 3 + j] = n * R[i * 3 + j];
            }
            o[9] = tp[0]; o[10] = tp[1]; o[11] = tp[2];
            return o;
        }

        static void RotKey(StringBuilder sb, double tick, double[] R)
        {
            sb.Append("#(").Append(G(tick / 160.0)).Append(",(matrix3 [").Append(G(R[0])).Append(',').Append(G(R[1])).Append(',')
              .Append(G(R[2])).Append("] [").Append(G(R[3])).Append(',').Append(G(R[4])).Append(',').Append(G(R[5]))
              .Append("] [").Append(G(R[6])).Append(',').Append(G(R[7])).Append(',').Append(G(R[8])).Append("] [0,0,0]))");
        }

        static string Vec3Keys(List<double[]> keys)
        {
            StringBuilder sb = new StringBuilder("#(");
            for (int k = 0; k < keys.Count; k++)
            {
                double[] f = keys[k];
                if (k > 0) sb.Append(',');
                sb.Append("#(").Append(G(f[0] / 160.0)).Append(",[").Append(G(f[1])).Append(',').Append(G(f[2]))
                  .Append(',').Append(G(f[3])).Append("])");
            }
            return sb.Append(')').ToString();
        }
        static string G(double v) { return Math.Abs(v) < 1e-12 ? "0.0" : v.ToString("0.0#########", U.CI); }
        internal static string M3(double[] m)
        {
            return "(matrix3 [" + G(m[0]) + "," + G(m[1]) + "," + G(m[2]) + "] [" + G(m[3]) + "," + G(m[4]) + "," + G(m[5]) +
                   "] [" + G(m[6]) + "," + G(m[7]) + "," + G(m[8]) + "] [" + G(m[9]) + "," + G(m[10]) + "," + G(m[11]) + "])";
        }

        public string PhysiqueLiteral(Node g, int numVerts)
        {
            int[] idx = new int[numVerts];
            foreach (KeyValuePair<int, string> kv in PhysMap(g))
            {
                int bi;
                if (kv.Key >= 0 && kv.Key < numVerts && index.TryGetValue(kv.Value, out bi)) idx[kv.Key] = bi + 1;
            }
            StringBuilder sb = new StringBuilder("#(");
            for (int i = 0; i < numVerts; i++) { if (i > 0) sb.Append(','); sb.Append(idx[i]); }
            return sb.Append(')').ToString();
        }

        // ---- accessors for MAXScript
        public int Count { get { return Bones.Count; } }
        public string BoneName(int i) { return Bones[i].Name; }
        public int BoneParent(int i) { return Bones[i].ParentIndex; }
        public double BoneSize(int i) { return Bones[i].Size; }
        public int BoneKeyCount(int i) { return Bones[i].KeyCount; }
        public string AnimSource = "";
        public string BoneRaw(int i)
        {
            double[] m = Bones[i].Raw ?? Bones[i].Bind;
            StringBuilder sb = new StringBuilder();
            for (int k = 0; k < 12; k++) { if (k > 0) sb.Append(' '); sb.Append(m[k].ToString("R", U.CI)); }
            return sb.ToString();
        }
        public string BoneTm(int i) { return M3(Bones[i].Bind); }

        // a bone's bind pose as written (null = no such bone)
        internal double[] RawOf(string name)
        {
            int i;
            return index.TryGetValue(name ?? "", out i) ? (Bones[i].Raw ?? Bones[i].Bind) : null;
        }

        // 1-based bone indices, parents before their children
        public string ParentsFirst()
        {
            List<int> order = new List<int>();
            bool[] done = new bool[Bones.Count];
            for (int i = 0; i < Bones.Count; i++) AddUp(i, done, order, 0);
            StringBuilder sb = new StringBuilder("#(");
            for (int k = 0; k < order.Count; k++) { if (k > 0) sb.Append(','); sb.Append(order[k] + 1); }
            return sb.Append(')').ToString();
        }
        void AddUp(int i, bool[] done, List<int> order, int depth)
        {
            if (done[i]) return;
            done[i] = true;                                  // (set first: a parent loop cannot recurse forever)
            int p = Bones[i].ParentIndex;
            if (p >= 0 && depth < 1000) AddUp(p, done, order, depth + 1);
            order.Add(i);
        }

        // The bind pose exactly as written (scaled / skewed): the game skins a vertex on it, so the
        // Skin modifier is bound with the bones there.  "" = same as the rigid rest pose.
        public string BoneBindTm(int i)
        {
            Bone b = Bones[i];
            double[] w = b.Raw;
            if (!Animated || w == null || !Usable(w)) return "";
            for (int k = 0; k < 12; k++) if (Math.Abs(w[k] - b.Bind[k]) > 1e-7) return M3(w);
            return "";
        }

        // A bone without keys in an animated skeleton: the game shows it at its stored local
        // transform (Tm x parent->TmInvert, scale and all).  "" = no keys needed beyond the rest pose.
        public string BoneStatic(int i)
        {
            Bone b = Bones[i];
            if (!Animated || b.KeyCount > 0 || b.Raw == null) return "";
            double[] raw = RawLocal(b);
            if (!Usable(raw)) return "";
            double[] rest = b.ParentIndex >= 0 ? Mul43(b.Bind, Inv43(Bones[b.ParentIndex].Bind)) : b.Bind;
            for (int k = 0; k < 12; k++) if (Math.Abs(raw[k] - rest[k]) > 1e-6) return M3(raw);
            return "";
        }

        internal static bool Usable(double[] m)
        {
            foreach (double v in m) if (double.IsNaN(v) || double.IsInfinity(v)) return false;
            double det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6]);
            return Math.Abs(det) > 1e-9;
        }
        public string PosKeys(int i) { return Bones[i].PosKeys; }
        public string RotKeys(int i) { return Bones[i].RotKeys; }
        public string ScaleKeys(int i) { return Bones[i].ScaleKeys; }
    }

    // ------------------------------------------------------------------ skeleton export
    // Writes bones exactly as 3ds Max Biped exported them for Priston Tale: a mesh object WITHOUT a
    // material (the game's builder puts material-less meshes and their animation into the .smb,
    // and ignores helpers), with keys in ASE form: position relative to the parent, rotation as a
    // turn from the previous key (axis + angle, first key absolute), scale.
    public class RigWriter
    {
        StringBuilder sb = new StringBuilder();
        List<string> keys = new List<string>();
        double[] last;                                   // previous key's rotation rows (orthonormal)
        StringBuilder pos, rot, scl;
        bool hasScale;
        static readonly System.Globalization.CultureInfo CI = System.Globalization.CultureInfo.InvariantCulture;

        static string F4(double v) { string s = v.ToString("F4", CI); return s == "-0.0000" ? "0.0000" : s; }
        static string F6(double v) { string s = v.ToString("F6", CI); return s == "-0.000000" ? "0.000000" : s; }
        static string F9(double v) { string s = v.ToString("F9", CI); return s == "-0.000000000" ? "0.000000000" : s; }
        static string F(double v)
        {
            string s = v.ToString("F8", CI).TrimEnd('0');
            int dot = s.IndexOf('.');
            if (s.EndsWith(".")) s += "0000";
            else if (s.Length - dot < 5) s += new string('0', 5 - (s.Length - dot));
            return s == "-0.0000" ? "0.0000" : s;
        }
        static string Q(string s) { return "\"" + (s ?? "").Replace("\"", "'") + "\""; }

        public void BeginTrack(bool scale)
        {
            last = new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1 };
            pos = new StringBuilder(); rot = new StringBuilder(); scl = new StringBuilder();
            hasScale = scale;
        }

        // one key: local (parent-relative) transform as 3ds Max rows r0..r3
        public void Key(int tick, double a0, double a1, double a2, double b0, double b1, double b2,
                        double c0, double c1, double c2, double t0, double t1, double t2)
        {
            double[] r = { a0, a1, a2, b0, b1, b2, c0, c1, c2 };
            double[] sc = new double[3];
            // mirrored (a prop with a negative scale): negative scale, the rotation rows turned back
            double det = a0 * (b1 * c2 - b2 * c1) - a1 * (b0 * c2 - b2 * c0) + a2 * (b0 * c1 - b1 * c0);
            for (int i = 0; i < 3; i++)
            {
                sc[i] = Math.Sqrt(r[i * 3] * r[i * 3] + r[i * 3 + 1] * r[i * 3 + 1] + r[i * 3 + 2] * r[i * 3 + 2]);
                if (det < 0) sc[i] = -sc[i];
                if (Math.Abs(sc[i]) > 1e-12) for (int j = 0; j < 3; j++) r[i * 3 + j] /= sc[i];
            }
            pos.Append("\t\t\t*CONTROL_POS_SAMPLE ").Append(tick.ToString(CI)).Append('\t').Append(F6(t0)).Append('\t')
               .Append(F6(t1)).Append('\t').Append(F6(t2)).Append("\r\n");
            if (hasScale)
                scl.Append("\t\t\t*CONTROL_SCALE_SAMPLE ").Append(tick.ToString(CI)).Append('\t').Append(F6(sc[0])).Append('\t')
                   .Append(F6(sc[1])).Append('\t').Append(F6(sc[2])).Append("\t0.0000\t0.0000\t0.0000\t0.0000\r\n");
            // the game composes rows_i = rows_(i-1) * M  =>  M = rows_(i-1)^T * rows_i  (a standard rotation matrix)
            double[] M = new double[9];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    M[i * 3 + j] = last[i] * r[j] + last[3 + i] * r[3 + j] + last[6 + i] * r[6 + j];
            double x, y, z, w;
            QuatFromMatrix(M, out x, out y, out z, out w);
            if (w < 0) { x = -x; y = -y; z = -z; w = -w; }            // shortest way round
            double s = Math.Sqrt(x * x + y * y + z * z);
            double ax = 0, ay = 0, az = 0, ang = 0;
            if (s > 1e-12) { ax = x / s; ay = y / s; az = z / s; ang = 2.0 * Math.Atan2(s, w); }
            rot.Append("\t\t\t*CONTROL_ROT_SAMPLE ").Append(tick.ToString(CI)).Append('\t').Append(F9(ax)).Append('\t')
               .Append(F9(ay)).Append('\t').Append(F9(az)).Append('\t').Append(F9(ang)).Append("\r\n");
            last = r;
        }

        static void QuatFromMatrix(double[] m, out double x, out double y, out double z, out double w)
        {
            double tr = m[0] + m[4] + m[8], s;
            if (tr > 0) { s = Math.Sqrt(tr + 1.0) * 2; x = (m[7] - m[5]) / s; y = (m[2] - m[6]) / s; z = (m[3] - m[1]) / s; w = 0.25 * s; }
            else if (m[0] > m[4] && m[0] > m[8]) { s = Math.Sqrt(1.0 + m[0] - m[4] - m[8]) * 2; x = 0.25 * s; y = (m[1] + m[3]) / s; z = (m[2] + m[6]) / s; w = (m[7] - m[5]) / s; }
            else if (m[4] > m[8]) { s = Math.Sqrt(1.0 + m[4] - m[0] - m[8]) * 2; x = (m[1] + m[3]) / s; y = 0.25 * s; z = (m[5] + m[7]) / s; w = (m[2] - m[6]) / s; }
            else { s = Math.Sqrt(1.0 + m[8] - m[0] - m[4]) * 2; x = (m[2] + m[6]) / s; y = (m[5] + m[7]) / s; z = 0.25 * s; w = (m[3] - m[1]) / s; }
            double n = Math.Sqrt(x * x + y * y + z * z + w * w);
            x /= n; y /= n; z /= n; w /= n;
        }

        // A bone object: rest rows ("r00 r01 ... r32", 12 numbers), optional animation from BeginTrack/Key
        public string Bone(string name, string parent, string rows, bool withTrack)
        {
            string[] p = rows.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            double[] r = new double[12];
            for (int i = 0; i < 12 && i < p.Length; i++) r[i] = U.D(p[i]);
            StringBuilder o = new StringBuilder();
            o.Append("*GEOMOBJECT {\r\n\t*NODE_NAME ").Append(Q(name)).Append("\r\n");
            if (!string.IsNullOrEmpty(parent)) o.Append("\t*NODE_PARENT ").Append(Q(parent)).Append("\r\n");
            o.Append("\t*NODE_TM {\r\n\t\t*NODE_NAME ").Append(Q(name)).Append("\r\n");
            o.Append("\t\t*INHERIT_POS 0 0 0\r\n\t\t*INHERIT_ROT 0 0 0\r\n\t\t*INHERIT_SCL 0 0 0\r\n");
            for (int k = 0; k < 3; k++)
                o.Append("\t\t*TM_ROW").Append(k).Append(' ').Append(F4(r[k * 3])).Append('\t').Append(F4(r[k * 3 + 1])).Append('\t').Append(F4(r[k * 3 + 2])).Append("\r\n");
            string t = F(r[9]) + "\t" + F(r[10]) + "\t" + F(r[11]);
            o.Append("\t\t*TM_ROW3 ").Append(t).Append("\r\n\t\t*TM_POS ").Append(t).Append("\r\n");
            // TM_ROTAXIS / TM_ROTANGLE / TM_SCALE exactly as the converter (and 3ds Max) write them
            double[] sc = new double[3];
            double[] M = new double[9];
            for (int i = 0; i < 3; i++)
            {
                sc[i] = Math.Sqrt(r[i * 3] * r[i * 3] + r[i * 3 + 1] * r[i * 3 + 1] + r[i * 3 + 2] * r[i * 3 + 2]);
                if (sc[i] == 0) sc[i] = 1.0;
            }
            for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) M[i * 3 + j] = r[j * 3 + i] / sc[j];
            double qx, qy, qz, qw, s2, tr = M[0] + M[4] + M[8];
            if (tr > 0) { s2 = Math.Sqrt(tr + 1.0) * 2; qw = 0.25 * s2; qx = (M[5] - M[7]) / s2; qy = (M[6] - M[2]) / s2; qz = (M[1] - M[3]) / s2; }
            else if (M[0] > M[4] && M[0] > M[8]) { s2 = Math.Sqrt(1.0 + M[0] - M[4] - M[8]) * 2; qw = (M[5] - M[7]) / s2; qx = 0.25 * s2; qy = (M[3] + M[1]) / s2; qz = (M[6] + M[2]) / s2; }
            else if (M[4] > M[8]) { s2 = Math.Sqrt(1.0 + M[4] - M[0] - M[8]) * 2; qw = (M[6] - M[2]) / s2; qx = (M[3] + M[1]) / s2; qy = 0.25 * s2; qz = (M[7] + M[5]) / s2; }
            else { s2 = Math.Sqrt(1.0 + M[8] - M[0] - M[4]) * 2; qw = (M[1] - M[3]) / s2; qx = (M[6] + M[2]) / s2; qy = (M[7] + M[5]) / s2; qz = 0.25 * s2; }
            qw = Math.Max(-1.0, Math.Min(1.0, qw));
            double sn = Math.Sqrt(Math.Max(0.0, 1.0 - qw * qw));
            double[] axis = sn < 1e-7 ? new double[] { 0, 0, 0 } : new[] { qx / sn, qy / sn, qz / sn };
            double angle = sn < 1e-7 ? 0.0 : 2.0 * Math.Acos(qw);
            o.Append("\t\t*TM_ROTAXIS ").Append(F4(axis[0])).Append('\t').Append(F4(axis[1])).Append('\t').Append(F4(axis[2])).Append("\r\n");
            o.Append("\t\t*TM_ROTANGLE ").Append(F4(angle)).Append("\r\n");
            o.Append("\t\t*TM_SCALE ").Append(F4(sc[0])).Append('\t').Append(F4(sc[1])).Append('\t').Append(F4(sc[2])).Append("\r\n");
            o.Append("\t\t*TM_SCALEAXIS 0.0000\t0.0000\t0.0000\r\n\t\t*TM_SCALEAXISANG 0.0000\r\n\t}\r\n");
            double cx = r[9], cy = r[10], cz = r[11], rr = 0.5;
            double[][] v = { new[] { cx, cy, cz + rr }, new[] { cx, cy - rr, cz }, new[] { cx + rr, cy, cz },
                             new[] { cx, cy + rr, cz }, new[] { cx - rr, cy, cz }, new[] { cx, cy, cz - rr } };
            int[][] f = { new[] { 0, 1, 2 }, new[] { 0, 2, 3 }, new[] { 0, 3, 4 }, new[] { 0, 4, 1 },
                          new[] { 5, 4, 3 }, new[] { 5, 3, 2 }, new[] { 5, 2, 1 }, new[] { 5, 1, 4 } };
            o.Append("\t*MESH {\r\n\t\t*TIMEVALUE 0\r\n\t\t*MESH_NUMVERTEX 6\r\n\t\t*MESH_NUMFACES 8\r\n\t\t*MESH_VERTEX_LIST {\r\n");
            for (int i = 0; i < 6; i++)
                o.Append("\t\t\t*MESH_VERTEX ").Append(i.ToString(CI).PadLeft(5)).Append('\t').Append(F4(v[i][0])).Append('\t')
                 .Append(F4(v[i][1])).Append('\t').Append(F4(v[i][2])).Append("\r\n");
            o.Append("\t\t}\r\n\t\t*MESH_FACE_LIST {\r\n");
            for (int i = 0; i < 8; i++)
                o.Append("\t\t\t*MESH_FACE ").Append(i.ToString(CI).PadLeft(5)).Append(":    A: ").Append(f[i][0].ToString(CI).PadLeft(5))
                 .Append(" B: ").Append(f[i][1].ToString(CI).PadLeft(5)).Append(" C: ").Append(f[i][2].ToString(CI).PadLeft(5))
                 .Append(" AB:    1 BC:    1 CA:    1\t *MESH_SMOOTHING 1 \t*MESH_MTLID 0\r\n");
            o.Append("\t\t}\r\n\t\t*MESH_NUMTVERTEX 0\r\n\t}\r\n\t*PROP_MOTIONBLUR 0\r\n\t*PROP_CASTSHADOW 1\r\n\t*PROP_RECVSHADOW 1\r\n");
            if (withTrack) o.Append(Track(name));
            o.Append("\t*WIREFRAME_COLOR 0.6510\t0.7922\t0.9412\r\n}\r\n");
            pos = null;
            return o.ToString();
        }

        // The *TM_ANIMATION block of the keys given since BeginTrack ("" = none)
        public string Track(string name)
        {
            if (pos == null || pos.Length == 0) return "";
            StringBuilder o = new StringBuilder();
            o.Append("\t*TM_ANIMATION {\r\n\t\t*NODE_NAME ").Append(Q(name)).Append("\r\n");
            o.Append("\t\t*CONTROL_POS_TRACK {\r\n").Append(pos).Append("\t\t}\r\n");
            o.Append("\t\t*CONTROL_ROT_TRACK {\r\n").Append(rot).Append("\t\t}\r\n");
            if (hasScale) o.Append("\t\t*CONTROL_SCALE_TRACK {\r\n").Append(scl).Append("\t\t}\r\n");
            o.Append("\t}\r\n");
            pos = null;
            return o.ToString();
        }

        // *PHYSIQUE block: one bone name per vertex ("" = none), joined with '|'
        public string Physique(string names)
        {
            string[] n = names.Split('|');
            int count = 0;
            foreach (string s in n) if (s.Length > 0) count++;
            StringBuilder o = new StringBuilder("\t*PHYSIQUE {\r\n\t\t*PHYSIQUE_NUMVERTEXASSIGNMENT\t");
            o.Append(count.ToString(CI)).Append("\r\n");
            for (int i = 0; i < n.Length; i++)
                if (n[i].Length > 0)
                    o.Append("\t\t*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE ").Append(i.ToString(CI)).Append('\t').Append(Q(n[i])).Append("\r\n");
            o.Append("\t}\r\n");
            return o.ToString();
        }
    }

    // Textures the importer decoded into %TEMP%\pt_texture_cache as <hash>_<name>: the exporter
    // writes (and copies) the game's own file instead of the temporary copy.
    public class TexInfo
    {
        public string Original(string path)
        {
            if (string.IsNullOrEmpty(path)) return "";
            try
            {
                string dir = Path.GetDirectoryName(path) ?? "", nm = Path.GetFileName(path);
                if (!dir.EndsWith("pt_texture_cache", StringComparison.OrdinalIgnoreCase) || nm.Length < 10 || nm[8] != '_') return path;
                string src = path + ".src";
                if (File.Exists(src))
                {
                    string o = File.ReadAllText(src).Trim();
                    if (o.Length > 0) return o;
                }
                return nm.Substring(9);
            }
            catch (Exception) { return path; }
        }
    }

    public class GeomData
    {
        public string Name = "", Parent = "", Kind = "geom";
        public string Transform = "(matrix3 1)";
        public string Verts = "#()", Faces = "#()", MatIds = "#()", Smooth = "#()";
        public int NumVerts, NumFaces;
        public int[] Channels = new int[0];       // channel numbers present (0 = vertex colour)
        public string[] ChanVerts = new string[0];
        public string[] ChanFaces = new string[0];
        public int MaterialRef = -1;
        public int[] UsedMtlIds = new int[0];
        internal List<int> FaceMtl = new List<int>();     // MESH_MTLID per face, as written
        public bool AllCollision;
        // skinned mesh: 1-based bone index per vertex (0 = no bone), as a MAXScript array literal
        public string Phys = "";
        // a prop's own animation (windmills, doors): linear keys relative to the parent object
        public string PosKeys = "#()", RotKeys = "#()", ScaleKeys = "#()";
        public int KeyCount;
        public double LastTick;
        public string RestRows = "";              // its NODE_TM exactly as written (12 numbers), for the exporter
        public bool PhysEmpty;                    // a *PHYSIQUE without assignments (the exporter keeps it)
        // light
        public string LightColor = "(color 255 255 255)";
        public double LightRange = 200;
    }

    public class Scene
    {
        public string FileName = "";
        public List<MatDef> Materials = new List<MatDef>();
        public List<GeomData> Objects = new List<GeomData>();
        public int LastFrame = 100;

        public Scene() { }
        // set by the importer before LoadFile: false = T-pose; optional *_motions.ase to animate with
        bool animate = true; string animationFile = "";
        public bool Animate { get { return animate; } set { animate = value; } }
        public string AnimationFile { get { return animationFile; } set { animationFile = value ?? ""; } }
        public void LoadFile(string path)
        {
            Scene t = Load(path, Animate, AnimationFile);
            FileName = t.FileName; Materials = t.Materials; Objects = t.Objects; LastFrame = t.LastFrame; Rig = t.Rig;
            packed = t.packed;
        }
        public string ChannelList(int obj)
        {
            StringBuilder sb = new StringBuilder("#(");
            int[] c = Objects[obj].Channels;
            for (int i = 0; i < c.Length; i++) { if (i > 0) sb.Append(','); sb.Append(c[i]); }
            return sb.Append(')').ToString();
        }
        // MAXScript's execute() overflows its stack on huge array literals, so big
        // literals are handed over in chunks: n = Split(lit, size); GetChunk(0..n-1)
        List<string> chunks = new List<string>();
        public int Split(string lit, int size)
        {
            chunks.Clear();
            if (lit.Length < 2 || !lit.StartsWith("#(")) { chunks.Add(lit); return 1; }
            StringBuilder cur = new StringBuilder("#(");
            int depth = 0, count = 0;
            for (int i = 2; i < lit.Length - 1; i++)
            {
                char ch = lit[i];
                if (ch == '[' || ch == '(') depth++;
                else if (ch == ']' || ch == ')') depth--;
                if (ch == ',' && depth == 0)
                {
                    count++;
                    if (count >= size) { cur.Append(')'); chunks.Add(cur.ToString()); cur = new StringBuilder("#("); count = 0; continue; }
                }
                cur.Append(ch);
            }
            cur.Append(')');
            chunks.Add(cur.ToString());
            return chunks.Count;
        }
        public string GetChunk(int i) { return chunks[i]; }
        public string ChanVerts(int obj, int k) { return Objects[obj].ChanVerts[k]; }
        public string ChanFaces(int obj, int k) { return Objects[obj].ChanFaces[k]; }
        public int ObjectCount { get { return Objects.Count; } }
        public GeomData GetObject(int i) { return Objects[i]; }
        public int MaterialCount { get { return Materials.Count; } }
        public string Missing = "";
        public Rig Rig;                                   // characters / monsters, else null
        public bool HasRig { get { return Rig != null && Rig.Bones.Count > 0; } }

        public static Scene Load(string path, bool animate = true, string animationFile = "")
        {
            Scene sc = new Scene();
            sc.FileName = path;
            Node root = Parser.Parse(path);
            Node scene = root.Find("*SCENE");
            if (scene != null) sc.LastFrame = U.I(scene.Val("*SCENE_LASTFRAME", "100"));
            Node ml = root.Find("*MATERIAL_LIST");
            if (ml != null) foreach (Node m in ml.FindAll("*MATERIAL")) sc.Materials.Add(new MatDef(m));
            List<Node> geoms = new List<Node>();
            Collect(root, geoms);
            HashSet<string> boneNames = new HashSet<string>();
            bool isChar = Rig.IsCharacter(root);
            if (isChar)
            {
                sc.Rig = new Rig(root, path, animate, animationFile);
                foreach (Rig.Bone b in sc.Rig.Bones) boneNames.Add(b.Name);
            }
            // objects with their own animation (map props: windmills, doors; rigid parts of a
            // character riding on a bone: Deius' Circle001): those objects and their parents (bones
            // aside) keep their exact NODE_TM pivot (the keys turn about it)
            Dictionary<string, double[]> rawTm = new Dictionary<string, double[]>();
            HashSet<string> rawNames = new HashSet<string>();
            Dictionary<string, string> parentOf = new Dictionary<string, string>();
            foreach (Node g in geoms)
            {
                string nm = U.Unq(g.Val("*NODE_NAME", ""));
                if (parentOf.ContainsKey(nm)) continue;
                parentOf[nm] = U.Unq(g.Val("*NODE_PARENT", ""));
                rawTm[nm] = Tm(g);
            }
            foreach (Node g in geoms)
            {
                if (g.Find("*TM_ANIMATION") == null || Rig.PhysMap(g).Count > 0) continue;
                string nm = U.Unq(g.Val("*NODE_NAME", ""));
                while (nm.Length > 0 && !rawNames.Contains(nm) && !boneNames.Contains(nm) && parentOf.ContainsKey(nm))
                {
                    rawNames.Add(nm);
                    nm = parentOf[nm];
                }
            }
            foreach (Node g in geoms)
            {
                string nm = U.Unq(g.Val("*NODE_NAME", ""));
                if (boneNames.Contains(nm)) continue;     // bones become helpers
                bool raw = rawNames.Contains(nm) && Rig.Usable(Tm(g));
                GeomData d = g.Key == "*GEOMOBJECT" ? BuildGeom(g, sc, raw) : BuildLight(g);
                if (d == null) continue;
                // skinned: at least one vertex on a bone (an empty *PHYSIQUE is a rigid part)
                if (sc.Rig != null && g.Find("*PHYSIQUE") != null)
                {
                    if (Rig.PhysMap(g).Count > 0) d.Phys = sc.Rig.PhysiqueLiteral(g, d.NumVerts);
                    else d.PhysEmpty = true;
                }
                Node anim = g.Find("*TM_ANIMATION");
                if (raw && anim != null && d.Kind == "geom")
                {
                    // keys relative to the parent: a bone (its bind pose as written) or an object
                    double[] p = sc.Rig != null ? sc.Rig.RawOf(d.Parent) : null;
                    if (p == null && !(rawTm.TryGetValue(d.Parent, out p) && rawNames.Contains(d.Parent))) p = null;
                    double[] rest = p != null && Rig.Usable(p) ? Rig.Mul43(Tm(g), Inverse(p)) : Tm(g);
                    Rig.Track t = Rig.ReadTrack(anim, Rig.EngineStatic(g, rest, d.Parent.Length > 0), true);
                    d.PosKeys = t.Pos; d.RotKeys = t.Rot; d.ScaleKeys = t.Scale; d.KeyCount = t.Count; d.LastTick = t.LastTick;
                    StringBuilder rr = new StringBuilder();
                    foreach (double v in Tm(g)) { if (rr.Length > 0) rr.Append(' '); rr.Append(v.ToString("R", U.CI)); }
                    d.RestRows = rr.ToString();
                    if (t.LastTick / 160.0 > sc.LastFrame) sc.LastFrame = (int)Math.Ceiling(t.LastTick / 160.0);
                }
                sc.Objects.Add(d);
            }
            sc.PackMaterialIds();
            return sc;
        }

        // A 3ds Max Multi/Sub material holds at most 1000 sub-materials.  When the faces use higher
        // ids (lost.ASE has a 3467-slot material), the ids in use are packed together; the
        // exporter then writes the packed material, which the game draws the same.
        const int MaxSubs = 1000;
        Dictionary<int, List<int>> packed = new Dictionary<int, List<int>>();   // matRef -> original id per packed id
        void PackMaterialIds()
        {
            Dictionary<int, SortedDictionary<int, bool>> used = new Dictionary<int, SortedDictionary<int, bool>>();
            foreach (GeomData o in Objects)
                if (o.Kind == "geom" && o.MaterialRef >= 0)
                {
                    if (!used.ContainsKey(o.MaterialRef)) used[o.MaterialRef] = new SortedDictionary<int, bool>();
                    foreach (int i in o.UsedMtlIds) used[o.MaterialRef][i] = true;
                }
            foreach (KeyValuePair<int, SortedDictionary<int, bool>> kv in used)
            {
                List<int> ids = new List<int>(kv.Value.Keys);
                if (ids.Count == 0 || ids[ids.Count - 1] < MaxSubs || ids.Count > MaxSubs) continue;
                packed[kv.Key] = ids;
                Dictionary<int, int> to = new Dictionary<int, int>();
                for (int k = 0; k < ids.Count; k++) to[ids[k]] = k;
                foreach (GeomData o in Objects)
                {
                    if (o.Kind != "geom" || o.MaterialRef != kv.Key) continue;
                    StringBuilder sm = new StringBuilder("#(");
                    for (int f = 0; f < o.FaceMtl.Count; f++) { if (f > 0) sm.Append(','); sm.Append(to[o.FaceMtl[f]] + 1); }
                    o.MatIds = sm.Append(')').ToString();
                    for (int k = 0; k < o.UsedMtlIds.Length; k++) o.UsedMtlIds[k] = to[o.UsedMtlIds[k]];
                }
            }
        }

        static void Collect(Node n, List<Node> outl)
        {
            if (n.Kids == null) return;
            foreach (Node k in n.Kids)
            {
                if (k.Key == "*GEOMOBJECT" || k.Key == "*LIGHTOBJECT") outl.Add(k);
                else if (k.Key == "*GROUP") Collect(k, outl);
            }
        }

        static double[] Tm(Node g)
        {
            Node tm = g.Find("*NODE_TM");
            double[] m = new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
            if (tm == null) return m;
            double[] r0 = U.Ds(tm.Val("*TM_ROW0", "1 0 0"), 3), r1 = U.Ds(tm.Val("*TM_ROW1", "0 1 0"), 3);
            double[] r2 = U.Ds(tm.Val("*TM_ROW2", "0 0 1"), 3), r3 = U.Ds(tm.Val("*TM_ROW3", "0 0 0"), 3);
            return new double[] { r0[0], r0[1], r0[2], r1[0], r1[1], r1[2], r2[0], r2[1], r2[2], r3[0], r3[1], r3[2] };
        }

        // A pivot a node can hold exactly. A flat or broken NODE_TM (some converted monsters
        // carried one) becomes an identity pivot; a skewed one (rows not at right angles, e.g. the
        // inverse of an 8.8 fixed-point matrix) gets square axes of the same lengths. The vertices
        // are world space, so they are simply made local to the pivot used here.
        static double[] Plain(double[] m)
        {
            double[] t = new double[] { m[9], m[10], m[11] };
            for (int k = 0; k < 3; k++) if (double.IsNaN(t[k]) || double.IsInfinity(t[k])) t = new double[] { 0, 0, 0 };
            double[] ident = new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, t[0], t[1], t[2] };
            for (int k = 0; k < 9; k++) if (double.IsNaN(m[k]) || double.IsInfinity(m[k])) return ident;
            double det = m[0] * (m[4] * m[8] - m[5] * m[7]) - m[1] * (m[3] * m[8] - m[5] * m[6]) + m[2] * (m[3] * m[7] - m[4] * m[6]);
            if (Math.Abs(det) < 1e-9) return ident;
            double[] ln = new double[3];
            double[][] u = new double[3][];
            for (int r = 0; r < 3; r++)
            {
                ln[r] = Math.Sqrt(m[r * 3] * m[r * 3] + m[r * 3 + 1] * m[r * 3 + 1] + m[r * 3 + 2] * m[r * 3 + 2]);
                u[r] = new double[] { m[r * 3] / ln[r], m[r * 3 + 1] / ln[r], m[r * 3 + 2] / ln[r] };
            }
            double d01 = Dot3(u[0], u[1]), d02 = Dot3(u[0], u[2]), d12 = Dot3(u[1], u[2]);
            // (any skew, even the 4th-decimal kind: a node holds it only approximately - a scaled plane
            // of a 2012 map was 0.026 off - while the vertices take it exactly)
            if (Math.Max(Math.Abs(d01), Math.Max(Math.Abs(d02), Math.Abs(d12))) < 1e-12) return m;
            double[] v1 = new double[] { u[1][0] - d01 * u[0][0], u[1][1] - d01 * u[0][1], u[1][2] - d01 * u[0][2] };
            double n1 = Math.Sqrt(Dot3(v1, v1));
            for (int k = 0; k < 3; k++) v1[k] /= n1;
            double[] v2 = new double[] { u[0][1] * v1[2] - u[0][2] * v1[1], u[0][2] * v1[0] - u[0][0] * v1[2], u[0][0] * v1[1] - u[0][1] * v1[0] };
            if (Dot3(v2, u[2]) < 0) for (int k = 0; k < 3; k++) v2[k] = -v2[k];
            return new double[] { u[0][0] * ln[0], u[0][1] * ln[0], u[0][2] * ln[0],
                                  v1[0] * ln[1], v1[1] * ln[1], v1[2] * ln[1],
                                  v2[0] * ln[2], v2[1] * ln[2], v2[2] * ln[2], t[0], t[1], t[2] };
        }

        static double Dot3(double[] a, double[] b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

        static string TmLiteral(double[] m)
        {
            return string.Format("(matrix3 [{0},{1},{2}] [{3},{4},{5}] [{6},{7},{8}] [{9},{10},{11}])",
                U.F(m[0]), U.F(m[1]), U.F(m[2]), U.F(m[3]), U.F(m[4]), U.F(m[5]),
                U.F(m[6]), U.F(m[7]), U.F(m[8]), U.F(m[9]), U.F(m[10]), U.F(m[11]));
        }

        internal static double[] Inverse(double[] m)
        {
            double a = m[0], b = m[1], c = m[2], d = m[3], e = m[4], f = m[5], g = m[6], h = m[7], i = m[8];
            double A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
            double det = a * A + b * B + c * C;
            if (Math.Abs(det) < 1e-12) return new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, -m[9], -m[10], -m[11] };
            double[] r = new double[] {
                A / det, -(b * i - c * h) / det, (b * f - c * e) / det,
                B / det, (a * i - c * g) / det, -(a * f - c * d) / det,
                C / det, -(a * h - b * g) / det, (a * e - b * d) / det, 0, 0, 0 };
            // translation: -t * R^-1 (row vectors)
            double tx = m[9], ty = m[10], tz = m[11];
            r[9] = -(tx * r[0] + ty * r[3] + tz * r[6]);
            r[10] = -(tx * r[1] + ty * r[4] + tz * r[7]);
            r[11] = -(tx * r[2] + ty * r[5] + tz * r[8]);
            return r;
        }

        static bool IsIdentity(double[] m)
        {
            double[] id = { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
            for (int i = 0; i < 12; i++) if (Math.Abs(m[i] - id[i]) > 1e-7) return false;
            return true;
        }

        static void UvBlock(Node blk, int nfaces, out string verts, out string faces, bool colors)
        {
            Node tl = blk.Find(colors ? "*MESH_CVERTLIST" : "*MESH_TVERTLIST");
            Node tf = blk.Find(colors ? "*MESH_CFACELIST" : "*MESH_TFACELIST");
            StringBuilder sv = new StringBuilder("#(");
            int nv = 0;
            if (tl != null && tl.Kids != null)
                foreach (Node c in tl.Kids)
                {
                    double[] p = U.Ds(c.Args, 4);
                    if (nv > 0) sv.Append(',');
                    sv.Append('[').Append(U.F(p[1])).Append(',').Append(U.F(p[2])).Append(',').Append(U.F(colors ? p[3] : 0)).Append(']');
                    nv++;
                }
            if (nv == 0) sv.Append("[0,0,0]");
            sv.Append(')');
            StringBuilder sf = new StringBuilder("#(");
            int nf = 0;
            if (tf != null && tf.Kids != null)
                foreach (Node c in tf.Kids)
                {
                    if (nf >= nfaces) break;
                    string[] p = U.Split(c.Args);
                    int a = p.Length > 1 ? U.I(p[1]) : 0, b = p.Length > 2 ? U.I(p[2]) : 0, cc = p.Length > 3 ? U.I(p[3]) : 0;
                    if (a < 0 || a >= Math.Max(nv, 1)) a = 0;
                    if (b < 0 || b >= Math.Max(nv, 1)) b = 0;
                    if (cc < 0 || cc >= Math.Max(nv, 1)) cc = 0;
                    if (nf > 0) sf.Append(',');
                    sf.Append('[').Append(a + 1).Append(',').Append(b + 1).Append(',').Append(cc + 1).Append(']');
                    nf++;
                }
            for (; nf < nfaces; nf++) { if (nf > 0) sf.Append(','); sf.Append("[1,1,1]"); }
            sf.Append(')');
            verts = sv.ToString();
            faces = sf.ToString();
        }

        static GeomData BuildGeom(Node g, Scene sc, bool rawPivot)
        {
            Node mesh = g.Find("*MESH");
            if (mesh == null) return null;
            GeomData d = new GeomData();
            d.Name = U.Unq(g.Val("*NODE_NAME", "Object"));
            d.Parent = U.Unq(g.Val("*NODE_PARENT", ""));
            d.MaterialRef = U.I(g.Val("*MATERIAL_REF", "-1"));
            // an animated prop (or its parent) keeps its exact pivot, mirrored or not
            double[] tm = rawPivot ? Tm(g) : Plain(Tm(g));
            double det = tm[0] * (tm[4] * tm[8] - tm[5] * tm[7]) - tm[1] * (tm[3] * tm[8] - tm[5] * tm[6]) + tm[2] * (tm[3] * tm[7] - tm[4] * tm[6]);
            if (det < 0 && !rawPivot)
            {
                // Mirrored pivot: keep world-space vertices (their winding is what the
                // game draws) with an identity transform instead of a negative scale.
                tm = new double[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 };
            }
            bool ident = IsIdentity(tm);
            double[] inv = ident ? null : Inverse(tm);
            d.Transform = TmLiteral(tm);

            Node vl = mesh.Find("*MESH_VERTEX_LIST");
            Node fl = mesh.Find("*MESH_FACE_LIST");
            if (vl == null || fl == null || vl.Kids == null || fl.Kids == null) return null;
            StringBuilder sv = new StringBuilder("#(");
            foreach (Node c in vl.Kids)
            {
                double[] p = U.Ds(c.Args, 4);
                double x = p[1], y = p[2], z = p[3];
                if (!ident)
                {
                    double lx = x * inv[0] + y * inv[3] + z * inv[6] + inv[9];
                    double ly = x * inv[1] + y * inv[4] + z * inv[7] + inv[10];
                    double lz = x * inv[2] + y * inv[5] + z * inv[8] + inv[11];
                    x = lx; y = ly; z = lz;
                }
                if (d.NumVerts > 0) sv.Append(',');
                sv.Append('[').Append(U.F(x)).Append(',').Append(U.F(y)).Append(',').Append(U.F(z)).Append(']');
                d.NumVerts++;
            }
            sv.Append(')');
            d.Verts = sv.ToString();

            StringBuilder sf = new StringBuilder("#("), sm = new StringBuilder("#("), sg = new StringBuilder("#(");
            HashSet<int> used = new HashSet<int>();
            foreach (Node c in fl.Kids)
            {
                string s = c.Args;
                int a = Field(s, "A:"), b = Field(s, "B:"), cc = Field(s, "C:");
                if (a < 0 || b < 0 || cc < 0 || a >= d.NumVerts || b >= d.NumVerts || cc >= d.NumVerts) { a = b = cc = 0; }
                int mid = 0, smg = 0;
                int k = s.IndexOf("*MESH_MTLID");
                if (k >= 0) { string[] p = U.Split(s.Substring(k + 11)); if (p.Length > 0) mid = U.I(p[0]); }
                k = s.IndexOf("*MESH_SMOOTHING");
                if (k >= 0)
                {
                    string[] p = U.Split(s.Substring(k + 15));
                    if (p.Length > 0 && !p[0].StartsWith("*"))
                        foreach (string grp in p[0].Split(',')) { int gi = U.I(grp); if (gi >= 1 && gi <= 32) smg |= 1 << (gi - 1); }
                }
                used.Add(mid);
                d.FaceMtl.Add(mid);
                if (d.NumFaces > 0) { sf.Append(','); sm.Append(','); sg.Append(','); }
                sf.Append('[').Append(a + 1).Append(',').Append(b + 1).Append(',').Append(cc + 1).Append(']');
                sm.Append(mid + 1);
                sg.Append(smg);
                d.NumFaces++;
            }
            sf.Append(')'); sm.Append(')'); sg.Append(')');
            d.Faces = sf.ToString();
            d.MatIds = sm.ToString();
            d.Smooth = sg.ToString();
            d.UsedMtlIds = new List<int>(used).ToArray();
            Array.Sort(d.UsedMtlIds);

            // collision object?  (all faces use collision materials, or smd2ase naming)
            bool allColl = d.Name.EndsWith("__collision");
            if (!allColl && d.MaterialRef >= 0 && d.MaterialRef < sc.Materials.Count)
            {
                allColl = true;
                foreach (int mid in d.UsedMtlIds)
                {
                    MatDef md = sc.Materials[d.MaterialRef].Resolve(mid);
                    if (md == null || !md.Collision) { allColl = false; break; }
                }
            }
            d.AllCollision = allColl;

            // UV channels + vertex colour (channel 0)
            List<int> ch = new List<int>();
            List<string> cv = new List<string>(), cf = new List<string>();
            string v, f;
            if (mesh.Find("*MESH_TVERTLIST") != null) { UvBlock(mesh, d.NumFaces, out v, out f, false); ch.Add(1); cv.Add(v); cf.Add(f); }
            foreach (Node mc in mesh.FindAll("*MESH_MAPPINGCHANNEL"))
            {
                int n = U.I(U.Split(mc.Args + " 0")[0]);
                if (n < 2 || n > 99 || ch.Contains(n)) continue;
                UvBlock(mc, d.NumFaces, out v, out f, false);
                ch.Add(n); cv.Add(v); cf.Add(f);
            }
            if (mesh.Find("*MESH_CVERTLIST") != null)
            {
                UvBlock(mesh, d.NumFaces, out v, out f, true);
                ch.Add(0); cv.Add(v); cf.Add(f);
            }
            d.Channels = ch.ToArray();
            d.ChanVerts = cv.ToArray();
            d.ChanFaces = cf.ToArray();
            return d;
        }

        static int Field(string s, string tag)
        {
            int k = s.IndexOf(tag);
            if (k < 0) return -1;
            string[] p = U.Split(s.Substring(k + tag.Length));
            return p.Length > 0 ? U.I(p[0]) : -1;
        }

        static GeomData BuildLight(Node g)
        {
            GeomData d = new GeomData();
            d.Kind = "light";
            d.Name = U.Unq(g.Val("*NODE_NAME", "Light"));
            d.Transform = TmLiteral(Tm(g));
            Node s = g.Find("*LIGHT_SETTINGS");
            if (s != null)
            {
                double[] c = U.Ds(s.Val("*LIGHT_COLOR", "1 1 1"), 3);
                d.LightColor = string.Format(CultureInfo.InvariantCulture, "(color {0} {1} {2})",
                    (int)(c[0] * 255), (int)(c[1] * 255), (int)(c[2] * 255));
                d.LightRange = U.D(s.Val("*LIGHT_ATTNEND", "200"));
            }
            return d;
        }

        // -------------------------------------------------------------- material script
        // Returns a MAXScript expression creating the Multi/Sub material used by object d.
        // mode: 0 = game look (self-illuminated), 1 = lit
        // Multi/Sub material for MATERIAL_REF matRef, holding every sub id used by
        // any object referencing it (shared by all those objects).
        public string MaterialScript(int matRef, int mode, bool vcol, bool layers, string searchDir)
        {
            bool hasVC = false;
            SortedDictionary<int, bool> idset = new SortedDictionary<int, bool>();
            foreach (GeomData o in Objects)
                if (o.Kind == "geom" && o.MaterialRef == matRef)
                {
                    foreach (int i in o.UsedMtlIds) idset[i] = true;
                    if (Array.IndexOf(o.Channels, 0) >= 0) hasVC = true;
                }
            hasVC = hasVC && vcol;
            List<int> ids = new List<int>(idset.Keys);
            StringBuilder sb = new StringBuilder();
            MatDef top0 = (matRef >= 0 && matRef < Materials.Count) ? Materials[matRef] : null;
            string baseName = Path.GetFileNameWithoutExtension(FileName) + "_" + (top0 != null ? top0.Name : "mat");
            int maxId = ids.Count > 0 ? ids[ids.Count - 1] + 1 : 1;
            sb.Append("(\nlocal mm = multimaterial numsubs:").Append(maxId).Append(" name:").Append(U.MS(baseName)).Append("\n");
            sb.Append("local s, b, c, lb, ob, vc, vp, si\n");
            MatDef top = top0;
            List<int> orig;
            packed.TryGetValue(matRef, out orig);
            foreach (int mid in ids)
            {
                MatDef md = top == null ? null : top.Resolve(orig != null ? orig[mid] : mid);
                sb.Append(StdScript(md, mode, hasVC, layers, searchDir));
                sb.Append("mm.materialList[").Append(mid + 1).Append("] = s\n");
            }
            sb.Append("mm\n)");
            return sb.ToString();
        }

        string Resolve(string path, string searchDir)
        {
            if (string.IsNullOrEmpty(path)) return "";
            if (File.Exists(path)) return Readable(path);
            string fn = Path.GetFileName(path.Replace('/', '\\'));
            List<string> dirs = new List<string>();
            dirs.Add(Path.GetDirectoryName(FileName));
            if (!string.IsNullOrEmpty(searchDir)) dirs.Add(searchDir);
            foreach (string dir in dirs)
            {
                string p = Path.Combine(dir, fn);
                if (File.Exists(p)) return Readable(p);
                foreach (string ext in new string[] { ".bmp", ".tga", ".png", ".dds" })
                {
                    string q = Path.Combine(dir, Path.GetFileNameWithoutExtension(fn) + ext);
                    if (File.Exists(q)) return Readable(q);
                }
            }
            // a converter output folder that was moved or shared keeps its layout, but the .ase still
            // names the old place: the end of the old path below one of the .ase's folders
            string[] parts = path.Replace('/', '\\').Split(new char[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);
            string up = Path.GetDirectoryName(FileName);
            for (int lvl = 0; lvl < 8 && !string.IsNullOrEmpty(up); lvl++)
            {
                for (int k = Math.Min(parts.Length - 1, 8); k >= 2; k--)          // (parts[0]: the old drive)
                {
                    string c = Path.Combine(up, string.Join("\\", parts, parts.Length - k, k));
                    if (File.Exists(c)) return Readable(c);
                }
                up = Path.GetDirectoryName(up);
            }
            // the converter's "textures" folder next to the .ase (any depth), by file name
            if (texIndex == null)
            {
                texIndex = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                string tex = Path.Combine(Path.GetDirectoryName(FileName), "textures");
                if (Directory.Exists(tex))
                    foreach (string f in Directory.GetFiles(tex, "*", SearchOption.AllDirectories))
                    {
                        if (!texIndex.ContainsKey(Path.GetFileName(f))) texIndex[Path.GetFileName(f)] = f;
                        if (!texIndex.ContainsKey(Path.GetFileNameWithoutExtension(f))) texIndex[Path.GetFileNameWithoutExtension(f)] = f;
                    }
            }
            string hit;
            if (texIndex.TryGetValue(fn, out hit) || texIndex.TryGetValue(Path.GetFileNameWithoutExtension(fn), out hit))
                return Readable(hit);
            if (!Missing.Contains(path + "\n")) Missing += path + "\n";
            return path;
        }
        Dictionary<string, string> texIndex;

        // A TGA header a reader can use (as PTSmd.Textures.TgaHeaderOk).
        static bool TgaHeaderOk(byte[] h, int off, long fileLen)
        {
            int idLen = h[off], cmap = h[off + 1], type = h[off + 2];
            int w = h[off + 12] | h[off + 13] << 8, ht = h[off + 14] | h[off + 15] << 8, bpp = h[off + 16];
            if (cmap > 1 || !(type == 1 || type == 2 || type == 3 || type == 9 || type == 10 || type == 11)) return false;
            if (w == 0 || ht == 0 || !(bpp == 8 || bpp == 15 || bpp == 16 || bpp == 24 || bpp == 32)) return false;
            if ((type == 2 || type == 3) && 18L + idLen + (long)w * ht * ((bpp + 7) / 8) > fileLen) return false;
            return true;
        }

        // Game client textures are scrambled ('A8' BMP / 'G8' TGA header); 3ds Max can't read
        // them, so a decoded copy goes to %TEMP%\pt_texture_cache.
        static string Readable(string path)
        {
            try
            {
                byte[] head = new byte[2];
                using (FileStream f = File.OpenRead(path)) f.Read(head, 0, 2);
                bool bmp = head[0] == 'A' && head[1] == '8', tga = head[0] == 'G' && head[1] == '8';
                if (!bmp && !tga) return path;
                string dir = Path.Combine(Path.GetTempPath(), "pt_texture_cache");
                Directory.CreateDirectory(dir);
                // named after the file's path, size and date: an edited texture gets a fresh copy
                FileInfo fi = new FileInfo(path);
                string key = Path.GetFullPath(path).ToLowerInvariant() + "|" + fi.Length + "|" + fi.LastWriteTimeUtc.Ticks;
                string outp = Path.Combine(dir, ((uint)key.GetHashCode()).ToString("x8") + "_" + Path.GetFileName(path));
                // the game's own file, for the exporter (TexInfo.Original)
                if (!File.Exists(outp + ".src")) File.WriteAllText(outp + ".src", Path.GetFullPath(path));
                if (File.Exists(outp)) return outp;
                byte[] d = File.ReadAllBytes(path);
                if (bmp && d.Length >= 14)
                {
                    d[0] = (byte)'B'; d[1] = (byte)'M';
                    for (int i = 2; i < 14; i++) d[i] = (byte)(d[i] - i * i);
                    // scrambled twice (StartImage\...\Mokoba.BMP): undo once more when the pixel offset is past the end
                    uint pix = BitConverter.ToUInt32(d, 10);
                    if (pix < 26 || pix >= d.Length)
                    {
                        byte[] twice = new byte[14];
                        for (int i = 2; i < 14; i++) twice[i] = (byte)(d[i] - i * i);
                        uint pix2 = BitConverter.ToUInt32(twice, 10);
                        if (pix2 >= 26 && pix2 < d.Length && BitConverter.ToUInt32(twice, 2) == d.Length) Buffer.BlockCopy(twice, 2, d, 2, 12);
                    }
                }
                else if (d.Length >= 18)
                {
                    d[0] = 0; d[1] = 0;
                    for (int i = 2; i < 18; i++) d[i] = (byte)(d[i] - i * i);
                    // some client TGAs were scrambled twice (Field\castle, Fall_Game, Iron)
                    if (!TgaHeaderOk(d, 0, d.Length))
                    {
                        byte[] twice = new byte[18];
                        for (int i = 2; i < 18; i++) twice[i] = (byte)(d[i] - i * i);
                        if (TgaHeaderOk(twice, 0, d.Length)) Buffer.BlockCopy(twice, 2, d, 2, 16);
                    }
                }
                File.WriteAllBytes(outp, d);
                return outp;
            }
            catch (Exception) { return path; }
        }

        Dictionary<string, bool> alphaCache = new Dictionary<string, bool>();
        bool HasAlpha(string path)
        {
            bool r;
            if (alphaCache.TryGetValue(path, out r)) return r;
            r = false;
            try
            {
                if (File.Exists(path))
                    using (FileStream f = File.OpenRead(path))
                    {
                        byte[] h = new byte[30];
                        int n = f.Read(h, 0, 30);
                        if (n >= 18 && path.EndsWith(".tga", StringComparison.OrdinalIgnoreCase))
                            r = h[16] == 32 || (h[17] & 0x0F) > 0;
                        else if (n >= 30 && h[0] == 'B' && h[1] == 'M')
                            r = BitConverter.ToUInt16(h, 28) == 32;
                    }
            }
            catch (Exception) { }
            alphaCache[path] = r;
            return r;
        }

        string Bmp(string var, MapDef m, string searchDir)
        {
            StringBuilder sb = new StringBuilder();
            sb.Append(var).Append(" = bitmaptexture filename:").Append(U.MS(Resolve(m.Bitmap, searchDir)))
              .Append(" name:").Append(U.MS(m.Name)).Append("\n");
            sb.Append(var).Append(".coords.mapChannel = ").Append(m.Channel).Append("\n");
            if (Math.Abs(m.UOff) > 1e-6) sb.Append(var).Append(".coords.U_Offset = ").Append(U.F(m.UOff)).Append("\n");
            if (Math.Abs(m.VOff) > 1e-6) sb.Append(var).Append(".coords.V_Offset = ").Append(U.F(m.VOff)).Append("\n");
            if (Math.Abs(m.UTile - 1) > 1e-6) sb.Append(var).Append(".coords.U_Tiling = ").Append(U.F(m.UTile)).Append("\n");
            if (Math.Abs(m.VTile - 1) > 1e-6) sb.Append(var).Append(".coords.V_Tiling = ").Append(U.F(m.VTile)).Append("\n");
            if (Math.Abs(m.Angle) > 1e-6) sb.Append(var).Append(".coords.W_Angle = ").Append(U.F(m.Angle * 180.0 / Math.PI)).Append("\n");
            return sb.ToString();
        }

        string StdScript(MatDef md, int mode, bool hasVC, bool layers, string searchDir)
        {
            StringBuilder sb = new StringBuilder();
            if (md == null)
            {
                sb.Append("s = standardmaterial name:\"default\"\n");
                return sb.ToString();
            }
            double[] df = md.Diffuse;
            sb.Append("s = standardmaterial name:").Append(U.MS(md.Name))
              .AppendFormat(CultureInfo.InvariantCulture, " diffuse:(color {0} {1} {2}) ambient:(color {0} {1} {2})",
                (int)(df[0] * 255), (int)(df[1] * 255), (int)(df[2] * 255))
              .Append(" twoSided:").Append(md.TwoSided ? "true" : "false").Append("\n");
            sb.Append("s.specularLevel = 0; s.glossiness = 10\n");
            bool hasTex = md.DiffuseMap != null && md.DiffuseMap.Bitmap != "";
            if (hasTex)
            {
                sb.Append(Bmp("b", md.DiffuseMap, searchDir));
                sb.Append("c = b\n");
                // Viewport shows the base texture only: Max 2020's viewport draws the "Vertex Color"
                // map and some extra-channel layers as UV-coordinate colours (red/green gradients).
                // Renders use the full chain (texture x lightmap x baked vertex lighting).
                sb.Append("vp = b\n");
                if (layers)
                    foreach (MapDef l in md.Layers)
                    {
                        if (l.Bitmap == "") continue;
                        sb.Append(Bmp("lb", l, searchDir));
                        if (l.Name.Contains("BS_ADD:") && !l.Name.Contains("BS_ADDSIGNED"))
                            sb.Append("c = mix map1:c map2:lb mixAmount:50 name:\"layer add\"; c.output.output_amount = 2.0\n");
                        else
                            sb.Append("c = RGB_Multiply map1:c map2:lb name:\"layer\"\n");
                    }
            }
            else if (layers)
            {
                // no texture of its own, only layers (i2-bip01's scrolling FS_SCROLL2 effect): they
                // go to the self-illumination slot, which the exporter writes back as layers
                bool any = false;
                foreach (MapDef l in md.Layers)
                {
                    if (l.Bitmap == "") continue;
                    sb.Append(Bmp("lb", l, searchDir));
                    sb.Append(any ? "si = RGB_Multiply map1:si map2:lb name:\"layer\"\n" : "si = lb\n");
                    any = true;
                }
                if (any) sb.Append("s.selfIllumMap = si\n");
            }
            if (hasVC)
            {
                sb.Append("vc = Vertex_Color()\n");
                if (hasTex) sb.Append("c = RGB_Multiply map1:c map2:vc name:\"tex x vertex light\"\n");
                else sb.Append("c = RGB_Multiply map1:vc color2:s.diffuse name:\"diffuse x vertex light\"\nc.map2Enabled = false\n");
            }
            if (hasTex || hasVC) sb.Append("s.diffuseMap = c\n");
            if (mode == 0) sb.Append("s.useSelfIllumColor = false; s.selfIllumAmount = 100\n");
            else if (md.SelfIllum > 0.01) sb.Append("s.selfIllumAmount = ").Append((int)(md.SelfIllum * 100)).Append("\n");
            // opacity
            if (md.OpacityMap != null && md.OpacityMap.Bitmap != "" && hasTex)
            {
                bool same = string.Equals(Path.GetFileName(md.OpacityMap.Bitmap), Path.GetFileName(md.DiffuseMap.Bitmap),
                                          StringComparison.OrdinalIgnoreCase);
                sb.Append(Bmp("ob", md.OpacityMap, searchDir));
                if (same) sb.Append("ob.monoOutput = 1\n");      // alpha channel
                sb.Append("s.opacityMap = ob\n");
            }
            if (md.Transparency > 0) sb.Append("s.opacity = ").Append(U.F((1 - md.Transparency) * 100)).Append("\n");
            bool texAlpha = hasTex && HasAlpha(Resolve(md.DiffuseMap.Bitmap, searchDir));
            bool hasOpMap = md.OpacityMap != null && md.OpacityMap.Bitmap != "" && hasTex;
            if (!hasOpMap && hasTex && (texAlpha || md.Additive))
            {
                // PT renders every 32-bit texture with its alpha; additive (BLEND_LAMP /
                // ADDCOLOR) textures without alpha use their brightness instead.
                sb.Append(Bmp("ob", md.DiffuseMap, searchDir));
                sb.Append("ob.monoOutput = ").Append(texAlpha ? 1 : 0).Append("\ns.opacityMap = ob\n");
            }
            if (md.Additive) sb.Append("s.opacityType = 2\n");
            if (hasTex) sb.Append("showTextureMap s vp true\n");
            else sb.Append("showTextureMap s false\n");
            return sb.ToString();
        }
    }
}
