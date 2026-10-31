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
  --no-clamp-colors       allow overbright (>1.0) vertex colours
  --color-scale X         multiply baked colours (default 1.0)
  --animation MODE        characters/monsters: auto (default), embed, shared or none
                          auto = monsters get their animation inside the .ase, player
                          bodies/heads share one class file (m1_motions.ase ...)
  --lod all               keep every monster detail level (default: high detail only)
  --no-lights             do not write stage lights

texture tools:
  --encode-textures DIR   scramble every plain .bmp/.tga under DIR the way the game client
                          ships them (for textures exported next to an edited .ase)

example:
  smd2ase ""C:\Program Files (x86)\MasangSoft\PristonTale(Test)\Field"" -o D:\PT-ASE --textures";

        static int Main(string[] args)
        {
            var inputs = new List<string>();
            var s = new BatchSettings();
            var t = s.Template;
            s.Textures = false;
            try
            {
                for (int i = 0; i < args.Length; i++)
                {
                    string a = args[i];
                    switch (a)
                    {
                        case "-h": case "--help": case "/?": Console.WriteLine(Help); return 0;
                        case "-o": case "--out": s.OutDir = args[++i]; break;
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
                        case "--color-scale": t.ColorScale = double.Parse(args[++i], CultureInfo.InvariantCulture); break;
                        case "--bones": break;                                  // (old option: skeletons are automatic now)
                        case "--animation": t.Animation = args[++i].ToLowerInvariant(); break;
                        case "--lod": t.Lod = args[++i].ToLowerInvariant(); break;
                        case "--no-lights": t.IncludeLights = false; break;
                        case "--encode-textures":
                        {
                            var r0 = Textures.EncodeFolder(args[++i]);
                            Console.WriteLine("encoded {0} texture(s), {1} skipped (already encoded / not BMP or TGA)", r0.encoded, r0.skipped);
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
            var files = Batch.Collect(inputs);
            if (files.Count == 0) { Console.WriteLine("no .smd / .smb files found"); return 1; }
            var r = Batch.Run(files, s, null, (line, ok) => Console.WriteLine(line));
            Console.WriteLine();
            Console.WriteLine("{0} converted, {1} failed in {2:0.0}s -> {3}", r.Ok, r.Failed, r.Elapsed.TotalSeconds, Path.GetFullPath(s.OutDir));
            if (r.MissingReport != null)
                Console.WriteLine("{0} referenced textures not found on disk (listed in {1})", r.Missing.Count, r.MissingReport);
            return r.Failed == 0 ? 0 : 2;
        }
    }
}
