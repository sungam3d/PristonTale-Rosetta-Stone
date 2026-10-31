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
        const string AppName = "PT SMD → ASE Converter";
        const double MbPerSec = 15.0;       // measured: whole client (440 MB of SMD) in ~25 s incl. textures

        readonly Settings st = Settings.Load();
        readonly Label drop;
        readonly TextBox outBox;
        readonly CheckBox chkTex, chkVc, chkLights, chkSplit, chkOk;
        readonly RadioButton rbSplit, rbKeep, rbDrop;
        readonly ComboBox cmbWhat;
        readonly Panel warn;
        readonly Label warnLbl, status;
        readonly Button btnGo, btnCancel;
        readonly ProgressBar prog;
        readonly RichTextBox log;

        List<string> pending = new List<string>();
        bool needConfirm;
        CancellationTokenSource cts;
        Task worker;

        static readonly Color DropBack = Color.FromArgb(238, 243, 251), DropHot = Color.FromArgb(214, 230, 252);

        public MainForm(string[] initial)
        {
            Text = AppName + "  v" + Application.ProductVersion;
            Font = new Font("Segoe UI", 9f);
            AutoScaleMode = AutoScaleMode.Font;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch (Exception) { }
            ClientSize = new Size(st.Width, st.Height);
            MinimumSize = new Size(640, 560);
            StartPosition = FormStartPosition.CenterScreen;
            AllowDrop = true;
            DragEnter += OnDragEnter;
            DragLeave += (s, e) => drop.BackColor = DropBack;
            DragDrop += OnDragDrop;

            var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, Padding = new Padding(10) };
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 120));   // drop
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // browse
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // output
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // options
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // warning
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // actions
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));         // progress
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));     // log
            Controls.Add(root);

            // drop zone
            drop = new Label
            {
                Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, BackColor = DropBack,
                ForeColor = Color.FromArgb(43, 74, 122), Font = new Font("Segoe UI", 13f), BorderStyle = BorderStyle.FixedSingle,
                Cursor = Cursors.Hand, AllowDrop = true, Margin = new Padding(0, 0, 0, 6),
            };
            drop.DragEnter += OnDragEnter;
            drop.DragLeave += (s, e) => drop.BackColor = DropBack;
            drop.DragDrop += OnDragDrop;
            drop.Click += (s, e) => BrowseFiles();
            SetDropText(null);
            root.Controls.Add(drop);

            var browse = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
            browse.Controls.Add(MakeButton("Browse .smd file(s)…", (s, e) => BrowseFiles()));
            browse.Controls.Add(MakeButton("Browse folder…", (s, e) => BrowseFolder()));
            root.Controls.Add(browse);

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
            opt.Controls.Add(new Label { Text = "Convert:", AutoSize = true, Margin = new Padding(3, 7, 3, 3) }, 0, 4);
            cmbWhat = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260 };
            cmbWhat.Items.AddRange(new object[] { "Everything", "Terrain maps only", "Objects, characters, monsters" });
            cmbWhat.SelectedIndex = Math.Max(0, Math.Min(2, st.What));
            cmbWhat.SelectedIndexChanged += (s, e) => { if (pending.Count > 0 && !Busy) ShowSelection(); };
            opt.Controls.Add(cmbWhat, 1, 4);
            opGrp.Controls.Add(opt);
            root.Controls.Add(opGrp);

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
            if (initial != null && initial.Length > 0)
                Shown += (s, e) => OnInput(initial);
        }

        static Button MakeButton(string text, EventHandler click)
        {
            var b = new Button { Text = text, AutoSize = true, Padding = new Padding(6, 1, 6, 1) };
            b.Click += click;
            return b;
        }

        string OutDir => string.IsNullOrWhiteSpace(outBox.Text) ? Settings.DefaultOut : outBox.Text.Trim();
        bool Busy => worker != null && !worker.IsCompleted;

        void SetDropText(string extra)
        {
            drop.Text = "⇩  Drop an .smd file (map, character, monster) or a whole folder here  ⇩\n(or click to browse)" + (extra != null ? "\n\n" + extra : "");
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
            bool can = pending.Count > 0 && !Busy && (!needConfirm || chkOk.Checked);
            btnGo.Enabled = can;
            btnCancel.Enabled = Busy;
        }

        // ------------------------------------------------------------- input
        void OnDragEnter(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop) && !Busy)
            {
                e.Effect = DragDropEffects.Copy;
                drop.BackColor = DropHot;
            }
            else e.Effect = DragDropEffects.None;
        }

        void OnDragDrop(object sender, DragEventArgs e)
        {
            drop.BackColor = DropBack;
            if (e.Data.GetData(DataFormats.FileDrop) is string[] files) BeginInvoke(new Action(() => OnInput(files)));
        }

        void BrowseFiles()
        {
            if (Busy) return;
            using (var d = new OpenFileDialog { Title = "Choose .smd file(s)", Filter = "Priston Tale SMD (*.smd)|*.smd|All files (*.*)|*.*",
                                                Multiselect = true, InitialDirectory = st.LastIn })
                if (d.ShowDialog(this) == DialogResult.OK) OnInput(d.FileNames);
        }

        void BrowseFolder()
        {
            if (Busy) return;
            using (var d = new FolderBrowserDialog { Description = "Choose a folder (searched recursively for .smd files)", SelectedPath = st.LastIn })
                if (d.ShowDialog(this) == DialogResult.OK) OnInput(new[] { d.SelectedPath });
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
            pending = Batch.Collect(inputs);
            chkOk.Checked = false;
            needConfirm = false;
            warn.Visible = false;
            if (pending.Count == 0)
            {
                SetDropText("No .smd files found in what you dropped.");
                Log("No .smd files found in: " + string.Join("; ", inputs), Warn);
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
                StagesOnly = cmbWhat.SelectedIndex == 1,
                ModelsOnly = cmbWhat.SelectedIndex == 2,
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
            st.What = cmbWhat.SelectedIndex;
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
    }
}
