using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using PTSmd;

namespace PT_SMD2ASE
{
    public class MainForm : Form
    {
        const string AppName = "PristonTale - Rosetta Stone";
        // measured (2026-11): maps ~10 MB of .smd a second, characters / monsters ~3; the whole client
        // (876 MB .smd, 2.5 GB textures + sounds) in 6 min 43 s
        const double MbPerSec = 5.0, ModelMbPerSec = 3.0, RestMbPerSec = 25.0;

        readonly Settings st = Settings.Load();
        readonly Label drop, dropEnc;          // decode (game -> readable), encode (readable -> game)
        readonly TextBox outBox;
        readonly CheckBox chkTex, chkVc, chkLights, chkSplit, chkOk;
        readonly RadioButton rbSplit, rbKeep, rbDrop;
        readonly CheckBox chkServer;
        readonly TableLayoutPanel plugRows;
        readonly Panel warn;
        readonly Label warnLbl, status;
        readonly Button btnGo, btnCancel;
        readonly ProgressBar prog;
        readonly RichTextBox log;

        List<string> pending = new List<string>();
        ClientConvert.Scan scan;                // whole game folder mode: what was dropped
        bool needConfirm;
        bool whole;                             // what was dropped needs the whole-folder conversion
        CancellationTokenSource cts;
        Task worker;

        static readonly Color DropBack = Color.FromArgb(238, 243, 251), DropHot = Color.FromArgb(214, 230, 252),
                              EncBack = Color.FromArgb(251, 244, 235), EncHot = Color.FromArgb(252, 230, 206);

        public MainForm(string[] initial)
        {
            Text = AppName + "  v" + Application.ProductVersion;
            Font = new Font("Segoe UI", 9f);
            AutoScaleMode = AutoScaleMode.Font;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
            ClientSize = new Size(st.Width, st.Height);
            MinimumSize = new Size(700, 700);
            StartPosition = FormStartPosition.CenterScreen;
            AllowDrop = true;
            DragEnter += OnDragEnter;
            DragLeave += (s, e) => { drop.BackColor = DropBack; dropEnc.BackColor = EncBack; };
            DragDrop += OnDragDrop;

            var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, Padding = new Padding(10) };
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 200));   // decode / encode drop zones + browse buttons
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // output
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // options
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // plug-ins
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // warning
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // actions
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // progress
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));     // log
            Controls.Add(root);

            // drop zones: decode (left), encode (right), each with its browse buttons
            var zones = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 2, Margin = new Padding(0, 0, 0, 4) };
            zones.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            zones.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            zones.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            zones.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            drop = MakeZone(false);
            dropEnc = MakeZone(true);
            zones.Controls.Add(drop, 0, 0);
            zones.Controls.Add(dropEnc, 1, 0);
            zones.Controls.Add(BrowseRow(false), 0, 1);
            zones.Controls.Add(BrowseRow(true), 1, 1);
            SetDropText(null);
            SetEncText(null);
            root.Controls.Add(zones);

            // output folder
            var outGrp = new GroupBox { Text = "Output folder", Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(6) };
            var outRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, AutoSize = true };
            outRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            outRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            outRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            outBox = new TextBox { Dock = DockStyle.Fill, Text = st.OutDir, Margin = new Padding(3, 5, 3, 3) };
            outRow.Controls.Add(outBox, 0, 0);
            outRow.Controls.Add(MakeButton("Change…", (s, e) => BrowseOut()), 1, 0);
            outRow.Controls.Add(MakeButton("Open", (s, e) => OpenFolder(OutDir)), 2, 0);
            outGrp.Controls.Add(outRow);
            root.Controls.Add(outGrp);

            // options
            var opGrp = new GroupBox { Text = "Options", Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(6) };
            var opt = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, AutoSize = true };
            opt.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            opt.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            chkTex = new CheckBox { Text = "Copy + decrypt textures (the .ase points at the decoded copies)", AutoSize = true, Checked = st.Textures };
            chkVc = new CheckBox { Text = "Baked vertex lighting (game look)", AutoSize = true, Checked = st.VertexColors };
            chkLights = new CheckBox { Text = "Stage lights", AutoSize = true, Checked = st.Lights };
            opt.Controls.Add(chkTex, 0, 0); opt.SetColumnSpan(chkTex, 2);
            opt.Controls.Add(chkVc, 0, 1);
            opt.Controls.Add(chkLights, 1, 1);
            chkSplit = new CheckBox { Text = "Split maps into separate objects (like the original .ase files)", AutoSize = true, Checked = st.SplitObjects };
            opt.Controls.Add(chkSplit, 0, 2); opt.SetColumnSpan(chkSplit, 2);
            opt.Controls.Add(new Label { Text = "Collision walls:", AutoSize = true, Margin = new Padding(3, 7, 3, 3) }, 0, 3);
            var coll = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
            rbSplit = new RadioButton { Text = "separate object", AutoSize = true, Checked = st.Collision == "split" };
            rbKeep = new RadioButton { Text = "keep in mesh", AutoSize = true, Checked = st.Collision == "keep" };
            rbDrop = new RadioButton { Text = "remove", AutoSize = true, Checked = st.Collision == "drop" };
            if (!rbKeep.Checked && !rbDrop.Checked) rbSplit.Checked = true;
            coll.Controls.AddRange(new Control[] { rbSplit, rbKeep, rbDrop });
            opt.Controls.Add(coll, 1, 3);
            chkServer = new CheckBox { Text = "Also save the model info for the server (_server folder, Korean code page)", AutoSize = true, Checked = st.ServerCopy };
            new ToolTip { AutoPopDelay = 20000 }.SetToolTip(chkServer,
                "<output>\\_server holds the model info files (.ini / .inf / .in made from each .inx) again in the game's own\n" +
                "Korean code page: the form the server and the game's tools read.");
            chkServer.CheckedChanged += (s, e) => { if (scan != null && !Busy) ShowSelection(); };
            opt.Controls.Add(chkServer, 0, 4); opt.SetColumnSpan(chkServer, 2);
            opGrp.Controls.Add(opt);
            root.Controls.Add(opGrp);

            // 3ds Max / Blender plug-ins
            var plugGrp = new GroupBox { Text = "3ds Max / Blender plug-ins", Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(6) };
            plugRows = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, AutoSize = true };
            plugRows.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            plugRows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            plugRows.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            plugRows.Controls.Add(new Label { Text = "Looking for 3ds Max and Blender…", AutoSize = true, Margin = new Padding(3, 6, 3, 3) }, 0, 0);
            plugGrp.Controls.Add(plugRows);
            root.Controls.Add(plugGrp);

            // folder warning
            warn = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(255, 244, 206), AutoSize = true,
                               Padding = new Padding(10, 8, 10, 8), Margin = new Padding(3, 6, 3, 6), Visible = false,
                               BorderStyle = BorderStyle.FixedSingle };
            var warnTbl = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, AutoSize = true, BackColor = warn.BackColor };
            warnLbl = new Label { AutoSize = true, ForeColor = Color.FromArgb(92, 68, 0), Font = new Font("Segoe UI", 9.5f),
                                  MaximumSize = new Size(700, 0) };
            chkOk = new CheckBox { Text = "I understand, continue", AutoSize = true, Font = new Font("Segoe UI", 9.5f, FontStyle.Bold),
                                   ForeColor = Color.FromArgb(92, 68, 0), Margin = new Padding(0, 6, 0, 0) };
            chkOk.CheckedChanged += (s, e) => UpdateButtons();
            warnTbl.Controls.Add(warnLbl, 0, 0);
            warnTbl.Controls.Add(chkOk, 0, 1);
            warn.Controls.Add(warnTbl);
            root.Controls.Add(warn);

            // actions
            var act = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
            btnGo = new Button { Text = "Convert", AutoSize = true, Font = new Font("Segoe UI", 10f, FontStyle.Bold),
                                 Padding = new Padding(14, 4, 14, 4), Enabled = false };
            btnGo.Click += (s, e) => Start();
            btnCancel = MakeButton("Cancel", (s, e) => { cts?.Cancel(); status.Text = "Cancelling after the current file…"; });
            btnCancel.Enabled = false;
            btnCancel.Margin = new Padding(8, 8, 3, 3);
            status = new Label { AutoSize = true, Margin = new Padding(12, 12, 3, 3) };
            act.Controls.AddRange(new Control[] { btnGo, btnCancel, status });
            root.Controls.Add(act);

            prog = new ProgressBar { Dock = DockStyle.Fill, Height = 18, Margin = new Padding(3, 3, 3, 6) };
            root.Controls.Add(prog);

            log = new RichTextBox
            {
                Dock = DockStyle.Fill, ReadOnly = true, BackColor = Color.FromArgb(30, 30, 30), ForeColor = Color.FromArgb(212, 212, 212),
                Font = new Font("Consolas", 9f), WordWrap = false, BorderStyle = BorderStyle.None,
            };
            root.Controls.Add(log);

            FormClosing += OnClosing;
            Shown += (s, e) => DetectPlugins();
            if (initial != null && initial.Length > 0)
                Shown += (s, e) => OnInput(initial);
        }

        // ------------------------------------------------------------- plug-ins
        void DetectPlugins()
        {
            Task.Run(() => Plugins.Detect()).ContinueWith(t =>
            {
                if (IsDisposed) return;
                BeginInvoke(new Action(() => ShowPlugins(t.IsFaulted ? new List<PluginTarget>() : t.Result)));
            });
        }

        void ShowPlugins(List<PluginTarget> found)
        {
            plugRows.SuspendLayout();
            plugRows.Controls.Clear();
            plugRows.RowStyles.Clear();
            int row = 0;
            foreach (var app in new[] { "3ds Max", "Blender" })
            {
                var mine = found.Where(f => f.App == app).ToList();
                if (mine.Count == 0)
                {
                    plugRows.Controls.Add(new Label { Text = app, AutoSize = true, Font = new Font(Font, FontStyle.Bold), Margin = new Padding(3, 6, 12, 3) }, 0, row);
                    plugRows.Controls.Add(new Label { Text = "not found on this PC", AutoSize = true, ForeColor = SystemColors.GrayText, Margin = new Padding(3, 6, 3, 3) }, 1, row);
                    row++;
                    continue;
                }
                foreach (var t in mine)
                {
                    var target = t;
                    plugRows.Controls.Add(new Label { Text = t.Name, AutoSize = true, Font = new Font(Font, FontStyle.Bold), Margin = new Padding(3, 6, 12, 3) }, 0, row);
                    var lbl = new Label
                    {
                        Text = t.StatusText, AutoSize = true, Margin = new Padding(3, 6, 3, 3),
                        ForeColor = !t.Supported ? SystemColors.GrayText : t.UpToDate ? Color.FromArgb(30, 120, 40) : Color.FromArgb(160, 90, 0),
                    };
                    plugRows.Controls.Add(lbl, 1, row);
                    if (t.Supported)
                    {
                        var b = MakeButton(t.Installed ? (t.UpToDate ? "Reinstall" : "Update") : "Install", null);
                        b.Click += (s, e) => InstallPlugin(target, b);
                        plugRows.Controls.Add(b, 2, row);
                    }
                    row++;
                }
            }
            plugRows.ResumeLayout();
        }

        void InstallPlugin(PluginTarget t, Button b)
        {
            // a running Blender that saves its preferences on quit would switch the new add-on off again
            if (t.App == "Blender" && Process.GetProcessesByName("blender").Length > 0 && !QuietForTests &&
                MessageBox.Show(this, "Blender is open. Please close it first: when Blender saves its preferences on quit, " +
                                      "it can switch the newly installed add-on off again.\n\nInstall anyway?", AppName,
                                MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
                return;
            b.Enabled = false;
            string was = b.Text;
            b.Text = "Installing…";
            Log("=== Installing the plug-in into " + t.Name + " ===", Head);
            Task.Run(() => Plugins.Install(t)).ContinueWith(task =>
            {
                var r = task.IsFaulted ? (false, t.Name + ": " + task.Exception.GetBaseException().Message) : task.Result;
                BeginInvoke(new Action(() =>
                {
                    Log(r.Item2, r.Item1 ? Ok : Err);
                    b.Text = was;
                    b.Enabled = true;
                    DetectPlugins();
                }));
            });
        }

        static Button MakeButton(string text, EventHandler click)
        {
            var b = new Button { Text = text, AutoSize = true, Padding = new Padding(6, 1, 6, 1) };
            b.Click += click;
            return b;
        }

        Label MakeZone(bool enc)
        {
            var z = new Label
            {
                Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, BackColor = enc ? EncBack : DropBack,
                ForeColor = enc ? Color.FromArgb(122, 70, 20) : Color.FromArgb(43, 74, 122), Font = new Font("Segoe UI", 10.5f),
                BorderStyle = BorderStyle.FixedSingle, Cursor = Cursors.Hand, AllowDrop = true,
                Margin = enc ? new Padding(5, 0, 0, 0) : new Padding(0, 0, 5, 0),
            };
            z.DragEnter += OnDragEnter;
            z.DragLeave += (s, e) => z.BackColor = enc ? EncBack : DropBack;
            z.DragDrop += OnDragDrop;
            z.Click += (s, e) => BrowseFiles(enc);
            new ToolTip { AutoPopDelay = 20000 }.SetToolTip(z, enc
                ? "Edited files back into the forms the game uses:\n.ini / .inf / .in → .inx (+ Korean code page text), " +
                  ".wav → game sound header,\n.bmp / .tga → game texture header, other UTF-8 text → Korean code page.\n" +
                  "Written to <output folder>\\game_format. Keep the game's folder names (char\\monster\\...)."
                : "Game files into forms you can open: .smd → .ase, textures, sounds, Korean text → UTF-8,\n" +
                  ".inx → .ini / .inf / .in. Written to the output folder in the game's folder layout.");
            return z;
        }

        Control BrowseRow(bool enc)
        {
            var row = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false,
                                            Margin = enc ? new Padding(5, 2, 0, 0) : new Padding(0, 2, 5, 0) };
            row.Controls.Add(MakeButton("Browse file(s)…", (s, e) => BrowseFiles(enc)));
            row.Controls.Add(MakeButton("Browse folder…", (s, e) => BrowseFolder(enc)));
            return row;
        }

        string OutDir => string.IsNullOrWhiteSpace(outBox.Text) ? Settings.DefaultOut : outBox.Text.Trim();
        bool Busy => worker != null && !worker.IsCompleted;

        void SetDropText(string extra)
        {
            // (with a selection or result the box shows only that: the half-width box has no room for both)
            drop.Text = "DECODE   game → readable\n\n" + (extra != null ? Wrap(extra) :
                        "⇩  Drop the game folder, any folder,\nor .smd / .inx / .wav files here  ⇩\n(or click to browse)");
        }

        void SetEncText(string extra)
        {
            dropEnc.Text = "ENCODE   readable → game\n\n" + (extra != null ? Wrap(extra) :
                           "⇩  Drop edited .ini / .inf / .in, .wav,\n.bmp / .tga files or folders here  ⇩\n(or click to browse)");
        }

        // "Selected: x  -  a, b, c" / "Done: a, b, c" -> one item per line
        static string Wrap(string s)
        {
            s = s.Replace("  -  ", "\n");
            if (s.StartsWith("Done: ")) s = "Done:\n" + s.Substring(6);
            return s.Replace(", ", "\n");
        }

        void Log(string s, Color c)
        {
            log.SelectionStart = log.TextLength;
            log.SelectionLength = 0;
            log.SelectionColor = c;
            log.AppendText(s + "\n");
            log.SelectionColor = log.ForeColor;
            log.ScrollToCaret();
        }

        static readonly Color Ok = Color.FromArgb(137, 209, 133), Err = Color.FromArgb(244, 135, 113),
                              Warn = Color.FromArgb(229, 192, 123), Head = Color.FromArgb(97, 175, 239);

        void UpdateButtons()
        {
            bool any = whole ? scan != null && scan.Files.Count > 0 : pending.Count > 0;
            bool can = any && !Busy && (!needConfirm || chkOk.Checked);
            btnGo.Enabled = can;
            btnCancel.Enabled = Busy;
        }

        // ------------------------------------------------------------- input
        void OnDragEnter(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop) && !Busy)
            {
                e.Effect = DragDropEffects.Copy;
                if (sender == dropEnc) dropEnc.BackColor = EncHot; else drop.BackColor = DropHot;
            }
            else e.Effect = DragDropEffects.None;
        }

        void OnDragDrop(object sender, DragEventArgs e)
        {
            drop.BackColor = DropBack;
            dropEnc.BackColor = EncBack;
            if (e.Data.GetData(DataFormats.FileDrop) is string[] files)
                BeginInvoke(new Action(() => { if (sender == dropEnc) OnEncode(files); else OnInput(files); }));
        }

        void BrowseFiles(bool enc)
        {
            if (Busy) return;
            using (var d = enc
                ? new OpenFileDialog { Title = "Choose edited file(s) to put back into game format",
                                       Filter = "Edited files (*.ini;*.inf;*.in;*.wav;*.bmp;*.tga;*.sin;*.msg;*.txt)|*.ini;*.inf;*.in;*.wav;*.bmp;*.tga;*.sin;*.msg;*.txt|All files (*.*)|*.*",
                                       Multiselect = true, InitialDirectory = OutDir }
                : new OpenFileDialog { Title = "Choose game file(s)",
                                       Filter = "Game files (*.smd;*.inx;*.wav;*.bgm;*.bmp;*.tga;*.inf;*.ini;*.in;*.sin;*.msg)|" +
                                                "*.smd;*.inx;*.wav;*.bgm;*.bmp;*.tga;*.inf;*.ini;*.in;*.sin;*.msg|Priston Tale SMD (*.smd)|*.smd|All files (*.*)|*.*",
                                       Multiselect = true, InitialDirectory = st.LastIn })
                if (d.ShowDialog(this) == DialogResult.OK) { if (enc) OnEncode(d.FileNames); else OnInput(d.FileNames); }
        }

        void BrowseFolder(bool enc)
        {
            if (Busy) return;
            using (var d = new FolderBrowserDialog
                   {
                       Description = enc ? "Choose a folder with edited files. Keep the game's folder names (char\\monster\\...) so each .inx comes out right."
                                         : "Choose the game folder, or any folder below it (searched recursively)",
                       SelectedPath = enc ? OutDir : st.LastIn,
                   })
                if (d.ShowDialog(this) == DialogResult.OK) { if (enc) OnEncode(new[] { d.SelectedPath }); else OnInput(new[] { d.SelectedPath }); }
        }

        void BrowseOut()
        {
            using (var d = new FolderBrowserDialog { Description = "Output folder", SelectedPath = OutDir })
                if (d.ShowDialog(this) == DialogResult.OK) outBox.Text = d.SelectedPath;
        }

        static void OpenFolder(string dir)
        {
            try { Directory.CreateDirectory(dir); Process.Start("explorer.exe", "\"" + dir + "\""); } catch (Exception) { }
        }

        string[] inputs = new string[0];

        void OnInput(string[] paths)
        {
            if (Busy) { Log("Busy - wait for the current conversion to finish.", Warn); return; }
            inputs = paths.Select(Path.GetFullPath).ToArray();
            st.LastIn = File.Exists(inputs[0]) ? Path.GetDirectoryName(inputs[0]) : inputs[0];
            ShowSelection();
        }

        void ShowSelection()
        {
            Converter.ClearClientCache();                       // (folders may have changed since the last drop)
            pending = Batch.Collect(inputs);
            scan = null;
            chkOk.Checked = false;
            needConfirm = false;
            warn.Visible = false;
            // the game folder, or anything with sounds, text or model info in it: convert every kind of file;
            // only .smd (and their textures): the model conversion
            bool gameFolder = inputs.Any(p => Directory.Exists(p) && ClientConvert.LooksLikeClient(p));
            var sc = ClientConvert.ScanInputs(inputs);
            whole = gameFolder || sc.HasClientFiles || (pending.Count == 0 && sc.Files.Count > 0);
            if (whole) { scan = sc; ShowClientSelection(); return; }
            if (pending.Count == 0)
            {
                SetDropText("Nothing to convert in what you dropped.");
                Log("No game files found in: " + string.Join("; ", inputs), Warn);
                UpdateButtons();
                return;
            }
            long bytes = Batch.TotalBytes(pending);
            string names = Path.GetFileName(inputs[0].TrimEnd('\\')) + (inputs.Length > 1 ? " (+" + (inputs.Length - 1) + " more)" : "");
            SetDropText(string.Format("Selected: {0}  -  {1} .smd file(s), {2:0.0} MB", names, pending.Count, bytes / 1e6));
            bool folder = inputs.Any(Directory.Exists);
            if (folder || pending.Count > 1)
            {
                double est = bytes / 1e6 / MbPerSec + 1;
                warnLbl.Text = string.Format(
                    "⚠  This contains {0} .smd files ({1:0} MB). Converting them may take some time - roughly {2}{3} - " +
                    "and writes about {4:0} MB of .ase files{5}.\nTick the box below to continue.",
                    pending.Count, bytes / 1e6, FmtTime(est),
                    chkTex.Checked ? " (longer the first time textures are decoded)" : "",
                    bytes / 1e6 * 3.4, chkTex.Checked ? " plus decoded textures" : "");
                needConfirm = true;
                warn.Visible = true;
                UpdateButtons();
            }
            else
            {
                UpdateButtons();
                Start();                          // single file: convert straight away
            }
        }

        ClientSettings ClientOptions() => new ClientSettings
        {
            OutDir = OutDir, Textures = chkTex.Checked, ServerCopy = chkServer.Checked,
        };

        void ShowClientSelection()
        {
            if (scan == null) scan = ClientConvert.ScanInputs(inputs);
            var c = ClientOptions();
            var F = ClientConvert.FileKind.Model;
            string names = Path.GetFileName(inputs[0].TrimEnd('\\')) + (inputs.Length > 1 ? " (+" + (inputs.Length - 1) + " more)" : "");
            var parts = new List<string>();
            void Part(bool on, ClientConvert.FileKind k, string what) { if (on && scan[k] > 0) parts.Add(scan[k] + " " + what); }
            Part(c.Models, F, "models");
            Part(c.Textures, ClientConvert.FileKind.Texture, "textures");
            Part(c.Sounds, ClientConvert.FileKind.Sound, "sounds");
            Part(c.Text, ClientConvert.FileKind.Text, "text files");
            Part(c.ModelInfo, ClientConvert.FileKind.ModelInfo, "model info files");
            if (parts.Count == 0)
            {
                SetDropText("Nothing to convert in what you dropped.");
                UpdateButtons();
                return;
            }
            SetDropText("Selected: " + names + "  -  " + string.Join(", ", parts));
            double smdMb = c.Models ? scan.BytesOf(F) / 1e6 : 0;
            double restMb = (c.Textures ? scan.BytesOf(ClientConvert.FileKind.Texture) : 0) / 1e6 +
                            (c.Sounds ? scan.BytesOf(ClientConvert.FileKind.Sound) : 0) / 1e6;
            int count = scan.Files.Count;
            if (count > 1 || inputs.Any(Directory.Exists))
            {
                double est = smdMb / ModelMbPerSec + restMb / RestMbPerSec + scan[ClientConvert.FileKind.Text] / 1000.0 + 1;
                double outMb = smdMb * 3.4 + restMb;
                warnLbl.Text = string.Format(
                    "⚠  Converting {0} may take some time - roughly {1} - and writes about {2} into the output folder, " +
                    "in the same folder layout as the game.{3}\nTick the box below to continue.",
                    string.Join(", ", parts), FmtTime(est), outMb >= 1000 ? (outMb / 1000).ToString("0.0") + " GB" : outMb.ToString("0") + " MB",
                    c.ServerCopy && scan[ClientConvert.FileKind.ModelInfo] > 0 ? "\nThe model info also goes into _server\\ in the game's Korean code page (for the server)." : "");
                needConfirm = true;
                warn.Visible = true;
                UpdateButtons();
            }
            else
            {
                UpdateButtons();
                Start();
            }
        }

        // encode: edited files -> <output>\game_format, straight away (it is quick)
        void OnEncode(string[] paths)
        {
            if (Busy) { Log("Busy - wait for the current conversion to finish.", Warn); return; }
            paths = paths.Select(Path.GetFullPath).ToArray();
            Converter.ClearClientCache();                       // (folders may have changed since the last drop)
            string outDir = Path.GetFullPath(Path.Combine(OutDir, "game_format")).TrimEnd('\\');
            string names = Path.GetFileName(paths[0].TrimEnd('\\')) + (paths.Length > 1 ? " (+" + (paths.Length - 1) + " more)" : "");
            // the game folder itself is not edited files (it would copy the whole client)
            string game = paths.FirstOrDefault(p => Directory.Exists(p) && ClientConvert.LooksLikeClient(p) && Directory.EnumerateFiles(p, "*.exe").Any());
            if (game != null)
            {
                SetEncText("That is the game folder itself - drop the folder with your edited files");
                Log("ENCODE is for the files you edited (in the output folder, " + OutDir + "). " + game +
                    " is the game folder: drop it on DECODE to get readable copies.", Warn);
                return;
            }
            // (inside a dropped output folder, _server and an earlier game_format are left out)
            var files = ClientConvert.ToGameFiles(paths, outDir);
            if (files.Count == 0) { SetEncText("Nothing to encode in " + names + "."); return; }
            SetEncText("Encoding " + names + " …");
            Log("=== Encoding back to game format: " + files.Count + " file(s) -> " + outDir + " ===", Head);
            bool quiet = files.Count > 300;                       // (a whole folder: notes and errors only)
            prog.Maximum = Math.Max(1, files.Count);
            prog.Value = 0;
            cts = new CancellationTokenSource();
            var token = cts.Token;
            int lastShown = -1;
            worker = Task.Run(() =>
            {
                ClientConvert.ToGameResult r;
                try
                {
                    r = ClientConvert.ToGame(files, outDir,
                        (line, ok) => { if (!ok || !quiet) BeginInvoke(new Action(() => Log(line, ok ? Ok : Warn))); }, 172,
                        (i, n, rel) =>
                        {
                            if (i - lastShown < 25 && i < n) return;              // (don't flood the window)
                            lastShown = i;
                            BeginInvoke(new Action(() => { status.Text = string.Format("({0}/{1}) {2}", Math.Min(i + 1, n), n, rel); SetProgress(i); }));
                        },
                        token);
                }
                catch (Exception ex) { BeginInvoke(new Action(() => Log("Unexpected error: " + ex.Message, Err))); r = new ClientConvert.ToGameResult(); }
                BeginInvoke(new Action(() =>
                {
                    worker = null;
                    if (!r.Cancelled) SetProgress(prog.Maximum);
                    Log("=== " + r.Summary() + (r.Cancelled ? " (cancelled)" : "") + " ===", r.Failed > 0 ? Err : Head);
                    if (r.Notes > 0) Log("Read the notes above: they say what was put right, or what the game will not read as you meant.", Warn);
                    status.Text = "Done: " + r.Summary();
                    SetEncText("Done: " + r.Summary());
                    UpdateButtons();
                    if (!QuietForTests && !r.Cancelled && r.Inx + r.Sounds + r.Textures + r.Texts > 0) OpenFolder(outDir);
                }));
            });
            UpdateButtons();
        }

        // Windows animates progress bars; stepping past the value and back makes it jump immediately.
        void SetProgress(int v)
        {
            v = Math.Max(0, Math.Min(prog.Maximum, v));
            if (v < prog.Maximum) { prog.Value = v + 1; prog.Value = v; }
            else { prog.Maximum = v + 1; prog.Value = v + 1; prog.Maximum = v; prog.Value = v; }
        }

        static string FmtTime(double s)
        {
            if (s < 1.5) return "1 second";
            if (s < 60) return Math.Round(s) + " seconds";
            return string.Format("{0} min {1:00} s", (int)(s / 60), (int)(s % 60));
        }

        // ------------------------------------------------------------- conversion
        void Start()
        {
            if (whole) { StartClient(); return; }
            if (pending.Count == 0 || Busy || (needConfirm && !chkOk.Checked)) return;
            string outDir = OutDir;
            try { Directory.CreateDirectory(outDir); }
            catch (Exception ex) { MessageBox.Show(this, "Cannot create the output folder:\n" + ex.Message, AppName); return; }
            SaveSettings();
            var files = pending;
            pending = new List<string>();
            var s = new BatchSettings
            {
                OutDir = outDir,
                Textures = chkTex.Checked,
            };
            s.Template.SplitCollision = !rbKeep.Checked;
            s.Template.DropCollision = rbDrop.Checked;
            s.Template.SplitObjects = chkSplit.Checked;
            s.Template.VertexColors = chkVc.Checked;
            s.Template.IncludeLights = chkLights.Checked;

            needConfirm = false;
            warn.Visible = false;
            prog.Maximum = files.Count;
            prog.Value = 0;
            Log(string.Format("=== Converting {0} file(s) -> {1} ===", files.Count, outDir), Head);
            cts = new CancellationTokenSource();
            var token = cts.Token;
            worker = Task.Run(() =>
            {
                BatchResult r;
                try
                {
                    r = Batch.Run(files, s,
                        (i, f) => BeginInvoke(new Action(() =>
                        {
                            status.Text = string.Format("({0}/{1}) {2}", i + 1, files.Count, Path.GetFileName(f));
                            SetProgress(i);
                        })),
                        (line, ok) => BeginInvoke(new Action(() => Log(line, ok ? Ok : (line.StartsWith("Cancel") ? Warn : Err)))),
                        token);
                }
                catch (Exception ex)
                {
                    BeginInvoke(new Action(() => Log("Unexpected error: " + ex, Err)));
                    r = new BatchResult();
                }
                BeginInvoke(new Action(() => Done(r, files.Count)));
            });
            UpdateButtons();
        }

        void StartClient()
        {
            if (scan == null || scan.Files.Count == 0 || Busy || (needConfirm && !chkOk.Checked)) return;
            var c = ClientOptions();
            try { Directory.CreateDirectory(c.OutDir); }
            catch (Exception ex) { MessageBox.Show(this, "Cannot create the output folder:\n" + ex.Message, AppName); return; }
            SaveSettings();
            c.Template.SplitCollision = !rbKeep.Checked;
            c.Template.DropCollision = rbDrop.Checked;
            c.Template.SplitObjects = chkSplit.Checked;
            c.Template.VertexColors = chkVc.Checked;
            c.Template.IncludeLights = chkLights.Checked;
            var sc = scan;
            scan = null;
            needConfirm = false;
            warn.Visible = false;
            prog.Maximum = Math.Max(1, sc.Files.Count);
            prog.Value = 0;
            Log(string.Format("=== Converting the game files ({0} files) -> {1} ===", sc.Files.Count, c.OutDir), Head);
            foreach (var r0 in sc.Roots) Log("game folder: " + r0, Head);
            cts = new CancellationTokenSource();
            var token = cts.Token;
            int lastShown = -1;
            worker = Task.Run(() =>
            {
                ClientResult r;
                try
                {
                    r = ClientConvert.Run(sc, c,
                        (i, n, rel) =>
                        {
                            if (i - lastShown < 25 && i < n) return;              // (don't flood the window)
                            lastShown = i;
                            BeginInvoke(new Action(() => { status.Text = string.Format("({0}/{1}) {2}", Math.Min(i + 1, n), n, rel); SetProgress(i); }));
                        },
                        (line, ok) => { if (!ok) BeginInvoke(new Action(() => Log(line, line.StartsWith("Cancel") ? Warn : Err))); },
                        token);
                }
                catch (Exception ex)
                {
                    BeginInvoke(new Action(() => Log(ex is ArgumentException ? ex.Message : "Unexpected error: " + ex, Err)));
                    r = new ClientResult();
                }
                BeginInvoke(new Action(() => DoneClient(r, c.OutDir)));
            });
            UpdateButtons();
        }

        void DoneClient(ClientResult r, string outDir)
        {
            worker = null;
            if (!r.Cancelled) SetProgress(prog.Maximum);
            string summary = r.Summary() + " in " + FmtTime(r.Elapsed.TotalSeconds);
            status.Text = "Done: " + summary;
            Log("=== " + summary + " ===", r.Failed > 0 ? Err : Head);
            if (r.ServerDir != null) Log("Model info for the server (Korean code page): " + r.ServerDir, Head);
            if (r.MissingReport != null)
                Log(string.Format("{0} referenced texture(s) are not in the game folder - listed in {1}", r.Missing.Count, r.MissingReport), Warn);
            SetDropText("Done - drop more files to convert again.");
            UpdateButtons();
            if (r.Files > 0 && !r.Cancelled && !QuietForTests &&
                MessageBox.Show(this, "Done: " + r.Summary() + ".\n\nOpen the output folder?", AppName,
                                MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                OpenFolder(outDir);
        }

        void Done(BatchResult r, int total)
        {
            worker = null;
            if (!r.Cancelled) SetProgress(prog.Maximum);
            string summary = string.Format("{0} converted, {1} failed{2} in {3}", r.Ok, r.Failed,
                r.Skipped > 0 ? ", " + r.Skipped + " skipped" : "", FmtTime(r.Elapsed.TotalSeconds));
            status.Text = "Done: " + summary;
            Log("=== " + summary + " ===", r.Failed > 0 ? Err : Head);
            if (r.MissingReport != null)
                Log(string.Format("{0} referenced texture(s) are not in the game folder - listed in {1}", r.Missing.Count, r.MissingReport), Warn);
            if (pending.Count == 0) SetDropText("Done - drop more files to convert again.");
            UpdateButtons();
            if (r.Ok > 0 && !QuietForTests)
            {
                var ans = MessageBox.Show(this, r.Ok + " file(s) converted" + (r.Failed > 0 ? ", " + r.Failed + " failed" : "") +
                                          ".\n\nOpen the output folder?", AppName, MessageBoxButtons.YesNo, MessageBoxIcon.Information);
                if (ans == DialogResult.Yes)
                {
                    if (r.Outputs.Count == 1) Process.Start("explorer.exe", "/select,\"" + r.Outputs[0] + "\"");
                    else OpenFolder(OutDir);
                }
            }
        }

        public static bool QuietForTests;

        void SaveSettings()
        {
            st.OutDir = OutDir;
            st.Textures = chkTex.Checked;
            st.VertexColors = chkVc.Checked;
            st.Lights = chkLights.Checked;
            st.SplitObjects = chkSplit.Checked;
            st.Collision = rbKeep.Checked ? "keep" : rbDrop.Checked ? "drop" : "split";
            st.ServerCopy = chkServer.Checked;
            if (WindowState == FormWindowState.Normal) { st.Width = ClientSize.Width; st.Height = ClientSize.Height; }
            st.Save();
        }

        void OnClosing(object sender, FormClosingEventArgs e)
        {
            if (Busy)
            {
                if (MessageBox.Show(this, "A conversion is running. Stop it and quit?", AppName, MessageBoxButtons.YesNo) != DialogResult.Yes)
                {
                    e.Cancel = true;
                    return;
                }
                cts?.Cancel();
            }
            SaveSettings();
        }

        // test hooks
        public void TestInput(string[] p) => OnInput(p);
        public void TestTick() => chkOk.Checked = true;
        public void TestConvert() => btnGo.PerformClick();
        public bool TestConvertEnabled => btnGo.Enabled;
        public bool TestWarningVisible => warn.Visible;
        public bool TestBusy => Busy;
        public string TestStatus => status.Text;
        public void TestSetOut(string d) => outBox.Text = d;
        public bool TestWhole => whole;
        public void TestEncode(string[] p) => OnEncode(p);
    }
}
