using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace PTSmd
{
    /// <summary>One smMATERIAL entry (320 bytes + texture name strings).</summary>
    public class Material
    {
        public static readonly (int bit, string name)[] UseStateNames =
        {
            (0x1, "wind:"), (0x2, "anim2:"), (0x4, "anim4:"), (0x8, "anim8:"), (0x10, "anim16:"),
            (0x20, "wind_z1:"), (0x40, "wind_z2:"), (0x80, "wind_x1:"), (0x100, "wind_x2:"),
            (0x200, "water:"), (0x400, "wall:"), (0x800, "pass:"), (0x1000, "notpass:"),
            (0x2000, "render_latter:"), (0x4000, "BLINK_COLOR:"), (0x8000, "ice:"), (0x10000, "orgwater:"),
        };
        static readonly Dictionary<int, string> BlendNames = new Dictionary<int, string>
            { { 2, "BLEND_COLOR:" }, { 3, "BLEND_SHADOW:" }, { 4, "BLEND_LAMP:" }, { 5, "BLEND_ADDCOLOR:" } };
        public static readonly Dictionary<int, string> BlendTypeNames = new Dictionary<int, string>
            { { 0, "none" }, { 1, "alpha" }, { 2, "color" }, { 3, "shadow" }, { 4, "lamp" }, { 5, "addcolor" } };
        static readonly Dictionary<int, string> StageStateNames = new Dictionary<int, string>
        {
            { 4, "BS_MODULATE:" }, { 5, "BS_MODULATE2X:" }, { 6, "BS_MODULATE4X:" }, { 7, "BS_ADD:" },
            { 8, "BS_ADDSIGNED:" }, { 9, "BS_ADDSIGNED2X:" }, { 10, "BS_SUBTRACT:" },
        };
        static readonly string[] FormStateNames =
        {
            "FS_NONE:", "FS_FORMX:", "FS_FORMY:", "FS_FORMZ:", "FS_SCROLL:", "FS_REFLEX:",
            "FS_SCROLL2:", "FS_SCROLL3:", "FS_SCROLL4:", "FS_SCROLL5:", "FS_SCROLL6:",
            "FS_SCROLL7:", "FS_SCROLL8:", "FS_SCROLL9:", "FS_SCROLL10:",
            "FS_SCROLLSLOW1:", "FS_SCROLLSLOW2:", "FS_SCROLLSLOW3:", "FS_SCROLLSLOW4:",
        };

        public int Index;
        public int InUse, TexCount, MapOpacity, TextureType, BlendType, TwoSided, UseState, MeshState, WindBottom;
        public int[] StageState = new int[8], FormState = new int[8];
        public double[] Diffuse = new double[3];
        public double Transparency, SelfIllum;
        public int AnimCount, AnimFrameMask, AnimSpeedShift, AnimFrame;
        public List<(string name, string nameA)> Textures = new List<(string, string)>();
        public List<(string name, string nameA)> AnimTextures = new List<(string, string)>();
        public List<bool> AlphaFromSelf = new List<bool>();

        public Material(int index, byte[] b, int o, string[] names)
        {
            Index = index;
            InUse = Bin.I(b, o);
            TexCount = Bin.I(b, o + 4);
            for (int i = 0; i < 8; i++)
            {
                StageState[i] = Bin.I(b, o + 40 + 4 * i);
                FormState[i] = Bin.I(b, o + 72 + 4 * i);
            }
            MapOpacity = Bin.I(b, o + 108);
            TextureType = Bin.I(b, o + 112);
            BlendType = Bin.I(b, o + 116);
            TwoSided = Bin.I(b, o + 124);
            for (int i = 0; i < 3; i++) Diffuse[i] = Bin.F(b, o + 132 + 4 * i);
            Transparency = Bin.F(b, o + 144);
            SelfIllum = Bin.F(b, o + 148);
            UseState = Bin.I(b, o + 164);
            MeshState = Bin.I(b, o + 168);
            WindBottom = Bin.I(b, o + 172);
            AnimCount = Bin.I(b, o + 304);
            AnimFrameMask = Bin.I(b, o + 308);
            AnimSpeedShift = Bin.I(b, o + 312);
            AnimFrame = Bin.I(b, o + 316);
            int k = 0;
            for (int i = 0; i < TexCount && i < 64; i++, k += 2)
            {
                CleanPair(names, k, out string n, out string na, out bool selfA);
                Textures.Add((n, na));
                AlphaFromSelf.Add(selfA);
            }
            for (int i = 0; i < AnimCount && i < 256; i++, k += 2)
            {
                CleanPair(names, k, out string n, out string na, out bool _);
                AnimTextures.Add((n, na));
            }
        }

        static bool ValidTexName(string s)
        {
            if (string.IsNullOrEmpty(s) || s.IndexOf('.') < 0) return false;
            foreach (char c in s) if (c < 32 || c >= 127) return false;
            return true;
        }

        // PT marks "alpha comes from Name itself" by overwriting NameA[0] with 0x01,
        // leaving stale bytes behind ("\x01ield\forest\x.tga").  Garbage is dropped.
        static void CleanPair(string[] names, int k, out string n, out string na, out bool selfAlpha)
        {
            n = k < names.Length ? names[k] : "";
            na = k + 1 < names.Length ? names[k + 1] : "";
            selfAlpha = na.Length > 0 && na[0] == '\x01';
            if (selfAlpha) na = "";
            if (!ValidTexName(n)) n = "";
            if (!ValidTexName(na)) na = "";
        }

        /// <summary>Invisible in game: 'wall:' collision walls and untextured helpers.</summary>
        public bool IsCollision => (UseState & 0x400) != 0 || (TexCount == 0 && AnimCount == 0);

        public List<string> Flags
        {
            get
            {
                var l = new List<string>();
                foreach (var f in UseStateNames) if ((UseState & f.bit) != 0) l.Add(f.name);
                return l;
            }
        }

        static string BaseName(string p)
        {
            p = p.Replace('\\', '/');
            int i = p.LastIndexOf('/');
            return i >= 0 ? p.Substring(i + 1) : p;
        }

        static string CommonPrefix(List<string> l)
        {
            if (l.Count == 0) return "";
            string a = l[0];
            int n = a.Length;
            foreach (var s in l)
            {
                int i = 0;
                while (i < n && i < s.Length && s[i] == a[i]) i++;
                n = i;
            }
            return a.Substring(0, n);
        }

        static string Rev(string s)
        {
            char[] c = s.ToCharArray();
            Array.Reverse(c);
            return new string(c);
        }

        /// <summary>'flame0.tga'..'flame7.tga' -> 'flame%d.tga' (PT 'animN:' naming).</summary>
        public string AnimPattern()
        {
            if (AnimTextures.Count == 0) return "";
            var names = new List<string>();
            foreach (var t in AnimTextures) names.Add(BaseName(t.name));
            if (names.Count == 1) return names[0];
            string pre = CommonPrefix(names);
            var rev = new List<string>();
            foreach (var s in names) rev.Add(Rev(s));
            string suf = Rev(CommonPrefix(rev));
            while (pre.Length > 0 && char.IsDigit(pre[pre.Length - 1])) pre = pre.Substring(0, pre.Length - 1);
            while (suf.Length > 0 && char.IsDigit(suf[0])) suf = suf.Substring(1);
            return pre + "%d" + suf;
        }

        /// <summary>Material name carrying PT's keyword flags.</summary>
        public string PtName()
        {
            string s = string.Concat(Flags);
            if ((UseState & 0x4000) != 0 && WindBottom >= 10 && WindBottom <= 16)
                s += "BLINK_TIME" + (WindBottom - 8).ToString(System.Globalization.CultureInfo.InvariantCulture) + ":";   // (BLINK_TIME1 = 9 is the default)
            if (BlendNames.TryGetValue(BlendType, out string bn)) s += bn;
            if (TextureType == 1 && AnimCount != 0)
                s = string.Format("anim{0}:{1}:{2}", AnimCount, AnimPattern(), AnimSpeedShift) + (s.Length > 0 ? ":" + s : "");
            return s;
        }

        public string LayerMapName(int layer)
        {
            string s = StageStateNames.TryGetValue(StageState[layer], out string n) ? n : "";
            int fs = FormState[layer];
            if (fs > 0 && fs < FormStateNames.Length) s += FormStateNames[fs];
            return s;
        }
    }
}
