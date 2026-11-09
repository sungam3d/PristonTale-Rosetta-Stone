// Priston Tale texture header de-obfuscation.
//   BMP: 'A8' magic instead of 'BM', then byte[i] += i*i for i in 2..13
//   TGA: 'G8' magic instead of the (zero) id-length/colormap bytes,
//        then byte[i] += i*i for i in 2..17 (the whole 18-byte header)
// Everything after the header is untouched.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace PTSmd
{
    public static class Textures
    {
        public enum Kind { Unchanged, Bmp, Tga }

        public static Kind Decode(byte[] data)
        {
            if (data.Length < 18) return Kind.Unchanged;
            if (data[0] == 'A' && data[1] == '8')
            {
                data[0] = (byte)'B'; data[1] = (byte)'M';
                for (int i = 2; i < 14; i++) data[i] = (byte)(data[i] - i * i);
                // scrambled twice (StartImage\...\Mokoba.BMP): the pixel offset points past the end
                // once undone; twice, size and offset are right
                if (!BmpHeaderOk(data, 0, data.Length))
                {
                    var twice = new byte[14];
                    for (int i = 2; i < 14; i++) twice[i] = (byte)(data[i] - i * i);
                    if (BmpHeaderOk(twice, 0, data.Length) && BitConverter.ToUInt32(twice, 2) == data.Length)
                        Buffer.BlockCopy(twice, 2, data, 2, 12);
                }
                return Kind.Bmp;
            }
            if (data[0] == 'G' && data[1] == '8')
            {
                data[0] = 0; data[1] = 0;
                for (int i = 2; i < 18; i++) data[i] = (byte)(data[i] - i * i);
                // some client TGAs were scrambled twice (Field\castle, Fall_Game, Iron): once
                // undone they still have no sane header, twice they do
                if (!TgaHeaderOk(data, 0, data.Length))
                {
                    var twice = new byte[18];
                    for (int i = 2; i < 18; i++) twice[i] = (byte)(data[i] - i * i);
                    if (TgaHeaderOk(twice, 0, data.Length)) Buffer.BlockCopy(twice, 2, data, 2, 16);
                }
                return Kind.Tga;
            }
            if (data[0] == 'B' && data[1] == 'M')
            {
                // already plain: normalise a garbage bfSize left by third-party decoders
                int size = data.Length;
                data[2] = (byte)size; data[3] = (byte)(size >> 8); data[4] = (byte)(size >> 16); data[5] = (byte)(size >> 24);
                return Kind.Bmp;
            }
            return Kind.Unchanged;
        }

        /// <summary>A TGA header (18 bytes at off) that a reader can use: a known image type, a
        /// usual pixel size, and (uncompressed) pixels that fit in a file of fileLen bytes.</summary>
        public static bool TgaHeaderOk(byte[] h, int off, long fileLen)
        {
            int idLen = h[off], cmap = h[off + 1], type = h[off + 2];
            int w = h[off + 12] | h[off + 13] << 8, ht = h[off + 14] | h[off + 15] << 8, bpp = h[off + 16];
            if (cmap > 1 || !(type == 1 || type == 2 || type == 3 || type == 9 || type == 10 || type == 11)) return false;
            if (w == 0 || ht == 0 || !(bpp == 8 || bpp == 15 || bpp == 16 || bpp == 24 || bpp == 32)) return false;
            if ((type == 2 || type == 3) && 18L + idLen + (long)w * ht * ((bpp + 7) / 8) > fileLen) return false;
            return true;
        }

        /// <summary>A BMP file header (14 bytes at off) whose pixel offset lies inside a file of fileLen bytes.</summary>
        public static bool BmpHeaderOk(byte[] h, int off, long fileLen)
        {
            uint pix = BitConverter.ToUInt32(h, off + 10);
            return pix >= 26 && pix < fileLen;
        }

        /// <summary>Scramble a plain BMP/TGA the way the game client ships them (inverse of Decode).</summary>
        public static Kind Encode(byte[] data)
        {
            if (data.Length < 18) return Kind.Unchanged;
            if (data[0] == 'B' && data[1] == 'M')
            {
                data[0] = (byte)'A'; data[1] = (byte)'8';
                for (int i = 2; i < 14; i++) data[i] = (byte)(data[i] + i * i);
                return Kind.Bmp;
            }
            if (data[0] == 0 && data[1] == 0 && (data[2] == 2 || data[2] == 3 || data[2] == 10 || data[2] == 11))
            {
                data[0] = (byte)'G'; data[1] = (byte)'8';
                for (int i = 2; i < 18; i++) data[i] = (byte)(data[i] + i * i);
                return Kind.Tga;
            }
            return Kind.Unchanged;       // already scrambled or not a BMP/TGA
        }

        /// <summary>Encode every .bmp/.tga under a folder in place (ForGame). Returns (encoded, skipped).</summary>
        public static (int encoded, int skipped) EncodeFolder(string dir, Action<string> log = null)
        {
            int enc = 0, skip = 0;
            foreach (var f in Directory.EnumerateFiles(dir, "*.*", SearchOption.AllDirectories))
            {
                string ext = Path.GetExtension(f).ToLowerInvariant();
                if (ext != ".bmp" && ext != ".tga") continue;
                byte[] d = File.ReadAllBytes(f);
                var notes = new List<string>();
                byte[] o = ForGame(d, notes);
                foreach (var n in notes) log?.Invoke(f + ": " + n);
                if (o.Length == d.Length && o.SequenceEqual(d)) { skip++; continue; }
                File.WriteAllBytes(f, o);
                enc++;
            }
            return (enc, skip);
        }

        // ------------------------------------------------------------------ edited textures -> game
        static void Put32(byte[] b, int o, int v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }

        /// <summary>An edited BMP / TGA in the form the game's loaders read (smTexture.cpp LoadDib,
        /// cTGA::LoadTga), scrambled like the client's own files.  What can be put right without
        /// changing the picture is: RLE-packed TGAs are unpacked, a TGA image ID / colour map is left
        /// out, grey TGAs become colour, top-down BMPs are flipped, BMP pixels are moved right behind
        /// the header and palette (the game ignores bfOffBits) and bfSize is set (the game reads that
        /// many bytes).  notes gets what was changed, or why the game will not show the picture.
        /// Files already in the game's form ('A8' / 'G8') come back unchanged.</summary>
        public static byte[] ForGame(byte[] data, List<string> notes)
        {
            if (data.Length >= 2 && ((data[0] == 'A' && data[1] == '8') || (data[0] == 'G' && data[1] == '8'))) return data;
            if (data.Length >= 26 && data[0] == 'B' && data[1] == 'M') return BmpForGame((byte[])data.Clone(), notes);
            if (data.Length >= 18 && data[1] <= 1 && TgaHeaderOk(data, 0, long.MaxValue)) return TgaForGame(data, notes);
            notes.Add(L.T("tex.unknown"));
            return data;
        }

        static byte[] BmpForGame(byte[] d, List<string> notes)
        {
            int off = BitConverter.ToInt32(d, 10), hdr = BitConverter.ToInt32(d, 14);
            if (hdr >= 40 && d.Length >= 54)
            {
                int w = BitConverter.ToInt32(d, 18), h = BitConverter.ToInt32(d, 22);
                int bpp = BitConverter.ToUInt16(d, 28), comp = BitConverter.ToInt32(d, 30), used = BitConverter.ToInt32(d, 46);
                int masks = 0;
                if (comp == 3 && bpp == 32)
                {
                    // BI_BITFIELDS: fine when the masks are the plain B,G,R byte order (they sit at
                    // offset 54: inside a V2+ header, or right after a 40-byte one)
                    bool plain = d.Length >= 66 && BitConverter.ToUInt32(d, 54) == 0x00FF0000 &&
                                 BitConverter.ToUInt32(d, 58) == 0x0000FF00 && BitConverter.ToUInt32(d, 62) == 0x000000FF;
                    if (plain) { comp = 0; Put32(d, 30, 0); if (hdr == 40) masks = 12; }
                }
                if (!(bpp == 8 || bpp == 24 || bpp == 32))
                    notes.Add(L.T("tex.bmp_bits", bpp));
                else if (comp != 0)
                    notes.Add(L.T("tex.bmp_compressed"));
                else
                {
                    int pal = bpp == 8 ? (used > 0 && used <= 256 ? used : 256) * 4 : 0;
                    int want = 14 + hdr + pal;
                    int rows = Math.Abs(h);
                    long stride = ((long)w * bpp + 31) / 32 * 4, pix = stride * rows;
                    if (w <= 0 || rows == 0 || off < 14 + hdr + masks || off + pix > d.Length)
                        notes.Add(L.T("tex.bmp_damaged"));
                    else if (off != want || h < 0)
                    {
                        var o = new byte[want + pix];
                        Buffer.BlockCopy(d, 0, o, 0, 14 + hdr);
                        if (pal > 0) Buffer.BlockCopy(d, 14 + hdr + masks, o, 14 + hdr, (int)Math.Min(pal, off - 14 - hdr - masks));
                        for (int r = 0; r < rows; r++)
                            Buffer.BlockCopy(d, (int)(off + (h < 0 ? rows - 1 - r : r) * stride), o, (int)(want + r * stride), (int)stride);
                        if (h < 0) { Put32(o, 22, rows); notes.Add(L.T("tex.bmp_flipped")); }
                        if (off != want) notes.Add(L.T("tex.bmp_moved"));
                        Put32(o, 10, want);
                        d = o;
                    }
                }
            }
            Put32(d, 2, d.Length);                                   // the game reads bfSize bytes
            Encode(d);
            return d;
        }

        static byte[] TgaForGame(byte[] d, List<string> notes)
        {
            int idLen = d[0], cmap = d[1], type = d[2];
            int w = d[12] | d[13] << 8, h = d[14] | d[15] << 8, bpp = d[16];
            if (type == 1 || type == 9)
            {
                notes.Add(L.T("tex.tga_cmap"));
                return d;
            }
            int px = (bpp + 7) / 8;
            int cmapLen = cmap == 1 ? (d[5] | d[6] << 8) * ((d[7] + 7) / 8) : 0;
            int start = 18 + idLen + cmapLen;
            long n = (long)w * h;
            bool rle = type == 10 || type == 11, gray = type == 3 || type == 11;
            if (!rle && !gray && idLen == 0 && cmapLen == 0)
            {
                if (bpp != 16 && bpp != 24 && bpp != 32) notes.Add(L.T("tex.tga_bits", bpp));
                var e = (byte[])d.Clone();
                Encode(e);
                return e;
            }
            byte[] pix;
            if (rle)
            {
                pix = Unrle(d, start, n, px);
                if (pix == null) { notes.Add(L.T("tex.tga_rle_damaged")); return d; }
                notes.Add(L.T("tex.tga_rle"));
            }
            else
            {
                if (start + n * px > d.Length) { notes.Add(L.T("tex.tga_damaged")); return d; }
                pix = new byte[n * px];
                Buffer.BlockCopy(d, start, pix, 0, pix.Length);
            }
            if (idLen > 0 || cmapLen > 0) notes.Add(L.T("tex.tga_id"));
            int obpp = bpp;
            if (gray)
            {
                if (bpp == 8 || bpp == 16)
                {
                    obpp = bpp == 8 ? 24 : 32;
                    int op = obpp / 8;
                    var c = new byte[n * op];
                    for (long i = 0; i < n; i++)
                    {
                        byte g = pix[i * px];
                        c[i * op] = g; c[i * op + 1] = g; c[i * op + 2] = g;
                        if (op == 4) c[i * op + 3] = pix[i * px + 1];
                    }
                    pix = c;
                    notes.Add(L.T("tex.tga_grey"));
                }
                else notes.Add(L.T("tex.tga_grey_bits", bpp));
            }
            else if (bpp != 16 && bpp != 24 && bpp != 32) notes.Add(L.T("tex.tga_bits", bpp));
            var o = new byte[18 + pix.Length];
            Buffer.BlockCopy(d, 8, o, 8, 8);                         // origin, width, height
            o[2] = 2;
            o[16] = (byte)obpp;
            o[17] = (byte)((d[17] & 0x30) | (obpp != bpp ? (obpp == 32 ? 8 : 0) : d[17] & 0x0F));   // origin bits + alpha bits
            Buffer.BlockCopy(pix, 0, o, 18, pix.Length);
            Encode(o);
            return o;
        }

        /// <summary>Unpack TGA run-length data: count pixels of px bytes from pos, or null if it runs out.</summary>
        static byte[] Unrle(byte[] d, int pos, long count, int px)
        {
            var o = new byte[count * px];
            long i = 0;
            while (i < count)
            {
                if (pos >= d.Length) return null;
                int c = d[pos++], n = (c & 0x7F) + 1;
                if ((c & 0x80) != 0)
                {
                    if (pos + px > d.Length) return null;
                    for (int k = 0; k < n && i < count; k++, i++) Buffer.BlockCopy(d, pos, o, (int)(i * px), px);
                    pos += px;
                }
                else
                    for (int k = 0; k < n && i < count; k++, i++)
                    {
                        if (pos + px > d.Length) return null;
                        Buffer.BlockCopy(d, pos, o, (int)(i * px), px);
                        pos += px;
                    }
            }
            return o;
        }

        /// <summary>Decode src to dst unless a copy is already there.  A copy is written again only
        /// when the game file is newer, or when it is a TGA an older version of this tool could not
        /// decode (twice-scrambled ones): copies you edited stay as they are.</summary>
        public static void DecodeIfNeeded(string src, string dst)
        {
            try
            {
                if (File.Exists(dst) && File.GetLastWriteTimeUtc(src) <= File.GetLastWriteTimeUtc(dst) && !Unreadable(dst)) return;
            }
            catch (Exception) { return; }
            DecodeFile(src, dst);
        }

        /// <summary>A decoded copy no reader can open (a twice-scrambled file decoded once).</summary>
        static bool Unreadable(string path)
        {
            var h = new byte[18];
            using (var f = File.OpenRead(path))
            {
                if (f.Read(h, 0, 18) < 18) return false;
                if (h[0] == 'B' && h[1] == 'M') return !BmpHeaderOk(h, 0, f.Length);
                if (path.EndsWith(".tga", StringComparison.OrdinalIgnoreCase)) return !TgaHeaderOk(h, 0, f.Length);
                return false;
            }
        }

        public static Kind DecodeFile(string src, string dst)
        {
            byte[] data = File.ReadAllBytes(src);
            Kind k = Decode(data);
            string d = Path.GetDirectoryName(dst);
            if (!string.IsNullOrEmpty(d)) Directory.CreateDirectory(d);
            File.WriteAllBytes(dst, data);
            return k;
        }

        static readonly Dictionary<string, Dictionary<string, string>> dirCache =
            new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);

        static Dictionary<string, string> ListDir(string dir)
        {
            string key = Path.GetFullPath(dir);
            lock (dirCache)
            {
                if (!dirCache.TryGetValue(key, out var d))
                {
                    d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    try
                    {
                        foreach (var e in Directory.EnumerateFileSystemEntries(dir))
                        {
                            string n = Path.GetFileName(e);
                            if (!d.ContainsKey(n)) d[n] = n;
                        }
                    }
                    catch (Exception) { }
                    dirCache[key] = d;
                }
                return d;
            }
        }

        public static void ClearCache()
        {
            lock (dirCache) dirCache.Clear();
        }

        /// <summary>Find root/rel on disk ignoring case and trying .bmp/.tga swaps. Null if absent.</summary>
        public static string Resolve(string root, string rel)
        {
            rel = rel.Replace('\\', '/').Trim('/');
            if (rel.Length == 0) return null;
            string[] parts = rel.Split('/');
            string cur = root;
            for (int i = 0; i < parts.Length; i++)
            {
                var entries = ListDir(cur);
                bool last = i == parts.Length - 1;
                entries.TryGetValue(parts[i], out string name);
                if (name == null && last)
                {
                    string stem = Path.GetFileNameWithoutExtension(parts[i]);
                    foreach (string alt in new[] { ".bmp", ".tga", ".png", ".jpg", ".dds" })
                        if (entries.TryGetValue(stem + alt, out name)) break;
                }
                if (name == null) return null;
                cur = Path.Combine(cur, name);
            }
            return File.Exists(cur) ? cur : null;
        }
    }
}
