using UnityEditor;
using UnityEngine;
using System.IO;

public class ForceModelImporter : EditorWindow
{
    [MenuItem("Tools/Roboter/Erzwinge Model-Importer")]
    public static void Execute()
    {
        // Sucht im gesamten Projekt nach STL-Dateien
        string[] allAssetPaths = AssetDatabase.GetAllAssetPaths();
        int count = 0;

        foreach (string path in allAssetPaths)
        {
            if (path.EndsWith(".stl", System.StringComparison.OrdinalIgnoreCase))
            {
                Debug.Log($"Gefunden: {path}");
                // Erzwingt die Behandlung als Model (3D-Mesh)
                AssetImporter importer = AssetImporter.GetAtPath(path);
                if (importer != null && !(importer is ModelImporter))
                {
                    AssetDatabase.SetImporterOverride<ModelImporter>(path);
                    AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
                    count++;
                }
            }
        }
        AssetDatabase.Refresh();
        Debug.Log($"{count} STL-Dateien wurden auf Model-Importer umgestellt.");
    }
}