// Finds 3ds Max and Blender on this PC and installs / updates the PT ASE plug-ins in them.
//
//   3ds Max   HKLM\SOFTWARE\Autodesk\3dsMax\<n>.0  (Installdir; year = 1998 + n).  The four files
//             go to the user's own startup scripts folder
//               %LOCALAPPDATA%\Autodesk\3dsMax\<year> - 64bit\<lang>\scripts\startup
//             (no administrator rights needed).  An older copy in Max's own scripts\startup folder
//             is updated where it is instead (Windows asks for permission), so it isn't loaded twice.
//   Blender   4.2 or newer (extensions), found in Program Files, the uninstall list and Steam.
//             Installed with Blender itself:  blender -c extension install-file -r user_default -e <zip>
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.Win32;
using PTSmd;

namespace PT_SMD2ASE
{
    public sealed class PluginTarget
    {
        public string App;            // "3ds Max" / "Blender"
        public string Version;        // "2020" / "5.2"
        public string Exe;
        public bool Supported = true; // Max 2020+, Blender 4.2+
        public bool Installed, UpToDate;
        public string Where;          // where the plug-in is (or would go)
        public string InstalledVersion;
        internal string SystemStartup, UserStartup;      // UserStartup: the default language's
        internal List<string> UserStartups = new List<string>();   // every language folder Max made (UserStartup first)

        public string Name => App + " " + Version;

        public string StatusText
        {
            get
            {
                if (!Supported) return L.T(App == "Blender" ? "plug.too_old_blender" : "plug.too_old_max");
                if (!Installed) return L.T("plug.not_installed");
                return L.T(UpToDate ? "plug.up_to_date" : "plug.older", "");   // (no version numbers: they only confuse)
            }
        }
    }

    public static class Plugins
    {
        public static readonly string[] MaxFiles = { "PT_ASE_Importer.ms", "PT_ASE_Exporter.ms", "PT_ASE_Reader.cs", "PT_ASE_Skin.cs" };
        const string MaxConfig = "PT_ASE_Config.ms";
        const string BlenderZipName = "pt_ase_importer.zip";
        const string BlenderExtId = "pt_ase_smd_importer";

        // ------------------------------------------------------------------ the plug-in files
        /// <summary>The release's 3dsMax\ folder (next to the exe), or tools\max in a source checkout.</summary>
        public static string MaxSource => FindUp(new[] { "3dsMax", Path.Combine("tools", "max") }, MaxFiles[0]);

        /// <summary>The release's Blender\pt_ase_importer.zip, or tools\dist in a source checkout.</summary>
        public static string BlenderZip
        {
            get
            {
                string d = FindUp(new[] { "Blender", Path.Combine("tools", "dist") }, BlenderZipName);
                return d != null ? Path.Combine(d, BlenderZipName) : null;
            }
        }

        static string FindUp(string[] subs, string file)
        {
            string d = Path.GetDirectoryName(typeof(Plugins).Assembly.Location);
            for (int up = 0; up < 8 && d != null; up++, d = Path.GetDirectoryName(d.TrimEnd('\\')))
                foreach (var s in subs)
                    if (File.Exists(Path.Combine(d, s, file))) return Path.Combine(d, s);
            return null;
        }

        static bool SameFile(string a, string b)
        {
            try
            {
                if (!File.Exists(a) || !File.Exists(b)) return false;
                var x = File.ReadAllBytes(a);
                var y = File.ReadAllBytes(b);
                return x.Length == y.Length && x.SequenceEqual(y);
            }
            catch (Exception) { return false; }
        }

        static string ManifestVersion(string toml)
        {
            var m = Regex.Match(toml ?? "", @"^\s*version\s*=\s*""([^""]+)""", RegexOptions.Multiline);
            return m.Success ? m.Groups[1].Value : null;
        }

        /// <summary>The add-on version inside the bundled zip.</summary>
        public static string BundledBlenderVersion
        {
            get
            {
                try
                {
                    using (var z = new ZipArchive(File.OpenRead(BlenderZip), ZipArchiveMode.Read))
                    {
                        var e = z.Entries.FirstOrDefault(x => x.Name == "blender_manifest.toml");
                        if (e == null) return null;
                        using (var r = new StreamReader(e.Open())) return ManifestVersion(r.ReadToEnd());
                    }
                }
                catch (Exception) { return null; }
            }
        }

        /// <summary>Every file of the bundled zip is in folder with the same bytes (so an add-on that
        /// changed without a new version number is still offered as an update).</summary>
        static bool SameAsBundled(string folder)
        {
            try
            {
                using (var z = new ZipArchive(File.OpenRead(BlenderZip), ZipArchiveMode.Read))
                    foreach (var e in z.Entries)
                    {
                        if (e.Name.Length == 0) continue;                           // (a folder)
                        string p = Path.Combine(folder, e.FullName.Replace('/', '\\'));
                        if (!File.Exists(p) || new FileInfo(p).Length != e.Length) return false;
                        var a = File.ReadAllBytes(p);
                        var b = new byte[e.Length];
                        using (var s = e.Open())
                        {
                            int n = 0, k;
                            while (n < b.Length && (k = s.Read(b, n, b.Length - n)) > 0) n += k;
                        }
                        if (!a.SequenceEqual(b)) return false;
                    }
                return true;
            }
            catch (Exception) { return false; }
        }

        // ------------------------------------------------------------------ detection
        public static List<PluginTarget> Detect()
        {
            var o = new List<PluginTarget>();
            try { o.AddRange(FindMax()); } catch (Exception) { }
            try { o.AddRange(FindBlender()); } catch (Exception) { }
            return o;
        }

        static IEnumerable<PluginTarget> FindMax()
        {
            var found = new List<PluginTarget>();
            using (var hk = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
            using (var key = hk.OpenSubKey(@"SOFTWARE\Autodesk\3dsMax"))
            {
                if (key == null) return found;
                foreach (var sub in key.GetSubKeyNames())
                {
                    var m = Regex.Match(sub, @"^(\d+)\.0$");
                    if (!m.Success) continue;
                    using (var k = key.OpenSubKey(sub))
                    {
                        string dir = k?.GetValue("Installdir") as string;
                        if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) continue;
                        int year = 1998 + int.Parse(m.Groups[1].Value);
                        string lang = (k.GetValue("DefaultLanguage") as string) ?? "ENU";
                        string userRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                                       "Autodesk", "3dsMax", year + " - 64bit");
                        var t = new PluginTarget
                        {
                            App = "3ds Max", Version = year.ToString(), Exe = Path.Combine(dir, "3dsmax.exe"),
                            Supported = year >= 2020,
                            SystemStartup = Path.Combine(dir, "scripts", "startup"),
                            UserStartup = Path.Combine(userRoot, lang, "scripts", "startup"),
                        };
                        // Max started in another language (its language shortcuts) reads that language's folder
                        t.UserStartups.Add(t.UserStartup);
                        try
                        {
                            foreach (var d in Directory.GetDirectories(userRoot))
                            {
                                string n = Path.GetFileName(d);
                                if (n.Length == 3 && n.All(char.IsLetter) && !n.Equals(lang, StringComparison.OrdinalIgnoreCase))
                                    t.UserStartups.Add(Path.Combine(d, "scripts", "startup"));
                            }
                        }
                        catch (Exception) { }
                        CheckMax(t);
                        found.Add(t);
                    }
                }
            }
            return found.OrderBy(t => t.Version);
        }

        /// <summary>A MAXScript string literal for text.</summary>
        static string MsQuote(string text) =>
            "\"" + text.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", "\\n").Replace("\t", "\\t") + "\"";

        /// <summary>A plug-in file as it is installed: the scripts in the window's language (their English
        /// texts, the max.* keys of the language tables, replaced; UTF-8 with a byte-order mark, which
        /// 3ds Max reads), everything else as it is.</summary>
        public static byte[] MaxFileFor(string src, string file)
        {
            byte[] raw = File.ReadAllBytes(Path.Combine(src, file));
            if (L.Current == "en" || !file.EndsWith(".ms", StringComparison.OrdinalIgnoreCase)) return raw;
            string s = Encoding.UTF8.GetString(raw);
            foreach (var key in L.Keys("en").Where(k => k.StartsWith("max.")))
            {
                string en = L.En(key), tr = L.T(key);
                if (tr != en) s = s.Replace(MsQuote(en), MsQuote(tr));
            }
            var body = Encoding.UTF8.GetBytes(s);
            var o = new byte[body.Length + 3];
            o[0] = 0xEF; o[1] = 0xBB; o[2] = 0xBF;
            Buffer.BlockCopy(body, 0, o, 3, body.Length);
            return o;
        }

        static bool SameAsInstalled(string src, string file, string dir)
        {
            try
            {
                string p = Path.Combine(dir, file);
                return File.Exists(p) && File.ReadAllBytes(p).SequenceEqual(MaxFileFor(src, file));
            }
            catch (Exception) { return false; }
        }

        static void CheckMax(PluginTarget t)
        {
            string src = MaxSource;
            bool inSystem = File.Exists(Path.Combine(t.SystemStartup, MaxFiles[0]));
            var users = t.UserStartups.Where(u => File.Exists(Path.Combine(u, MaxFiles[0]))).ToList();
            t.Installed = inSystem || users.Count > 0;
            t.Where = inSystem ? t.SystemStartup : t.UserStartup;
            // every copy Max may load must be the current one
            t.UpToDate = t.Installed && src != null &&
                         (!inSystem || MaxFiles.All(f => SameAsInstalled(src, f, t.SystemStartup))) &&
                         users.All(u => MaxFiles.All(f => SameAsInstalled(src, f, u)));
        }

        static IEnumerable<PluginTarget> FindBlender()
        {
            var exes = new List<string>();
            foreach (var pf in new[] { Environment.GetEnvironmentVariable("ProgramW6432"), Environment.GetEnvironmentVariable("ProgramFiles"),
                                       Environment.GetEnvironmentVariable("ProgramFiles(x86)") })
            {
                if (string.IsNullOrEmpty(pf)) continue;
                string bf = Path.Combine(pf, "Blender Foundation");
                if (Directory.Exists(bf))
                    foreach (var d in Directory.GetDirectories(bf)) exes.Add(Path.Combine(d, "blender.exe"));
                exes.Add(Path.Combine(pf, "Steam", "steamapps", "common", "Blender", "blender.exe"));
            }
            foreach (var hive in new[] { RegistryHive.LocalMachine, RegistryHive.CurrentUser })
                foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
                    try
                    {
                        using (var hk = RegistryKey.OpenBaseKey(hive, view))
                        using (var un = hk.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"))
                        {
                            if (un == null) continue;
                            foreach (var n in un.GetSubKeyNames())
                                using (var k = un.OpenSubKey(n))
                                {
                                    string name = k?.GetValue("DisplayName") as string;
                                    string loc = k?.GetValue("InstallLocation") as string;
                                    if (name != null && name.StartsWith("Blender", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrEmpty(loc))
                                        exes.Add(Path.Combine(loc, "blender.exe"));
                                }
                        }
                    }
                    catch (Exception) { }
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var found = new List<PluginTarget>();
            string want = BundledBlenderVersion;
            foreach (var exe in exes)
            {
                string full;
                try { full = Path.GetFullPath(exe); } catch (Exception) { continue; }
                if (!File.Exists(full) || !seen.Add(full)) continue;
                var v = BlenderVersion(full);
                if (v == null) continue;
                var t = new PluginTarget { App = "Blender", Version = v.Major + "." + v.Minor, Exe = full, Supported = v >= new Version(4, 2) };
                string ext = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Blender Foundation", "Blender",
                                          t.Version, "extensions", "user_default", BlenderExtId);
                t.Where = ext;
                string manifest = Path.Combine(ext, "blender_manifest.toml");
                if (File.Exists(manifest))
                {
                    t.Installed = true;
                    try { t.InstalledVersion = ManifestVersion(File.ReadAllText(manifest)); } catch (Exception) { }
                    t.UpToDate = want != null && t.InstalledVersion == want && SameAsBundled(ext);
                }
                found.Add(t);
            }
            return found.OrderBy(t => new Version(t.Version));
        }

        static Version BlenderVersion(string exe)
        {
            try
            {
                var fv = FileVersionInfo.GetVersionInfo(exe);
                var m = Regex.Match(fv.ProductVersion ?? fv.FileVersion ?? "", @"(\d+)\.(\d+)");
                if (!m.Success) m = Regex.Match(Path.GetFileName(Path.GetDirectoryName(exe)) ?? "", @"(\d+)\.(\d+)");
                return m.Success ? new Version(int.Parse(m.Groups[1].Value), int.Parse(m.Groups[2].Value)) : null;
            }
            catch (Exception) { return null; }
        }

        // ------------------------------------------------------------------ install
        /// <summary>Install or update; returns a line for the log (ok, message).</summary>
        public static (bool ok, string message) Install(PluginTarget t)
        {
            if (!t.Supported) return (false, t.Name + ": " + t.StatusText);
            return t.App == "Blender" ? InstallBlender(t) : InstallMax(t);
        }

        static bool Running(string processName) => Process.GetProcessesByName(processName).Length > 0;

        static (bool, string) InstallMax(PluginTarget t)
        {
            string src = MaxSource;
            if (src == null) return (false, L.T("inst.max_missing"));
            var targets = new List<string>();
            bool inSystem = File.Exists(Path.Combine(t.SystemStartup, MaxFiles[0]));
            if (inSystem) targets.Add(t.SystemStartup);                                   // update the old copy where it is
            // the user's own folders: copies already there are updated; without a system copy, every
            // language folder Max made gets one (Max started in that language reads only its own)
            foreach (var u in t.UserStartups)
                if (File.Exists(Path.Combine(u, MaxFiles[0])) || !inSystem) targets.Add(u);
            // the files in the window's language, ready to copy (also for a copy with administrator rights)
            string staged = Path.Combine(Path.GetTempPath(), "pt_max_plugin_" + L.Current);
            var files = MaxFiles.ToList();
            try
            {
                Directory.CreateDirectory(staged);
                foreach (var f in MaxFiles) File.WriteAllBytes(Path.Combine(staged, f), MaxFileFor(src, f));
                // where the converter is, so the plug-in opens game files (.smd, .smb) itself
                string conv = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "smd2ase.exe");
                if (File.Exists(conv))
                {
                    File.WriteAllText(Path.Combine(staged, MaxConfig),
                        "-- written by PT_RosettaStone.exe: its converter, for opening game files in 3ds Max\r\n" +
                        "global PTASE_Converter = @\"" + conv + "\"\r\n", new UTF8Encoding(true));
                    files.Add(MaxConfig);
                }
            }
            catch (Exception e) { return (false, t.Name + ": " + e.Message); }
            foreach (var dir in targets)
            {
                try
                {
                    Directory.CreateDirectory(dir);
                    foreach (var f in files) File.Copy(Path.Combine(staged, f), Path.Combine(dir, f), true);
                }
                catch (UnauthorizedAccessException)
                {
                    // Max's own folder is under Program Files: copy with administrator rights
                    string cmd = string.Join(" & ", files.Select(f => "copy /y \"" + Path.Combine(staged, f) + "\" \"" + Path.Combine(dir, f) + "\""));
                    try
                    {
                        var p = Process.Start(new ProcessStartInfo("cmd.exe", "/c " + cmd)
                        { UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden });
                        p?.WaitForExit(60000);
                    }
                    catch (System.ComponentModel.Win32Exception)
                    {
                        return (false, L.T("inst.refused", t.Name, dir));
                    }
                }
                catch (Exception e) { return (false, t.Name + ": " + e.Message); }
            }
            CheckMax(t);
            if (!t.UpToDate) return (false, L.T("inst.not_copied", t.Name, string.Join(L.T("inst.and"), targets)));
            string after = L.T(Running("3dsmax") ? "inst.max_restart" : "inst.max_start");
            return (true, L.T("inst.max_ok", t.Name, string.Join(L.T("inst.and"), targets)) + after);
        }

        /// <summary>The Blender add-on opens game files (.smd / .smb) with this program's converter: its
        /// path goes to %APPDATA%\PT_SMD2ASE\converter.txt (written on install and at every start, so a
        /// moved program folder is found again).</summary>
        public static void WriteConverterPath()
        {
            try
            {
                string conv = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "smd2ase.exe");
                string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "PT_SMD2ASE");
                string file = Path.Combine(dir, "converter.txt");
                if (!File.Exists(conv)) return;
                if (File.Exists(file) && File.ReadAllText(file).Trim() == conv) return;
                Directory.CreateDirectory(dir);
                File.WriteAllText(file, conv, new UTF8Encoding(false));
            }
            catch (Exception) { }
        }

        static (bool, string) InstallBlender(PluginTarget t)
        {
            string zip = BlenderZip;
            if (zip == null) return (false, L.T("inst.zip_missing", BlenderZipName));
            WriteConverterPath();
            var psi = new ProcessStartInfo(t.Exe, "-c extension install-file -r user_default -e \"" + zip + "\"")
            {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
            };
            string output;
            int code;
            try
            {
                using (var p = Process.Start(psi))
                {
                    var err = p.StandardError.ReadToEndAsync();
                    output = p.StandardOutput.ReadToEnd();
                    if (!p.WaitForExit(180000)) { try { p.Kill(); } catch (Exception) { } return (false, L.T("inst.timeout", t.Name)); }
                    output += err.Result;
                    code = p.ExitCode;
                }
            }
            catch (Exception e) { return (false, L.T("inst.no_run", t.Name, e.Message)); }
            string status = output.Split('\n').Select(l => l.Trim()).LastOrDefault(l => l.StartsWith("STATUS") || l.StartsWith("ERROR") || l.StartsWith("FATAL")) ?? "";
            var before = t.InstalledVersion;
            var fresh = FindBlender().FirstOrDefault(x => string.Equals(x.Exe, t.Exe, StringComparison.OrdinalIgnoreCase));
            if (fresh != null) { t.Installed = fresh.Installed; t.UpToDate = fresh.UpToDate; t.InstalledVersion = fresh.InstalledVersion; }
            if (code != 0 || !t.Installed)
                return (false, L.T("inst.failed", t.Name, status.Length > 0 ? " - " + status : L.T("inst.exit_code", code), BlenderZipName));
            string after = Running("blender") ? L.T("inst.bl_restart") : "";
            return (true, L.T(before != null ? "inst.bl_updated" : "inst.bl_installed", t.Name) + after);
        }
    }
}
