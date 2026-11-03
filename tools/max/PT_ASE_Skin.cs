// PT_ASE_Skin.cs - reads Skin modifier weights through the 3ds Max SDK (Autodesk.Max.dll), for the
// PT ASE exporter.  skinOps needs the modifier open in the Modify panel, and switching the panel
// costs about a second per mesh (an armour of 45 meshes: minutes); the SDK needs no panel.
// Compiled together with PT_ASE_Reader.cs when Autodesk.Max.dll can be referenced; the scripts
// fall back to skinOps otherwise.

using System.Text;
using Autodesk.Max;

namespace PTAse
{
    public class SkinSdk
    {
        static IGlobal G { get { return GlobalInterface.Instance; } }
        const uint I_SKIN = 0x00010000;

        // the topmost Skin modifier of a node (Skin: Class_ID(9815843, 87654)) as ISkin
        static IISkin SkinOf(IINode node)
        {
            IIDerivedObject d = node == null ? null : node.ObjectRef as IIDerivedObject;
            if (d == null) return null;
            for (int i = 0; i < d.NumModifiers; i++)
            {
                IModifier m = d.GetModifier(i);
                if (m != null && m.ClassID.PartA == 9815843 && m.ClassID.PartB == 87654)
                    return m.GetInterface((InterfaceID)I_SKIN) as IISkin;
            }
            return null;
        }

        static IINode Node(uint handle) { return G.COREInterface.GetINodeByHandle(handle); }

        // The strongest bone of every vertex, names joined with '|' ("" = none), as the exporter
        // writes *PHYSIQUE; null when there is no Skin to read.
        public string Physique(uint meshHandle)
        {
            IINode mesh = Node(meshHandle);
            IISkin skin = SkinOf(mesh);
            IISkinContextData ctx = skin == null ? null : skin.GetContextInterface(mesh);
            if (ctx == null) return null;
            string[] names = new string[skin.NumBones];
            for (int i = 0; i < names.Length; i++)
            {
                IINode b = skin.GetBone(i);
                names[i] = b != null ? b.Name : "";
            }
            StringBuilder sb = new StringBuilder();
            for (int v = 0; v < ctx.NumPoints; v++)
            {
                string best = "";
                float bw = 0f;
                for (int k = 0; k < ctx.GetNumAssignedBones(v); k++)
                {
                    float wt = ctx.GetBoneWeight(v, k);
                    int bi = ctx.GetAssignedBone(v, k);
                    if (wt > bw && bi >= 0 && bi < names.Length) { bw = wt; best = names[bi]; }
                }
                if (v > 0) sb.Append('|');
                sb.Append(best);
            }
            return sb.ToString();
        }

        // Node handles of the Skin's bones, ' '-separated ("" = no Skin)
        public string Bones(uint meshHandle)
        {
            IISkin skin = SkinOf(Node(meshHandle));
            if (skin == null) return "";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < skin.NumBones; i++)
            {
                IINode b = skin.GetBone(i);
                if (b == null) continue;
                if (sb.Length > 0) sb.Append(' ');
                sb.Append(b.Handle);
            }
            return sb.ToString();
        }
    }
}
