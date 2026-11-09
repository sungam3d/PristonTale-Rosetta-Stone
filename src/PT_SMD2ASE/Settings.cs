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
        public bool ServerCopy = true;          // whole game folder: _server copy of the model info
        public int Width = 800, Height = 860;
        public string Lang = "";                // interface language (L.Languages code); "" = Windows' language
        public int TextCodePage = 949;          // the game client's text code page (model info is always 949)

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
                if (d.TryGetValue("server_copy", out v)) s.ServerCopy = v == "1";
                if (d.TryGetValue("lang", out v)) s.Lang = v;
                if (d.TryGetValue("text_code_page", out v) && int.TryParse(v, out int cp)) s.TextCodePage = cp;
                if (d.TryGetValue("width", out v) && int.TryParse(v, out int w) && w >= 640) s.Width = w;
                if (d.TryGetValue("height", out v) && int.TryParse(v, out int h) && h >= 800) s.Height = h;   // (smaller: saved before the plug-in panel)
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
                    "server_copy=" + (ServerCopy ? 1 : 0), "lang=" + Lang,
                    "text_code_page=" + TextCodePage.ToString(CultureInfo.InvariantCulture),
                    "width=" + Width.ToString(CultureInfo.InvariantCulture), "height=" + Height.ToString(CultureInfo.InvariantCulture),
                });
            }
            catch (Exception) { }
        }
    }
}
