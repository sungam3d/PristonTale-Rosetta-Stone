// ASE -> SMD for models ("SMD Model data Ver 0.62": weapons, map props, monsters, armour) and their
// bones (.smb), ported from the 2012 source like the map builder (AseToSmd.cs):
//   smRead3d.cpp   smASE_Read (the .smd: every mesh not named "Bip..."), smASE_ReadBone (the .smb:
//                  the "Bip..." objects with their animation), ReadASE_GEOMOBJECT
//   smObj3d.cpp    smOBJ3D::Init / AddVertex / AddFace / AddTexLink / SortVertex / SetGNormals /
//                  ReformTM / ReformPhysique / SaveFile, smPAT3D::AddObject / LinkObject / SaveFile
//   smmatrix.cpp   smMatrixInvert, smMatrixFromQuaternion, smQuaternionFromAxis, smD... (double)
// A skinned model (*PHYSIQUE) is built the way the game builds a monster from one .ase: first its
// bones (.smb), then the meshes with each vertex moved into its bone's space.
//
// Model coordinates are the Max axes x 256 (not swapped as in maps); UVs are v = 1 - v.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace PTSmd
{
    public class ModelEncodeResult
    {
        public int Objects, Bones, Vertices, Faces, Materials, Textures, Unassigned;
        public bool WroteSmd, WroteSmb, Skinned;
        public string SmdPath, SmbPath;
    }

    public static partial class AseToSmd
    {
        const int ObjStructSize = 2236;

        internal sealed class MObj
        {
            public string Name = "", Parent = "";
            public List<int[]> V = new List<int[]>();            // x y z nx ny nz
            public List<int[]> F = new List<int[]>();            // a b c mat
            public List<int> FaceTex = new List<int>();
            public List<float[]> TexUV = new List<float[]>();
            public List<uint> TexH = new List<uint>();
            public List<int> TexNext = new List<int>();
            public List<MObj> Phys;                              // per vertex (null = no physique array)
            public int MaxX, MaxY, MaxZ, DBound, Bound, MaxVertex, MaxFace;
            public bool Inited, HasMaterial;
            public int[] Tm = Ident(), TmInv = CD16(), TmRotate = Ident();      // (TmInvert: uninitialised unless ReformTM runs)
            public float Qx, Qy, Qz, Qw;
            public int Sx, Sy, Sz, Px, Py, Pz;
            public List<(int f, float x, float y, float z, float w)> Rot = new List<(int, float, float, float, float)>();
            public List<float[]> PrevRot = new List<float[]>();
            public List<(int f, float x, float y, float z)> Pos = new List<(int, float, float, float)>();
            public List<(int f, int x, int y, int z)> Scl = new List<(int, int, int, int)>();
            public MObj ParentObj;

            public void AddVertex(int x, int y, int z)
            {
                V.Add(new[] { x, y, z, 0, 0, 0 });
                int mx = Math.Abs(x), my = Math.Abs(y), mz = Math.Abs(z);
                if (MaxX < mx) MaxX = mx;
                if (MaxZ < my) MaxZ = my;                          // (sic)
                if (MaxY < mz) MaxY = mz;
                unchecked
                {
                    int ax = x >> FLOATNS, ay = y >> FLOATNS, az = z >> FLOATNS;
                    int bound = Math.Abs(ax * ax + ay * ay + az * az);
                    if (DBound < bound) DBound = bound;
                }
                if (V.Count == MaxVertex) Bound = (int)Math.Sqrt(DBound);
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

        static int[] CD16() { var m = new int[16]; for (int i = 0; i < 16; i++) m[i] = unchecked((int)0xCDCDCDCD); return m; }

        static int[] Ident() { var m = new int[16]; m[0] = m[5] = m[10] = m[15] = FONE; return m; }

        // ------------------------------------------------------------------ smmatrix.cpp
        static void QuatFromAxis(ref float x, ref float y, ref float z, ref float w)
        {
            double half = w / 2.0;
            double sn = Math.Sin(half), d = Math.Cos(half);
            x = (float)(sn * x); y = (float)(sn * y); z = (float)(sn * z); w = (float)d;
        }

        static void DQuatFromAxis(ref double x, ref double y, ref double z, ref double w)
        {
            double half = w / 2.0;
            double sn = Math.Sin(half), d = Math.Cos(half);
            x = sn * x; y = sn * y; z = sn * z; w = d;
        }

        static int[] MatrixFromQuat(float x, float y, float z, float w)
        {
            int xx = Trunc(x * x * FONE), yy = Trunc(y * y * FONE), zz = Trunc(z * z * FONE);
            int xy = Trunc(x * y * FONE), xz = Trunc(x * z * FONE), yz = Trunc(y * z * FONE);
            int wx = Trunc(w * x * FONE), wy = Trunc(w * y * FONE), wz = Trunc(w * z * FONE);
            var m = new int[16];
            m[0] = FONE - 2 * (yy + zz); m[1] = 2 * (xy - wz); m[2] = 2 * (xz + wy);
            m[4] = 2 * (xy + wz); m[5] = FONE - 2 * (xx + zz); m[6] = 2 * (yz - wx);
            m[8] = 2 * (xz - wy); m[9] = 2 * (yz + wx); m[10] = FONE - 2 * (xx + yy);
            m[15] = FONE;
            return m;
        }

        static double[] DMatrixFromQuat(double x, double y, double z, double w)
        {
            double xx = x * x, yy = y * y, zz = z * z, xy = x * y, xz = x * z, yz = y * z, wx = w * x, wy = w * y, wz = w * z;
            var m = new double[16];
            m[0] = 1 - 2 * (yy + zz); m[1] = 2 * (xy - wz); m[2] = 2 * (xz + wy);
            m[4] = 2 * (xy + wz); m[5] = 1 - 2 * (xx + zz); m[6] = 2 * (yz - wx);
            m[8] = 2 * (xz - wy); m[9] = 2 * (yz + wx); m[10] = 1 - 2 * (xx + yy);
            m[15] = 1;
            return m;
        }

        static double[] DMult(double[] a, double[] b)
        {
            var m = new double[16];
            for (int i = 0; i < 4; i++)
                for (int j = 0; j < 4; j++)
                    for (int k = 0; k < 4; k++)
                        m[4 * j + i] += a[4 * j + k] * b[4 * k + i];
            return m;
        }

        // smMatrixInvert (8.8 fixed point); null when the game refuses (it then uses whatever q held)
        static int[] Invert(int[] a)
        {
            if (Math.Abs(a[15] - FONE) > 1) return null;
            if (Math.Abs(a[3]) > 1 || Math.Abs(a[7]) > 1 || Math.Abs(a[11]) > 1) return null;
            unchecked
            {
                int _11 = a[0], _12 = a[1], _13 = a[2], _21 = a[4], _22 = a[5], _23 = a[6], _31 = a[8], _32 = a[9], _33 = a[10];
                int det = ((_11 * ((_22 * _33 - _23 * _32) >> FLOATNS)) - (_12 * ((_21 * _33 - _23 * _31) >> FLOATNS)) +
                           (_13 * ((_21 * _32 - _22 * _31) >> FLOATNS))) >> FLOATNS;
                if (det != 0) det = (FONE << FLOATNS) / det;
                var q = new int[16];
                q[0] = (det * ((_22 * _33 - _23 * _32) >> FLOATNS)) >> FLOATNS;
                q[1] = -((det * ((_12 * _33 - _13 * _32) >> FLOATNS)) >> FLOATNS);
                q[2] = (det * ((_12 * _23 - _13 * _22) >> FLOATNS)) >> FLOATNS;
                q[4] = -((det * ((_21 * _33 - _23 * _31) >> FLOATNS)) >> FLOATNS);
                q[5] = (det * ((_11 * _33 - _13 * _31) >> FLOATNS)) >> FLOATNS;
                q[6] = -((det * ((_11 * _23 - _13 * _21) >> FLOATNS)) >> FLOATNS);
                q[8] = (det * ((_21 * _32 - _22 * _31) >> FLOATNS)) >> FLOATNS;
                q[9] = -((det * ((_11 * _32 - _12 * _31) >> FLOATNS)) >> FLOATNS);
                q[10] = (det * ((_11 * _22 - _12 * _21) >> FLOATNS)) >> FLOATNS;
                q[12] = -((a[12] * q[0] + a[13] * q[4] + a[14] * q[8]) >> FLOATNS);
                q[13] = -((a[12] * q[1] + a[13] * q[5] + a[14] * q[9]) >> FLOATNS);
                q[14] = -((a[12] * q[2] + a[13] * q[6] + a[14] * q[10]) >> FLOATNS);
                q[15] = FONE;
                return q;
            }
        }

        static void Transform(int[] v, int[] q, bool oldNormals = false)
        {
            unchecked
            {
                for (int s = 0; s < 6; s += 3)
                {
                    int x = v[s] * q[0] + v[s + 1] * q[4] + v[s + 2] * q[8];
                    int y = v[s] * q[1] + v[s + 1] * q[5] + v[s + 2] * q[9];
                    int z = v[s] * q[2] + v[s + 1] * q[6] + v[s + 2] * q[10];
                    bool move = s == 0 || !oldNormals;                  // (old-form normals: turned, not moved)
                    v[s] = (x >> FLOATNS) + (move ? q[12] : 0);
                    v[s + 1] = (y >> FLOATNS) + (move ? q[13] : 0);
                    v[s + 2] = (z >> FLOATNS) + (move ? q[14] : 0);
                }
            }
        }

        // ------------------------------------------------------------------ ReadASE_GEOMOBJECT
        static MObj ReadModelGeom(Lines rd, MatList ml, List<MObj> physique, int lastFrame, bool own, ModelEncodeResult res)
        {
            var o = new MObj();
            int strLevel = 0, nVertex = -1, nFace = -1, mCount = 0, matrialRef = 0, pNum = 0;
            int[] faceMat = new int[0];
            bool lightMap = false;
            UvList main = null, gameLm = null, target = null;
            var channels = new Dictionary<int, UvList>();
            bool inChannel = false;
            int chNum = 1, chLevel = 0;
            var dRot = new List<(int f, double x, double y, double z, double w)>();
            while (true)
            {
                string line = rd.Need();
                int p = 0;
                string decode = Word(line, ref p);
                bool channelLine = false;
                switch (decode)
                {
                    case "*NODE_NAME":
                    {
                        string n = Str(line, ref p);
                        o.Name = n.Length > 31 ? n.Substring(0, 31) : n;
                        break;
                    }
                    case "*NODE_PARENT":
                    {
                        string n = Str(line, ref p);
                        o.Parent = n.Length > 31 ? n.Substring(0, 31) : n;
                        break;
                    }
                    case "*MESH_NUMVERTEX": nVertex = Atoi(Word(line, ref p)); break;
                    case "*MESH_NUMFACES": nFace = Atoi(Word(line, ref p)); break;
                    case "*MESH_NUMTVERTEX":
                    {
                        Atoi(Word(line, ref p));
                        var l = new UvList();
                        if (lightMap) gameLm = l; else main = l;
                        channels[inChannel ? chNum : 1] = l;
                        target = l;
                        break;
                    }
                    case "*MESH_MAPPINGCHANNEL":
                        chNum = Atoi(Word(line, ref p)); lightMap = true; inChannel = true; chLevel = strLevel; channelLine = true;
                        break;
                    case "*TM_ROW0": case "*TM_ROW1": case "*TM_ROW2": case "*TM_ROW3":
                    {
                        int r = decode[7] - '0';
                        for (int c = 0; c < 3; c++) o.Tm[4 * r + c] = Trunc(Atof(Word(line, ref p)) * FONE);
                        break;
                    }
                    case "*TM_POS":
                        o.Px = Trunc(Atof(Word(line, ref p)) * FONE); o.Py = Trunc(Atof(Word(line, ref p)) * FONE); o.Pz = Trunc(Atof(Word(line, ref p)) * FONE);
                        break;
                    case "*TM_ROTAXIS":
                        o.Qx = (float)Atof(Word(line, ref p)); o.Qy = (float)Atof(Word(line, ref p)); o.Qz = (float)Atof(Word(line, ref p));
                        break;
                    case "*TM_ROTANGLE":
                        o.Qw = (float)Atof(Word(line, ref p));
                        QuatFromAxis(ref o.Qx, ref o.Qy, ref o.Qz, ref o.Qw);
                        o.TmRotate = MatrixFromQuat(o.Qx, o.Qy, o.Qz, o.Qw);
                        break;
                    case "*TM_SCALE":
                        o.Sx = Trunc(Atof(Word(line, ref p)) * FONE); o.Sy = Trunc(Atof(Word(line, ref p)) * FONE); o.Sz = Trunc(Atof(Word(line, ref p)) * FONE);
                        break;
                    case "*CONTROL_ROT_SAMPLE": case "*CONTROL_TCB_ROT_KEY":
                    {
                        int f = Atoi(Word(line, ref p));
                        double x = Atof(Word(line, ref p)), y = Atof(Word(line, ref p)), z = Atof(Word(line, ref p)), w = Atof(Word(line, ref p));
                        dRot.Add((f, x, y, z, w));
                        break;
                    }
                    case "*CONTROL_POS_SAMPLE": case "*CONTROL_TCB_POS_KEY": case "*CONTROL_BEZIER_POS_KEY":
                    {
                        int f = Atoi(Word(line, ref p));
                        o.Pos.Add((f, (float)Atof(Word(line, ref p)), (float)Atof(Word(line, ref p)), (float)Atof(Word(line, ref p))));
                        break;
                    }
                    case "*CONTROL_SCALE_SAMPLE": case "*CONTROL_TCB_SCALE_KEY": case "*CONTROL_BEZIER_SCALE_KEY":
                    {
                        int f = Atoi(Word(line, ref p));
                        o.Scl.Add((f, Trunc(Atof(Word(line, ref p)) * FONE), Trunc(Atof(Word(line, ref p)) * FONE), Trunc(Atof(Word(line, ref p)) * FONE)));
                        break;
                    }
                    case "*MESH_VERTEX":
                    {
                        Word(line, ref p);
                        int x = Fixed(Atof(Word(line, ref p)), own), y = Fixed(Atof(Word(line, ref p)), own), z = Fixed(Atof(Word(line, ref p)), own);
                        if (o.Inited) o.AddVertex(x, y, z);
                        break;
                    }
                    case "*MESH_FACE":
                    {
                        Word(line, ref p);
                        Word(line, ref p); int a = Atoi(Word(line, ref p));
                        Word(line, ref p); int b = Atoi(Word(line, ref p));
                        Word(line, ref p); int c = Atoi(Word(line, ref p));
                        if (o.Inited) { o.F.Add(new[] { a, b, c, 0 }); o.FaceTex.Add(-1); }
                        for (int k = 0; k < 16; k++)
                            if (Word(line, ref p) == "*MESH_MTLID")
                            {
                                int id = Atoi(Word(line, ref p));
                                if (mCount < faceMat.Length) faceMat[mCount] = id;
                                mCount++;
                                break;
                            }
                        break;
                    }
                    case "*MESH_TVERT":
                        if (target != null)
                        {
                            Word(line, ref p);
                            target.U.Add((float)Atof(Word(line, ref p)));
                            target.V.Add((float)Atof(Word(line, ref p)));
                        }
                        break;
                    case "*MESH_TFACE":
                        if (target != null)
                        {
                            Word(line, ref p);
                            target.F.Add(new[] { Atoi(Word(line, ref p)), Atoi(Word(line, ref p)), Atoi(Word(line, ref p)) });
                        }
                        break;
                    case "*MATERIAL_REF": matrialRef = Atoi(Word(line, ref p)); o.HasMaterial = true; break;
                    case "*PHYSIQUE_VERTEXASSIGNMENT_NONBLENDED_RIGIDTYPE":
                        if (physique != null && o.Phys != null)
                        {
                            pNum = Atoi(Word(line, ref p));
                            string bn = Str(line, ref p);
                            if (pNum >= 0 && pNum < o.Phys.Count) o.Phys[pNum] = FindObj(physique, bn);
                        }
                        break;
                    case "*PHYSIQUE_VERTEXASSIGNMENT_BLENDED_RIGIDTYPE":
                        if (physique != null) pNum = Atoi(Word(line, ref p));
                        break;
                    case "*PHYSIQUE_VERTEXASSIGNMENT_NODE":
                        if (physique != null && o.Phys != null)
                        {
                            int x = Atoi(Word(line, ref p));
                            Word(line, ref p);
                            string bn = Str(line, ref p);
                            if (x == 0 && pNum >= 0 && pNum < o.Phys.Count) o.Phys[pNum] = FindObj(physique, bn);
                        }
                        break;
                }
                if (!o.Inited && nVertex >= 0 && nFace >= 0)
                {
                    o.Inited = true;
                    o.MaxVertex = nVertex; o.MaxFace = nFace;
                    if (physique != null) { o.Phys = new List<MObj>(); for (int i = 0; i < nVertex; i++) o.Phys.Add(null); }
                    faceMat = new int[nFace];
                }

                string w2 = Word(line, ref p);
                if (decode == "{" || w2 == "{") strLevel++;
                if (decode == "}" || w2 == "}")
                {
                    strLevel--;
                    if (strLevel < 0) break;
                    if (inChannel && !channelLine && strLevel == chLevel) inChannel = false;
                }
            }
            if (own) channels.TryGetValue(1, out main);

            // faces: materials and UVs (v = 1 - v for models)
            int nf = o.F.Count;
            for (int f = 0; f < nf; f++)
                for (int k = 0; k < 3; k++)
                    if (o.F[f][k] < 0 || o.F[f][k] >= o.V.Count) { res.Unassigned += 0; o.F[f][k] = 0; }
            ml.SubCount.TryGetValue(matrialRef, out int subN);
            int subPoint = ml.A.I(matrialRef, AseMats.SubPoint);
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
                for (int k = 0; k < 3; k++)
                {
                    var c = Corner(l, face, k);
                    double fU = c[0] - 0.5, fV = c[1] - 0.5;
                    double fu = fU * fc + fV * fs, fv = fV * fc - fU * fs;
                    fu -= ou; fv -= ov; fu *= tu; fv *= tv;
                    uv[k] = (float)(fu + 0.5); uv[3 + k] = (float)(1 - (float)(fv + 0.5));
                }
                return uv;
            }
            for (int cnt = 0; cnt < nf; cnt++)
            {
                if (ml.Mats.Count == 0) break;
                int id = cnt < faceMat.Length ? faceMat[cnt] : 0;
                if (own && subN > 0) id = ((id % subN) + subN) % subN;
                int fmat = subPoint != 0 ? subPoint + id : matrialRef;
                int mNum = ml.A.I(fmat, AseMats.RegistNum);
                if (mNum < 0 || mNum >= ml.Mats.Count) mNum = 0;
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
                    o.AddTexLink(cnt, HTex(mNum, t), Xform(src, cnt, fmat, t));
                }
                if (lm)
                {
                    t = Math.Max(texCnt, 0);
                    o.AddTexLink(cnt, HTex(mNum, t), Xform(gameLm, cnt, fmat, t));
                }
                o.F[cnt][3] = mNum;
            }

            // animation: last keys held to the scene's last frame; rotations as quaternions plus the
            // running product of all rotations so far (TmPrevRot)
            if (own)                                              // (our decoder ends each track 1 tick early:
            {                                                     //  that key goes back to the scene's end)
                if (dRot.Count > 0 && dRot[dRot.Count - 1].f == lastFrame - 1) { var k = dRot[dRot.Count - 1]; dRot[dRot.Count - 1] = (lastFrame, k.x, k.y, k.z, k.w); }
                if (o.Pos.Count > 0 && o.Pos[o.Pos.Count - 1].f == lastFrame - 1) { var k = o.Pos[o.Pos.Count - 1]; o.Pos[o.Pos.Count - 1] = (lastFrame, k.x, k.y, k.z); }
                if (o.Scl.Count > 0 && o.Scl[o.Scl.Count - 1].f == lastFrame - 1) { var k = o.Scl[o.Scl.Count - 1]; o.Scl[o.Scl.Count - 1] = (lastFrame, k.x, k.y, k.z); }
            }
            if (dRot.Count > 0 && dRot[dRot.Count - 1].f < lastFrame) { var k = dRot[dRot.Count - 1]; dRot.Add((lastFrame, k.x, k.y, k.z, k.w)); }
            if (o.Pos.Count > 0 && o.Pos[o.Pos.Count - 1].f < lastFrame) { var k = o.Pos[o.Pos.Count - 1]; o.Pos.Add((lastFrame, k.x, k.y, k.z)); }
            if (o.Scl.Count > 0 && o.Scl[o.Scl.Count - 1].f < lastFrame) { var k = o.Scl[o.Scl.Count - 1]; o.Scl.Add((lastFrame, k.x, k.y, k.z)); }
            if (dRot.Count > 0)
            {
                var prev = new double[16];
                prev[0] = prev[5] = prev[10] = prev[15] = 1;
                foreach (var k in dRot)
                {
                    double x = k.x, y = k.y, z = k.z, w = k.w;
                    DQuatFromAxis(ref x, ref y, ref z, ref w);
                    prev = DMult(prev, DMatrixFromQuat(x, y, z, w));
                    var fm = new float[16];
                    for (int i = 0; i < 16; i++) fm[i] = (float)prev[i];
                    o.PrevRot.Add(fm);
                    float fx = (float)k.x, fy = (float)k.y, fz = (float)k.z, fw = (float)k.w;
                    QuatFromAxis(ref fx, ref fy, ref fz, ref fw);
                    o.Rot.Add((k.f, fx, fy, fz, fw));
                }
            }
            return o;
        }

        static MObj FindObj(List<MObj> l, string name)
        {
            foreach (var o in l) if (AsciiNoCase.I.Equals(o.Name, name)) return o;
            return null;
        }

        // SortVertex: merges identical vertices and drops unused ones - as the game does it (the
        // second pass keeps the use counts of the original numbering)
        static void SortVertex(MObj o)
        {
            var V = o.V; var F = o.F; var P = o.Phys;
            int n = V.Count;
            for (int c1 = 1; c1 < n; c1++)
                for (int c2 = 0; c2 < c1; c2++)
                {
                    if (c1 < n && V[c1][0] == V[c2][0] && V[c1][1] == V[c2][1] && V[c1][2] == V[c2][2])
                    {
                        foreach (var f in F)
                        {
                            for (int k = 0; k < 3; k++) if (f[k] == c1) f[k] = c2;
                            for (int k = 0; k < 3; k++) if (f[k] > c1) f[k]--;
                        }
                        n--;
                        V.RemoveAt(c1);
                        if (P != null) P.RemoveAt(c1);
                    }
                }
            var use = new short[n];
            foreach (var f in F) for (int k = 0; k < 3; k++) if (f[k] >= 0 && f[k] < n) use[f[k]]++;
            for (int c1 = 0; c1 < n; c1++)
            {
                if (use[c1] != 0) continue;
                foreach (var f in F) for (int k = 0; k < 3; k++) if (f[k] > c1) f[k]--;
                n--;
                if (c1 < V.Count) { V.RemoveAt(c1); if (P != null) P.RemoveAt(c1); }
            }
        }

        static void SetGNormals(MObj o, bool old)
        {
            var cnt = new int[o.V.Count];
            foreach (var v in o.V) { v[3] = v[4] = v[5] = 0; }
            var n = new int[3];
            foreach (var f in o.F)
            {
                int[] p1 = o.V[f[0]], p2 = o.V[f[1]], p3 = o.V[f[2]];
                SetNormal(p1, p2, p3, n, false);
                for (int k = 0; k < 3; k++)
                {
                    var v = o.V[f[k]];
                    unchecked { v[3] += n[0]; v[4] += n[1]; v[5] += n[2]; }
                    cnt[f[k]]++;
                }
            }
            for (int i = 0; i < o.V.Count; i++)
                if (cnt[i] > 0)
                {
                    var v = o.V[i];
                    v[3] /= cnt[i]; v[4] /= cnt[i]; v[5] /= cnt[i];
                    if (!old) { v[3] += v[0]; v[4] += v[1]; v[5] += v[2]; }
                }
        }

        static void ReformTM(MObj o, bool oldNormals)
        {
            int scale = o.ParentObj == null ? (o.Sx + o.Sy + o.Sz) / 3 : (o.ParentObj.Sx + o.ParentObj.Sy + o.ParentObj.Sz) / 3;
            if (scale != 0)
                unchecked { foreach (int i in new[] { 0, 1, 2, 4, 5, 6, 8, 9, 10 }) o.Tm[i] = (o.Tm[i] << FLOATNS) / scale; }
            var q = Invert(o.Tm);
            if (q == null)                                        // (the game refuses: TmInvert stays uninitialised
            {                                                     //  memory and the vertices stay where they are)
                o.TmInv = new int[16];
                for (int i = 0; i < 16; i++) o.TmInv[i] = unchecked((int)0xCDCDCDCD);
                return;
            }
            o.TmInv = q;
            foreach (var v in o.V) Transform(v, q, oldNormals);
        }

        static void ReformPhysique(MObj o, ref int unassigned, bool oldNormals)
        {
            for (int i = 0; i < o.V.Count; i++)
            {
                var b = o.Phys != null && i < o.Phys.Count ? o.Phys[i] : null;
                if (b == null) { unassigned++; continue; }               // (the game would crash here)
                var q = Invert(b.Tm);
                if (q != null) Transform(o.V[i], q, oldNormals);
            }
        }

        static void LinkObjects(List<MObj> objs)
        {
            foreach (var o in objs)
                if (o.Parent.Length > 0)
                    foreach (var p in objs) if (AsciiNoCase.I.Equals(o.Parent, p.Name)) { o.ParentObj = p; break; }
        }

        // ------------------------------------------------------------------ reading a whole file
        static string Head(string line) { int p = 0; return Word(line, ref p); }

        static int SceneLastFrame(Lines rd)
        {
            int last = 0;
            rd.Rewind();
            while (rd.Next(out string line))
                if (Head(line) == "*SCENE_LASTFRAME") { int p = 0; Word(line, ref p); last = Atoi(Word(line, ref p)) * 160; }
            rd.Rewind();
            return last;
        }

        static void SkipBlock(Lines rd)
        {
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

        static bool IsBip(string name) => name.Length >= 3 && name[0] == 'B' && name[1] == 'i' && name[2] == 'p';

        // a bone: the game takes the "Bip..." objects.  Our decoder and exporters write every bone (also the
        // few without a Bip name, e.g. facial bones) as a mesh without *MATERIAL_REF - but 3ds Max also
        // leaves it off a new mesh without a material, so such a mesh is a bone only when a skin uses it
        // or it has animation keys.
        sealed class BoneSet
        {
            public readonly HashSet<string> Names = new HashSet<string>(AsciiNoCase.I);
            public bool Own;
            public bool Is(string name) => IsBip(name) ? true : Own && Names.Contains(name);
        }

        static BoneSet Bones(string asePath, bool own)
        {
            var bs = new BoneSet { Own = own };
            if (!own) return bs;
            var refs = new HashSet<string>(AsciiNoCase.I);
            var cand = new List<(string name, bool mat, bool anim)>();
            string name = null;
            bool inGeom = false, mat = false, anim = false;
            void Close() { if (inGeom && name != null) cand.Add((name, mat, anim)); inGeom = false; }
            foreach (var l in File.ReadLines(asePath, Bin.Latin1))
            {
                if (l.Length > 0 && l[0] == '*') { Close(); if (l.StartsWith("*GEOMOBJECT", StringComparison.Ordinal)) { inGeom = true; name = null; mat = anim = false; } continue; }
                if (!inGeom) continue;
                string t = l.TrimStart();
                if (name == null && t.StartsWith("*NODE_NAME", StringComparison.Ordinal))
                {
                    int i = t.IndexOf('"');
                    name = i >= 0 ? t.Substring(i + 1).TrimEnd('"', ' ', '\t') : "";
                }
                else if (t.StartsWith("*MATERIAL_REF", StringComparison.Ordinal)) mat = true;
                else if (t.StartsWith("*TM_ANIMATION", StringComparison.Ordinal)) anim = true;
                else if (t.StartsWith("*PHYSIQUE_VERTEXASSIGNMENT", StringComparison.Ordinal))
                {
                    int a = t.IndexOf('"'), b = t.LastIndexOf('"');
                    if (a >= 0 && b > a) refs.Add(t.Substring(a + 1, b - a - 1));
                }
            }
            Close();
            foreach (var c in cand) if (!c.mat && (refs.Contains(c.name) || c.anim)) bs.Names.Add(c.name);
            return bs;
        }

        /// <summary>smASE_ReadBone: the "Bip..." objects of the file (bones and their animation).</summary>
        static List<MObj> ReadBones(string asePath, bool own, bool oldNormals, ModelEncodeResult res)
        {
            var bs = Bones(asePath, own);
            var rd = new Lines(asePath);
            int last = SceneLastFrame(rd);
            var none = new MatList();
            var bones = new List<MObj>();
            while (rd.Next(out string line))
            {
                if (Head(line) != "*GEOMOBJECT") continue;
                var o = ReadModelGeom(rd, none, null, last, own, res);
                if (bs.Is(o.Name)) bones.Add(o);
            }
            LinkObjects(bones);
            foreach (var o in bones) { SetGNormals(o, oldNormals); ReformTM(o, oldNormals); }
            return bones;
        }

        /// <summary>What the model .ase holds: bones, meshes, and meshes skinned to the bones.</summary>
        public static void ModelParts(string asePath, out bool bones, out bool skinned, out bool meshes, bool? ownFile = null)
        {
            bool own = ownFile ?? IsOwnFile(asePath);
            var bs = Bones(asePath, own);
            bool b = false, m = false, sk = false;
            string name = null;
            bool inGeom = false;
            void Close() { if (inGeom && name != null) { if (bs.Is(name)) b = true; else m = true; } inGeom = false; }
            foreach (var l in File.ReadLines(asePath, Bin.Latin1))
            {
                if (l.Length > 0 && l[0] == '*') { Close(); if (l.StartsWith("*GEOMOBJECT", StringComparison.Ordinal)) { inGeom = true; name = null; } continue; }
                if (!inGeom) continue;
                string t = l.TrimStart();
                if (name == null && t.StartsWith("*NODE_NAME", StringComparison.Ordinal))
                {
                    int i = t.IndexOf('"');
                    name = i >= 0 ? t.Substring(i + 1).TrimEnd('"', ' ', '\t') : "";
                }
                else if (t.StartsWith("*PHYSIQUE", StringComparison.Ordinal) || t.StartsWith("*SKIN", StringComparison.Ordinal)) sk = true;
            }
            Close();
            bones = b; skinned = sk; meshes = m;
        }

        /// <summary>Build a model .smd (and, when the .ase has bones, its .smb) the way the game does.
        /// smbPath null: no .smb.  A skinned model uses the bones of this .ase (bonesAse null) or of
        /// another .ase (the class / motion file).</summary>
        public static ModelEncodeResult Model(string asePath, string smdPath, string smbPath, EncodeOptions opt = null, string bonesAse = null)
        {
            opt = opt ?? new EncodeOptions();
            var res = new ModelEncodeResult();
            bool own = opt.OwnFile ?? IsOwnFile(asePath);
            string dataDir = opt.DataDir ?? "";
            if (dataDir.Length > 0 && !dataDir.EndsWith("\\")) dataDir += "\\";
            ModelParts(asePath, out bool hasBones, out bool skinned, out bool hasMeshes, own);
            res.Skinned = skinned;

            List<MObj> bones = null;
            if (hasBones || bonesAse != null)
            {
                bones = ReadBones(bonesAse ?? asePath, own, opt.OldNormals, res);
                res.Bones = bones.Count;
                if (smbPath != null && hasBones && bonesAse == null)
                {
                    var pat = new List<MObj>(bones);
                    WriteModel(smbPath, pat, null, opt.OldNormals);
                    res.WroteSmb = true; res.SmbPath = smbPath;
                }
            }

            if (hasMeshes && smdPath != null)
            {
                var rd = new Lines(asePath);
                int last = SceneLastFrame(rd);
                MatList ml = null;
                var objs = new List<MObj>();
                var phys = skinned ? bones : null;
                var boneSet = Bones(asePath, own);
                while (rd.Next(out string line))
                {
                    string d = Head(line);
                    if (d == "*MATERIAL_LIST") ml = ReadMaterials(rd, dataDir, own);
                    else if (d == "*GEOMOBJECT")
                    {
                        var o = ReadModelGeom(rd, ml ?? new MatList(), phys, last, own, res);
                        if (boneSet.Is(o.Name)) continue;
                        if (!own) SortVertex(o);                     // (our files hold the game's vertices already;
                                                                     //  merging ones that meet after rounding would
                                                                     //  renumber the rest)
                        objs.Add(o);
                    }
                }
                ml = ml ?? new MatList();
                int unassigned = 0;
                int maxFrame;
                if (phys != null)
                {
                    foreach (var o in objs)
                    {
                        SetGNormals(o, opt.OldNormals);
                        ReformPhysique(o, ref unassigned, opt.OldNormals);
                        if (own) { var q = Invert(o.Tm); if (q != null) o.TmInv = q; }   // (unused by the game; keeps the
                    }                                                                    //  pivot when decoded again)
                    maxFrame = MaxFrame(bones);
                }
                else
                {
                    LinkObjects(objs);
                    foreach (var o in objs) { SetGNormals(o, opt.OldNormals); ReformTM(o, opt.OldNormals); }
                    maxFrame = MaxFrame(objs);
                }
                res.Unassigned = unassigned;
                WriteModel(smdPath, objs, ml, opt.OldNormals);
                res.WroteSmd = true; res.SmdPath = smdPath;
                res.Objects = objs.Count;
                foreach (var o in objs) { res.Vertices += o.V.Count; res.Faces += o.F.Count; }
                res.Materials = ml.Mats.Count; res.Textures = ml.Tex.List.Count;
            }
            return res;
        }

        /// <summary>The skeleton file our decoder names in *PT_SKELETON (null if none).</summary>
        public static string SkeletonName(string asePath)
        {
            foreach (var l in File.ReadLines(asePath, Bin.Latin1))
            {
                string t = l.TrimStart();
                if (t.StartsWith("*PT_SKELETON", StringComparison.Ordinal))
                {
                    int a = t.IndexOf('"'), b = t.LastIndexOf('"');
                    string n = a >= 0 && b > a ? t.Substring(a + 1, b - a - 1) : "";
                    return n.Length > 0 ? Path.GetFileName(n.Replace('/', '\\')) : null;
                }
                if (t.StartsWith("*GEOMOBJECT", StringComparison.Ordinal)) break;
            }
            return null;
        }

        /// <summary>True when some object of the .ase has animation keys.</summary>
        public static bool HasBoneAnimation(string asePath)
        {
            foreach (var l in File.ReadLines(asePath, Bin.Latin1))
                if (l.TrimStart().StartsWith("*TM_ANIMATION", StringComparison.Ordinal)) return true;
            return false;
        }

        // the client's top folders: a texture path below one of them names the game folder
        static readonly string[] TopFolders = { "char", "field", "image", "effect", "sky", "weapons", "csel" + "ect", "startimage", "wav", "assets" };

        /// <summary>The game folder of the first texture an .ase points at (C:\...\Field\Ricarten\x.bmp ->
        /// "field\Ricarten"), or null.</summary>
        public static string GameDirFromBitmaps(string asePath)
        {
            foreach (var l in File.ReadLines(asePath, Bin.Latin1))
            {
                string t = l.TrimStart();
                if (!t.StartsWith("*BITMAP ", StringComparison.Ordinal)) continue;
                int a = t.IndexOf('"'), b = t.LastIndexOf('"');
                if (a < 0 || b <= a) continue;
                var parts = t.Substring(a + 1, b - a - 1).Replace('/', '\\').Split('\\');
                for (int i = 0; i < parts.Length - 1; i++)          // (the outermost one: Effect\Sky\Field\...)
                    if (Array.IndexOf(TopFolders, parts[i].ToLowerInvariant()) >= 0)
                        return string.Join("\\", parts, i, parts.Length - 1 - i);
            }
            return null;
        }

        static int MaxFrame(List<MObj> objs)
        {
            int m = 0;
            foreach (var o in objs)
            {
                int f = 0;
                if (o.Rot.Count > 0) f = o.Rot[o.Rot.Count - 1].f;
                if (o.Pos.Count > 0) f = o.Pos[o.Pos.Count - 1].f;
                if (m < f) m = f;
            }
            return m;
        }

        // ------------------------------------------------------------------ smPAT3D::SaveFile
        static void WriteModel(string path, List<MObj> objs, MatList ml, bool oldNormals)
        {
            var ms = new MemoryStream(1 << 20);
            var w = new BinaryWriter(ms);
            byte[] group = ml != null && ml.Mats.Count > 0 ? GroupBytes(ml) : null;
            int nObj = objs.Count;

            var hdr = new byte[Smd.FileHeaderSize];
            Encoding.ASCII.GetBytes(Smd.ModelHeader).CopyTo(hdr, 0);
            BitConverter.GetBytes(nObj).CopyTo(hdr, 24);
            BitConverter.GetBytes(group != null ? ml.Mats.Count : 0).CopyTo(hdr, 28);
            int pFile = Smd.FileHeaderSize + 40 * nObj;
            BitConverter.GetBytes(pFile).CopyTo(hdr, 32);
            if (group != null) pFile += group.Length;
            BitConverter.GetBytes(pFile).CopyTo(hdr, 36);
            w.Write(hdr);

            var bodies = new List<byte[]>();
            for (int i = 0; i < nObj; i++) bodies.Add(ObjBytes(objs[i], i, objs, oldNormals));
            foreach (var (o, b) in Zip(objs, bodies))
            {
                var name = new byte[32];
                var nb = Bin.Latin1.GetBytes(o.Name);
                Array.Copy(nb, name, Math.Min(31, nb.Length));
                w.Write(name);
                w.Write(b.Length);
                w.Write(pFile);
                pFile += b.Length;
            }
            if (group != null) w.Write(group);
            foreach (var b in bodies) w.Write(b);
            w.Flush();
            string d = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(d)) Directory.CreateDirectory(d);
            File.WriteAllBytes(path, ms.ToArray());
        }

        static IEnumerable<(MObj, byte[])> Zip(List<MObj> a, List<byte[]> b)
        {
            for (int i = 0; i < a.Count; i++) yield return (a[i], b[i]);
        }

        static byte[] GroupBytes(MatList ml)
        {
            var ms = new MemoryStream();
            var w = new BinaryWriter(ms);
            w.Write(0); w.Write(PtrMaterial); w.Write(ml.Mats.Count); w.Write(ml.ReformTexture); w.Write(ml.Mats.Count); w.Write(0);
            w.Write(new byte[64]);
            foreach (var m in ml.Mats)
            {
                var b = (byte[])m.B.Clone();
                for (int t = 0; t < 8; t++)
                    if (m.Tex[t] >= 0) BitConverter.GetBytes((uint)(PtrTexture + m.Tex[t] * TextureHandleSize)).CopyTo(b, Mat.smTexture + 4 * t);
                for (int t = 0; t < 32; t++)
                    if (m.Anim[t] >= 0) BitConverter.GetBytes((uint)(PtrTexture + m.Anim[t] * TextureHandleSize)).CopyTo(b, Mat.smAnimTexture + 4 * t);
                w.Write(b);
                if (m.I(Mat.InUse) == 0) continue;
                var s = new MemoryStream();
                int tc = Math.Min(Math.Max(m.I(Mat.TextureCounter), 0), 8), ac = Math.Min(Math.Max(m.I(Mat.AnimTexCounter), 0), 32);
                for (int t = 0; t < tc + ac; t++)
                {
                    int h = t < tc ? m.Tex[t] : m.Anim[t - tc];
                    var (n, na) = h >= 0 ? ml.Tex.List[h] : ("", "");
                    byte[] x = Bin.Latin1.GetBytes(n), y = Bin.Latin1.GetBytes(na);
                    s.Write(x, 0, x.Length); s.WriteByte(0);
                    s.Write(y, 0, y.Length); s.WriteByte(0);
                }
                var nb = s.ToArray();
                w.Write(nb.Length); w.Write(nb);
            }
            w.Flush();
            return ms.ToArray();
        }

        // smOBJ3D::SaveFile: the 2236-byte object, then vertices, faces, links, keys, physique names
        static byte[] ObjBytes(MObj o, int index, List<MObj> all, bool oldNormals)
        {
            uint basePtr = (uint)(0x30000000 + index * 0x00100000);
            uint vPtr = basePtr, fPtr = basePtr + 0x40000, tPtr = basePtr + 0x80000, pPtr = basePtr + 0xC0000;
            var S = new byte[ObjStructSize];
            void I(int off, int v) => BitConverter.GetBytes(v).CopyTo(S, off);
            void U(int off, uint v) => BitConverter.GetBytes(v).CopyTo(S, off);
            void Fl(int off, float v) => BitConverter.GetBytes(v).CopyTo(S, off);
            U(0, oldNormals ? 0x41424344u : 0x41424344u | 0x80000000u);
            U(4, vPtr); U(8, fPtr); U(12, tPtr); U(16, o.Phys != null ? pPtr : 0);
            I(44, o.MaxZ); I(52, o.MaxY); I(60, o.MaxX);
            I(68, o.DBound); I(72, o.Bound); I(76, o.MaxVertex); I(80, o.MaxFace);
            I(84, o.V.Count); I(88, o.F.Count); I(92, o.TexUV.Count);
            I(96, 1); I(100, 0x3F);
            var nm = Bin.Latin1.GetBytes(o.Name); Array.Copy(nm, 0, S, 172, Math.Min(31, nm.Length));
            var pn = Bin.Latin1.GetBytes(o.Parent); Array.Copy(pn, 0, S, 204, Math.Min(31, pn.Length));
            if (o.ParentObj != null) U(236, (uint)(0x2F000000 + all.IndexOf(o.ParentObj) * ObjStructSize));
            for (int i = 0; i < 16; i++) { I(240 + 4 * i, o.Tm[i]); I(304 + 4 * i, o.TmInv[i]); I(432 + 4 * i, o.TmRotate[i]); }
            var id = Ident();
            for (int i = 0; i < 16; i++) I(560 + 4 * i, id[i]);                           // mLocal
            Fl(628, o.Qx); Fl(632, o.Qy); Fl(636, o.Qz); Fl(640, o.Qw);
            I(644, o.Sx); I(648, o.Sy); I(652, o.Sz); I(656, o.Px); I(660, o.Py); I(664, o.Pz);
            if (o.Rot.Count > 0) { U(668, basePtr + 0xD0000); U(680, basePtr + 0xE0000); }
            if (o.Pos.Count > 0) U(672, basePtr + 0xD8000);
            if (o.Scl.Count > 0) U(676, basePtr + 0xDC000);
            I(684, o.Rot.Count); I(688, o.Pos.Count); I(692, o.Scl.Count);

            var ms = new MemoryStream();
            var w = new BinaryWriter(ms);
            w.Write(S);
            foreach (var v in o.V) for (int k = 0; k < 6; k++) w.Write(v[k]);
            for (int f = 0; f < o.F.Count; f++)
            {
                var fc = o.F[f];
                for (int k = 0; k < 4; k++) w.Write((ushort)fc[k]);
                w.Write(new byte[24]);                                                       // (t[3]: unused)
                w.Write(o.FaceTex[f] >= 0 ? tPtr + (uint)(o.FaceTex[f] * 32) : 0u);
            }
            for (int t = 0; t < o.TexUV.Count; t++)
            {
                for (int k = 0; k < 6; k++) w.Write(o.TexUV[t][k]);
                w.Write(o.TexH[t]);
                w.Write(o.TexNext[t] >= 0 ? tPtr + (uint)(o.TexNext[t] * 32) : 0u);
            }
            foreach (var k in o.Rot) { w.Write(k.f); w.Write(k.x); w.Write(k.y); w.Write(k.z); w.Write(k.w); }
            foreach (var k in o.Pos) { w.Write(k.f); w.Write(k.x); w.Write(k.y); w.Write(k.z); }
            foreach (var k in o.Scl) { w.Write(k.f); w.Write(k.x); w.Write(k.y); w.Write(k.z); }
            foreach (var m in o.PrevRot) foreach (var x in m) w.Write(x);
            if (o.Phys != null)
                foreach (var b in o.Phys)
                {
                    var nb = new byte[32];
                    if (b != null) { var x = Bin.Latin1.GetBytes(b.Name); Array.Copy(x, nb, Math.Min(31, x.Length)); }
                    w.Write(nb);
                }
            w.Flush();
            return ms.ToArray();
        }
    }
}
