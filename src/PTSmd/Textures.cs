// Priston Tale texture header de-obfuscation.
//   BMP: 'A8' magic instead of 'BM', then byte[i] += i*i for i in 2..13
//   TGA: 'G8' magic instead of the (zero) id-length/colormap bytes,
//        then byte[i] += i*i for i in 2..17 (the whole 18-byte header)
// Everything after the header is untouched.

using System;
using System.Collections.Generic;
using System.IO;

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
                return Kind.Bmp;
            }
            if (data[0] == 'G' && data[1] == '8')
            {
                data[0] = 0; data[1] = 0;
                for (int i = 2; i < 18; i++) data[i] = (byte)(data[i] - i * i);
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

        /// <summary>Encode every .bmp/.tga under a folder in place. Returns (encoded, skipped).</summary>
        public static (int encoded, int skipped) EncodeFolder(string dir)
        {
            int enc = 0, skip = 0;
            foreach (var f in Directory.EnumerateFiles(dir, "*.*", SearchOption.AllDirectories))
            {
                string ext = Path.GetExtension(f).ToLowerInvariant();
                if (ext != ".bmp" && ext != ".tga") continue;
                byte[] d = File.ReadAllBytes(f);
                if (Encode(d) == Kind.Unchanged) { skip++; continue; }
                File.WriteAllBytes(f, d);
                enc++;
            }
            return (enc, skip);
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
