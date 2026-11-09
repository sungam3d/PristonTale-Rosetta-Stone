// Interface languages: the language builds of the game source (_LANGUAGE_KOREAN, _ENGLISH,
// _CHINESE, _TAIWAN, _JAPANESE, _THAI, _VEITNAM, _BRAZIL, _ARGENTINA; the Philippine client was
// English).  Each language is an embedded table  PTSmd.lang.<code>.txt  of  key = text  lines
// (UTF-8, "#" comments, \n for a new line, {0} {1} ... for values).  A key missing from a table
// falls back to English, a key missing from English shows as itself.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace PTSmd
{
    public static class L
    {
        public sealed class Language
        {
            public readonly string Code, Name;
            public readonly int GameCodePage;          // the code page that language's game client writes its text in
            public Language(string code, string name, int cp) { Code = code; Name = name; GameCodePage = cp; }
            public override string ToString() => Name;
        }

        public static readonly Language[] Languages =
        {
            new Language("en", "English", 1252),
            new Language("ko", "한국어", 949),
            new Language("zh-CN", "简体中文", 936),
            new Language("zh-TW", "繁體中文", 950),
            new Language("ja", "日本語", 932),
            new Language("th", "ไทย", 874),
            new Language("vi", "Tiếng Việt", 1258),
            new Language("pt-BR", "Português (Brasil)", 1252),
            new Language("es", "Español (Latinoamérica)", 1252),
        };

        static readonly Dictionary<string, Dictionary<string, string>> tables = new Dictionary<string, Dictionary<string, string>>();
        static Dictionary<string, string> en, cur;
        public static string Current { get; private set; } = "en";

        public static Language Find(string code) =>
            Languages.FirstOrDefault(l => string.Equals(l.Code, code, StringComparison.OrdinalIgnoreCase));

        /// <summary>The language of the Windows display language, or English.</summary>
        public static string FromCulture(CultureInfo c)
        {
            string n = c.Name.ToLowerInvariant();
            if (n.StartsWith("zh")) return n.Contains("tw") || n.Contains("hk") || n.Contains("mo") || n.Contains("hant") ? "zh-TW" : "zh-CN";
            if (n.StartsWith("pt")) return "pt-BR";
            string two = c.TwoLetterISOLanguageName;
            var l = Find(two);
            return l != null ? l.Code : "en";
        }

        public static string SystemDefault => FromCulture(CultureInfo.CurrentUICulture);

        public static void Set(string code)
        {
            var l = Find(code) ?? Find("en");
            Current = l.Code;
            en = Table("en");
            cur = Table(l.Code);
        }

        static Dictionary<string, string> Table(string code)
        {
            lock (tables)
            {
                if (tables.TryGetValue(code, out var t)) return t;
                t = new Dictionary<string, string>(StringComparer.Ordinal);
                var asm = typeof(L).GetTypeInfo().Assembly;
                using (var s = asm.GetManifestResourceStream("PTSmd.lang." + code + ".txt"))
                    if (s != null)
                        using (var r = new StreamReader(s, Encoding.UTF8))
                            foreach (var line0 in r.ReadToEnd().Split('\n'))
                            {
                                string line = line0.TrimEnd('\r');
                                if (line.Length == 0 || line[0] == '#') continue;
                                int eq = line.IndexOf(" = ", StringComparison.Ordinal);
                                if (eq <= 0) continue;
                                t[line.Substring(0, eq).Trim()] = line.Substring(eq + 3).Replace("\\n", "\n").Replace("\\t", "\t");
                            }
                tables[code] = t;
                return t;
            }
        }

        /// <summary>The text for key in the current language (string.Format'ed with args, if any).</summary>
        public static string T(string key, params object[] args)
        {
            if (en == null) Set(Current);
            if (!cur.TryGetValue(key, out var s) && !en.TryGetValue(key, out s)) s = key;
            if (args == null || args.Length == 0) return s;
            try { return string.Format(CultureInfo.InvariantCulture, s, args); }
            catch (FormatException) { return s + " " + string.Join(" ", args); }
        }

        /// <summary>The English text for key (no values filled in).</summary>
        public static string En(string key)
        {
            if (en == null) Set(Current);
            return en.TryGetValue(key, out var s) ? s : key;
        }

        /// <summary>Every key of the English table (for checks).</summary>
        public static IEnumerable<string> Keys(string code = "en") => Table(code).Keys;
    }
}
