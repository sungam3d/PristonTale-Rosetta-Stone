using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using PTSmd;

namespace Smd2Ase
{
    static class Program
    {
        const string Help =
@"smd2ase - convert Priston Tale .smd files (maps, objects, characters, monsters) to 3ds Max .ase

usage: smd2ase <file.smd | file.smb | folder> [...] [options]

  -o, --out DIR           output folder (default: ase_out)
  --game-root DIR         game folder that contains Field\ (auto-detected)
  --textures              copy + decrypt every referenced texture into <out>\textures
  --stages-only           only convert terrain (stage) files
  --models-only           only convert object (model) files
  --one-mesh              maps: write one mesh (default: split into the original objects)
  --keep-collision        keep collision faces in the main object
  --drop-collision        omit collision faces entirely
  --all-material-slots    keep every SMD material slot (MTLID == SMD index)
  --no-vertex-colors      do not write baked lighting colours
  --clamp-colors          cap vertex colours at 1.0 (default: keep the overbright
                          lighting near lamps, so the map comes back as it was)
  --color-scale X         multiply baked colours (default 1.0)
  --animation MODE        characters/monsters: auto (default), embed, shared or none
                          auto = monsters get their animation inside the .ase, player
                          bodies/heads share one class file (m1_motions.ase ...)
  --lod all               keep every monster detail level (default: high detail only)
  --no-lights             do not write stage lights

whole client:
  --client                convert everything in the game folder(s) given, keeping the folder
                          layout: models -> .ase, textures, sounds (.wav playable again, music
                          X.bgm -> X.bgm.wav), Korean text -> UTF-8, compiled model info (.inx) -> the
                          .ini / .inf / .in it was built from; plus <out>\_server\ with the
                          model info in the game's own code page (CP949)
  --no-models / --no-textures / --no-sounds / --no-text / --no-modelinfo / --no-server-copy
                          leave that kind out (with --client)
  --copy-other            also copy every other file unchanged (with --client)

back to the game:
  --to-game               the files / folders given -> the forms the client ships:
                          .ini/.inf/.in -> .inx (+ CP949 text), .wav -> client sound header in
                          the layout the game reads (X.bgm.wav -> X.bgm), .bmp/.tga -> client
                          texture header (RLE TGAs unpacked, BMP layout fixed), UTF-8 / UTF-16
                          text -> CP949.  Inside a folder given, _server\ and game_format\ are
                          left out; notes say what the game will not read as meant
  --inx-layout 120        write .inx for 2012 clients (default 172: later clients)
  --encode-textures DIR   scramble every plain .bmp/.tga under DIR in place

checks:
  --check-inx DIR         decompile + recompile every .inx under DIR and compare (byte for byte)

examples:
  smd2ase ""C:\Program Files (x86)\MasangSoft\PristonTale(Test)\Field"" -o D:\PT-ASE --textures
  smd2ase --client ""C:\Program Files (x86)\MasangSoft\PristonTale(Test)"" -o D:\PT-Readable
  smd2ase --to-game D:\PT-Readable\char\monster\Tees -o D:\PT-Game";

        static int Main(string[] args)
        {
            try { Console.OutputEncoding = new System.Text.UTF8Encoding(false); } catch (Exception) { }   // (Korean names in notes)
            var inputs = new List<string>();
            var s = new BatchSettings();
            var t = s.Template;
            s.Textures = false;
            var cs = new ClientSettings { Template = t };
            bool client = false, toGame = false, outSet = false;
            int layout = 172;
            try
            {
                for (int i = 0; i < args.Length; i++)
                {
                    string a = args[i];
                    switch (a)
                    {
                        case "-h": case "--help": case "/?": Console.WriteLine(Help); return 0;
                        case "-o": case "--out": s.OutDir = args[++i]; outSet = true; break;
                        case "--client": client = true; break;
                        case "--to-game": toGame = true; break;
                        case "--no-models": cs.Models = false; break;
                        case "--no-sounds": cs.Sounds = false; break;
                        case "--no-textures": cs.Textures = false; break;
                        case "--no-text": cs.Text = false; break;
                        case "--no-modelinfo": cs.ModelInfo = false; break;
                        case "--no-server-copy": cs.ServerCopy = false; break;
                        case "--copy-other": cs.CopyOther = true; break;
                        case "--inx-layout":
                            layout = int.Parse(args[++i], CultureInfo.InvariantCulture);
                            if (layout != 120 && layout != 172) { Console.Error.WriteLine("--inx-layout is 172 (current clients) or 120 (2012 clients)"); return 1; }
                            break;
                        case "--check-inx": return CheckInx(args[++i]);
                        case "--game-root": s.GameRoot = args[++i]; break;
                        case "--textures": s.Textures = true; break;
                        case "--stages-only": s.StagesOnly = true; break;
                        case "--models-only": s.ModelsOnly = true; break;
                        case "--keep-collision": t.SplitCollision = false; break;
                        case "--drop-collision": t.DropCollision = true; break;
                        case "--one-mesh": t.SplitObjects = false; break;
                        case "--all-material-slots": t.CompactMaterials = false; break;
                        case "--no-vertex-colors": t.VertexColors = false; break;
                        case "--no-clamp-colors": t.ClampColors = false; break;
                        case "--clamp-colors": t.ClampColors = true; break;
                        case "--color-scale": t.ColorScale = double.Parse(args[++i], CultureInfo.InvariantCulture); break;
                        case "--bones": break;                                  // (old option: skeletons are automatic now)
                        case "--animation": t.Animation = args[++i].ToLowerInvariant(); break;
                        case "--lod": t.Lod = args[++i].ToLowerInvariant(); break;
                        case "--no-lights": t.IncludeLights = false; break;
                        case "--encode-textures":
                        {
                            var r0 = Textures.EncodeFolder(args[++i], Console.WriteLine);
                            Console.WriteLine("encoded {0} texture(s), {1} skipped (already encoded / not BMP or TGA)", r0.encoded, r0.skipped);
                            return 0;
                        }
                        case "--ase2model":                                       // in.ase out.smd|- out.smb|- [datadir] [own|game]
                        {
                            var eo = new EncodeOptions();
                            string ain = args[++i], aout = args[++i], bout = args[++i];
                            if (i + 1 < args.Length && !args[i + 1].StartsWith("-") && args[i + 1] != "own" && args[i + 1] != "game") eo.DataDir = args[++i];
                            if (i + 1 < args.Length && (args[i + 1] == "own" || args[i + 1] == "game")) eo.OwnFile = args[++i] == "own";
                            if (i + 1 < args.Length && args[i + 1] == "oldnormals") { eo.OldNormals = true; i++; }
                            var mr = AseToSmd.Model(ain, aout == "-" ? null : aout, bout == "-" ? null : bout, eo);
                            Console.WriteLine("{0} objects, {1} bones, {2} vertices, {3} faces, {4} materials, skinned={5}, smd={6}, smb={7}, unassigned={8}",
                                mr.Objects, mr.Bones, mr.Vertices, mr.Faces, mr.Materials, mr.Skinned, mr.WroteSmd, mr.WroteSmb, mr.Unassigned);
                            return 0;
                        }
                        case "--ase2smd":                                         // in.ase out.smd [datadir] [own|game] [contrast bright lx ly lz]
                        {
                            var eo = new EncodeOptions();
                            string ain = args[++i], aout = args[++i];
                            if (i + 1 < args.Length && !args[i + 1].StartsWith("-") && args[i + 1] != "own" && args[i + 1] != "game") eo.DataDir = args[++i];
                            if (i + 1 < args.Length && (args[i + 1] == "own" || args[i + 1] == "game")) eo.OwnFile = args[++i] == "own";
                            if (i + 5 < args.Length && int.TryParse(args[i + 1], out int ct))
                            {
                                eo.Contrast = ct; eo.Bright = int.Parse(args[i + 2]); eo.LightX = int.Parse(args[i + 3]);
                                eo.LightY = int.Parse(args[i + 4]); eo.LightZ = int.Parse(args[i + 5]); i += 5;
                            }
                            if (i + 1 < args.Length && args[i + 1] == "single") { eo.SinglePrecision = true; i++; }
                            if (i + 1 < args.Length && args[i + 1] == "2012") { eo.WideAreas = false; i++; }
                            var er = AseToSmd.Stage(ain, aout, eo);
                            Console.WriteLine("{0}: {1} objects ({2} skipped), {3} vertices, {4} faces, {5} texlinks, {6} materials, {7} textures, {8} lights ({9} dynamic), own={10}",
                                Path.GetFileName(aout), er.Objects, er.Skipped, er.Vertices, er.Faces, er.TexLinks, er.Materials, er.Textures, er.Lights, er.DynLights, er.OwnFile);
                            if (er.BadFaces > 0) Console.WriteLine("  note: {0} face corner(s) pointed past their object's vertices", er.BadFaces);
                            if (er.TooManyVertices) Console.WriteLine("  note: more than 65535 vertices - the game cannot number them");
                            if (er.TooManyFaces) Console.WriteLine("  note: more than 65535 faces - a 2012 client cannot number them");
                            if (er.CrowdedFaces > AseToSmd.CrowdedLimit)
                                Console.WriteLine("  note: {0} faces within reach of one spot (x {1:0}, y {2:0}): 2012-based clients crash there (limit 1000)", er.CrowdedFaces, er.CrowdedX, er.CrowdedY);
                            return 0;
                        }
                        default:
                            if (a.StartsWith("-")) { Console.Error.WriteLine("unknown option " + a + "\n\n" + Help); return 1; }
                            inputs.Add(a);
                            break;
                    }
                }
            }
            catch (IndexOutOfRangeException)
            {
                Console.Error.WriteLine("missing value for the last option");
                return 1;
            }
            if (inputs.Count == 0) { Console.WriteLine(Help); return 1; }
            foreach (var p in inputs) if (!File.Exists(p) && !Directory.Exists(p)) Console.WriteLine("warning: " + p + " not found");
            if (client)
            {
                cs.OutDir = outSet ? s.OutDir : "client_out";
                var scan = ClientConvert.ScanInputs(inputs);
                foreach (var root in scan.Roots) Console.WriteLine("game folder: " + root);
                ClientResult cr;
                try { cr = ClientConvert.Run(scan, cs, null, (line, ok) => { if (!ok) Console.WriteLine(line); }); }
                catch (ArgumentException e) { Console.Error.WriteLine(e.Message); return 1; }
                Console.WriteLine("{0} in {1:0.0}s -> {2}", cr.Summary(), cr.Elapsed.TotalSeconds, Path.GetFullPath(cs.OutDir));
                if (cr.ServerDir != null) Console.WriteLine("server model info (CP949): " + cr.ServerDir);
                if (cr.MissingReport != null) Console.WriteLine("{0} referenced textures not found (listed in {1})", cr.Missing.Count, cr.MissingReport);
                return cr.Failed == 0 ? 0 : 2;
            }
            if (toGame)
            {
                string od = outSet ? s.OutDir : "game_out";
                var gr = ClientConvert.ToGame(inputs, od, (line, ok) => Console.WriteLine(line), layout);
                Console.WriteLine("{0} -> {1}", gr.Summary(), Path.GetFullPath(od));
                return gr.Failed == 0 ? 0 : 2;
            }
            var files = Batch.Collect(inputs);
            if (files.Count == 0) { Console.WriteLine("no .smd / .smb files found"); return 1; }
            var r = Batch.Run(files, s, null, (line, ok) => Console.WriteLine(line));
            Console.WriteLine();
            Console.WriteLine("{0} converted, {1} failed in {2:0.0}s -> {3}", r.Ok, r.Failed, r.Elapsed.TotalSeconds, Path.GetFullPath(s.OutDir));
            if (r.MissingReport != null)
                Console.WriteLine("{0} referenced textures not found on disk (listed in {1})", r.Missing.Count, r.MissingReport);
            return r.Failed == 0 ? 0 : 2;
        }

        /// <summary>Every .inx under dir: decompile, compile again, compare byte for byte.</summary>
        static int CheckInx(string dir)
        {
            int ok = 0, bad = 0;
            foreach (var f in Directory.EnumerateFiles(dir, "*.inx", SearchOption.AllDirectories))
            {
                string rel = Converter.RelPath(f, dir) ?? Path.GetFileName(f);
                byte[] b = File.ReadAllBytes(f);
                try
                {
                    var mi = ClientFiles.ReadInx(b);
                    string text = ClientFiles.InxToIni(mi, rel);
                    byte[] b2 = ClientFiles.CompileIni(text, rel, mi.Layout.Rec, mi.Folder.Length > 0 ? mi.Folder : null, mi.Code);
                    bool same = b.Length == b2.Length;
                    for (int k = 0; same && k < b.Length; k++) same = b[k] == b2[k];
                    if (same) ok++;
                    else { bad++; if (bad <= 10) Console.WriteLine("differs: " + rel); }
                }
                catch (Exception e) { bad++; Console.WriteLine("ERROR " + rel + ": " + e.Message); }
            }
            Console.WriteLine("round trip: {0} identical, {1} differ", ok, bad);
            return bad == 0 ? 0 : 2;
        }
    }
}
