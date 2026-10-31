using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace PT_SMD2ASE
{
    /// <summary>Remembered UI settings (%APPDATA%\PT_SMD2ASE\settings.ini).</summary>
    public class Settings
    {
        public static readonly string DefaultOut =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "PT_ASE_Output");

        static string FilePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "PT_SMD2ASE", "settings.ini");

        public string OutDir = DefaultOut, LastIn = "", Collision = "split";
        public bool Textures = true, VertexColors = true, Lights = true, SplitObjects = true;
        public int What = 0, Width = 780, Height = 700;

        public static Settings Load()
        {
            var s = new Settings();
            try
            {
                if (!File.Exists(FilePath)) return s;
                var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (var line in File.ReadAllLines(FilePath))
                {
                    int i = line.IndexOf('=');
                    if (i > 0) d[line.Substring(0, i).Trim()] = line.Substring(i + 1).Trim();
                }
                string v;
                if (d.TryGetValue("out", out v) && v.Length > 0) s.OutDir = v;
                if (d.TryGetValue("last_in", out v)) s.LastIn = v;
                if (d.TryGetValue("collision", out v)) s.Collision = v;
                if (d.TryGetValue("textures", out v)) s.Textures = v == "1";
                if (d.TryGetValue("vertex_colors", out v)) s.VertexColors = v == "1";
                if (d.TryGetValue("lights", out v)) s.Lights = v == "1";
                if (d.TryGetValue("split_objects", out v)) s.SplitObjects = v == "1";
                if (d.TryGetValue("what", out v)) int.TryParse(v, out s.What);
                if (d.TryGetValue("width", out v) && int.TryParse(v, out int w) && w >= 640) s.Width = w;
                if (d.TryGetValue("height", out v) && int.TryParse(v, out int h) && h >= 560) s.Height = h;
            }
            catch (Exception) { }
            return s;
        }

        public void Save()
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(FilePath));
                File.WriteAllLines(FilePath, new[]
                {
                    "out=" + OutDir, "last_in=" + LastIn, "collision=" + Collision,
                    "textures=" + (Textures ? 1 : 0), "vertex_colors=" + (VertexColors ? 1 : 0), "lights=" + (Lights ? 1 : 0), "split_objects=" + (SplitObjects ? 1 : 0),
                    "what=" + What.ToString(CultureInfo.InvariantCulture),
                    "width=" + Width.ToString(CultureInfo.InvariantCulture), "height=" + Height.ToString(CultureInfo.InvariantCulture),
                });
            }
            catch (Exception) { }
        }
    }
}
