using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace PT_SMD2ASE
{
    static class Program
    {
        [STAThread]
        static void Main(string[] args)
        {
#if NETFRAMEWORK
            SetProcessDPIAware();
#else
            Application.SetHighDpiMode(HighDpiMode.SystemAware);
#endif
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            if (args.Length >= 5 && args[0] == "--selftest")
            {
                SelfTest(args[1], args[2], args[3], args[4], args.Length > 5 ? args[5] : null, args.Length > 6 ? args[6] : null);
                return;
            }
            if (args.Length >= 3 && args[0] == "--langshot")
            {
                LangShot(args[1], args[2], args.Length > 3 ? args[3] : null);
                return;
            }
            // files/folders dropped onto the exe icon arrive as arguments
            var paths = args.Where(a => File.Exists(a) || Directory.Exists(a)).ToArray();
            while (true)
            {
                var lang = Settings.Load().Lang;
                PTSmd.L.Set(string.IsNullOrEmpty(lang) ? PTSmd.L.SystemDefault : lang);
                var f = new MainForm(paths);
                Application.Run(f);
                if (!f.RestartForLanguage) break;            // (the language was changed: open the window again in it)
                paths = new string[0];
            }
        }

        /// <summary>A screenshot of the window in one language (optionally with something dropped on DECODE,
        /// without converting it): for checking that every language fits.</summary>
        static void LangShot(string code, string png, string input)
        {
            MainForm.QuietForTests = true;
            PTSmd.L.Set(code);
            var f = new MainForm(null) { NoSaveForTests = true };
            var timer = new Timer { Interval = 2500 };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                if (input != null) f.TestShowOnly(new[] { input });
                Application.DoEvents();
                using (var bmp = new Bitmap(f.Width, f.Height))
                {
                    f.DrawToBitmap(bmp, new Rectangle(0, 0, f.Width, f.Height));
                    bmp.Save(png, ImageFormat.Png);
                }
                f.Close();
            };
            f.Shown += (s, e) => timer.Start();
            Application.Run(f);
        }

#if NETFRAMEWORK
        [System.Runtime.InteropServices.DllImport("user32.dll")]
        static extern bool SetProcessDPIAware();
#endif

        /// <summary>Drives the real window: folder (warning + gating), then a single file, then (optional) a
        /// whole game folder. Screenshots to shotDir.</summary>
        static void SelfTest(string outDir, string folder, string file, string shotDir, string client, string encodeDir)
        {
            MainForm.QuietForTests = true;
            var f = new MainForm(null);
            var report = new System.Text.StringBuilder();
            int step = 0;
            var timer = new Timer { Interval = 400 };
            void Shot(string name)
            {
                using (var bmp = new Bitmap(f.Width, f.Height))
                {
                    f.DrawToBitmap(bmp, new Rectangle(0, 0, f.Width, f.Height));
                    bmp.Save(Path.Combine(shotDir, name), ImageFormat.Png);
                }
            }
            timer.Tick += (s, e) =>
            {
                switch (step)
                {
                    case 0: f.TestSetOut(outDir); Shot("cs_gui_0_start.png"); f.TestInput(new[] { folder }); step++; break;
                    case 1:
                        report.AppendLine("folder: whole=" + f.TestWhole + " warning=" + f.TestWarningVisible + " convertEnabled=" + f.TestConvertEnabled);
                        f.TestConvert();                                            // must be ignored (not ticked)
                        report.AppendLine("convert before tick started=" + f.TestBusy);
                        Shot("cs_gui_1_warning.png");
                        f.TestTick();
                        report.AppendLine("after tick convertEnabled=" + f.TestConvertEnabled);
                        f.TestConvert();
                        step++;
                        break;
                    case 2:
                        if (f.TestBusy) break;
                        report.AppendLine("folder done: " + f.TestStatus);
                        Shot("cs_gui_2_done.png");
                        f.TestInput(new[] { file });                                // single file converts immediately
                        step++;
                        break;
                    case 3:
                        if (f.TestBusy) break;
                        report.AppendLine("single file: warning=" + f.TestWarningVisible + " status=" + f.TestStatus);
                        Shot("cs_gui_3_single.png");
                        if (client != null) { f.TestInput(new[] { client }); step++; break; }
                        step = 8;
                        goto case 8;
                    case 4:
                        report.AppendLine("game folder: whole=" + f.TestWhole + " warning=" + f.TestWarningVisible + " convertEnabled=" + f.TestConvertEnabled);
                        Shot("cs_gui_4_client.png");
                        f.TestTick();
                        f.TestConvert();
                        step++;
                        break;
                    case 5:
                        if (f.TestBusy) break;
                        report.AppendLine("game folder done: " + f.TestStatus);
                        Shot("cs_gui_5_client_done.png");
                        f.TestEncode(new[] { encodeDir ?? outDir });                           // the readable copies back to game format
                        step++;
                        break;
                    case 6:
                        if (f.TestBusy) break;
                        report.AppendLine("encode done: " + f.TestStatus);
                        Shot("cs_gui_6_encode_done.png");
                        step = 8;
                        goto case 8;
                    case 8:
                        File.WriteAllText(Path.Combine(shotDir, "cs_gui_selftest.txt"), report.ToString());
                        timer.Stop();
                        f.Close();
                        break;
                }
            };
            f.Shown += (s, e) => timer.Start();
            Application.Run(f);
        }
    }
}
