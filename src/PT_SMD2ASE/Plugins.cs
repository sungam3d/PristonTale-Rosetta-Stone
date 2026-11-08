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
using System.Text.RegularExpressions;
using Microsoft.Win32;

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
        internal string SystemStartup, UserStartup;

        public string Name => App + " " + Version;

        public string StatusText
        {
            get
            {
                if (!Supported) return App == "Blender" ? "too old for the add-on (needs Blender 4.2 or newer)" : "too old for the plug-in (needs 3ds Max 2020 or newer)";
                if (!Installed) return "plug-in not installed";
                if (UpToDate) return "plug-in installed, up to date" + (InstalledVersion != null ? " (" + InstalledVersion + ")" : "");
                return "older plug-in installed" + (InstalledVersion != null ? " (" + InstalledVersion + ")" : "") + " - update available";
            }
        }
    }

    public static class Plugins
    {
        public static readonly string[] MaxFiles = { "PT_ASE_Importer.ms", "PT_ASE_Exporter.ms", "PT_ASE_Reader.cs", "PT_ASE_Skin.cs" };
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
                        var t = new PluginTarget
                        {
                            App = "3ds Max", Version = year.ToString(), Exe = Path.Combine(dir, "3dsmax.exe"),
                            Supported = year >= 2020,
                            SystemStartup = Path.Combine(dir, "scripts", "startup"),
                            UserStartup = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                                       "Autodesk", "3dsMax", year + " - 64bit", lang, "scripts", "startup"),
                        };
                        CheckMax(t);
                        found.Add(t);
                    }
                }
            }
            return found.OrderBy(t => t.Version);
        }

        static void CheckMax(PluginTarget t)
        {
            string src = MaxSource;
            bool inSystem = File.Exists(Path.Combine(t.SystemStartup, MaxFiles[0]));
            bool inUser = File.Exists(Path.Combine(t.UserStartup, MaxFiles[0]));
            t.Installed = inSystem || inUser;
            t.Where = inSystem ? t.SystemStartup : t.UserStartup;
            t.UpToDate = t.Installed && src != null &&
                         (!inSystem || MaxFiles.All(f => SameFile(Path.Combine(src, f), Path.Combine(t.SystemStartup, f)))) &&
                         (!inUser || MaxFiles.All(f => SameFile(Path.Combine(src, f), Path.Combine(t.UserStartup, f))));
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
                    t.UpToDate = want != null && t.InstalledVersion == want;
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
            if (src == null) return (false, "The 3dsMax plug-in files were not found next to PT_SMD2ASE.exe (3dsMax folder).");
            var targets = new List<string>();
            if (File.Exists(Path.Combine(t.SystemStartup, MaxFiles[0]))) targets.Add(t.SystemStartup);   // update the old copy where it is
            if (File.Exists(Path.Combine(t.UserStartup, MaxFiles[0])) || targets.Count == 0) targets.Add(t.UserStartup);
            foreach (var dir in targets)
            {
                try
                {
                    Directory.CreateDirectory(dir);
                    foreach (var f in MaxFiles) File.Copy(Path.Combine(src, f), Path.Combine(dir, f), true);
                }
                catch (UnauthorizedAccessException)
                {
                    // Max's own folder is under Program Files: copy with administrator rights
                    string cmd = string.Join(" & ", MaxFiles.Select(f => "copy /y \"" + Path.Combine(src, f) + "\" \"" + Path.Combine(dir, f) + "\""));
                    try
                    {
                        var p = Process.Start(new ProcessStartInfo("cmd.exe", "/c " + cmd)
                        { UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden });
                        p?.WaitForExit(60000);
                    }
                    catch (System.ComponentModel.Win32Exception)
                    {
                        return (false, t.Name + ": permission was refused - copy the 4 files from the 3dsMax folder into " + dir + " yourself.");
                    }
                }
                catch (Exception e) { return (false, t.Name + ": " + e.Message); }
            }
            CheckMax(t);
            if (!t.UpToDate) return (false, t.Name + ": the files could not be copied to " + string.Join(" and ", targets) + ".");
            string after = Running("3dsmax") ? " Restart 3ds Max to load it." : " Start 3ds Max: the PT Tools are under Customize → Customize User Interface → Toolbars → Category \"PT Tools\".";
            return (true, t.Name + ": plug-in installed in " + string.Join(" and ", targets) + "." + after);
        }

        static (bool, string) InstallBlender(PluginTarget t)
        {
            string zip = BlenderZip;
            if (zip == null) return (false, "Blender\\" + BlenderZipName + " was not found next to PT_SMD2ASE.exe.");
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
                    if (!p.WaitForExit(180000)) { try { p.Kill(); } catch (Exception) { } return (false, t.Name + ": Blender did not finish installing in 3 minutes."); }
                    output += err.Result;
                    code = p.ExitCode;
                }
            }
            catch (Exception e) { return (false, t.Name + ": could not run Blender - " + e.Message); }
            string status = output.Split('\n').Select(l => l.Trim()).LastOrDefault(l => l.StartsWith("STATUS") || l.StartsWith("ERROR") || l.StartsWith("FATAL")) ?? "";
            var before = t.InstalledVersion;
            var fresh = FindBlender().FirstOrDefault(x => string.Equals(x.Exe, t.Exe, StringComparison.OrdinalIgnoreCase));
            if (fresh != null) { t.Installed = fresh.Installed; t.UpToDate = fresh.UpToDate; t.InstalledVersion = fresh.InstalledVersion; }
            if (code != 0 || !t.Installed)
                return (false, t.Name + ": install failed" + (status.Length > 0 ? " - " + status : " (exit code " + code + ")") +
                               ". Install Blender\\" + BlenderZipName + " with Edit → Preferences → Get Extensions → Install from Disk.");
            string after = Running("blender") ? " Restart Blender to load it." : "";
            return (true, t.Name + ": add-on " + (before != null ? "updated" : "installed") + " and enabled (File → Import → Priston Tale / 3ds Max ASE)." + after);
        }
    }
}
