using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System;

// Hilfsklasse: So sieht unsere JSON-Datei für Unity aus
[Serializable]
public class ConfigData
{
    public string ros_ip;
    public string ros_port;
}

public class AppConfig : MonoBehaviour
{
    // Diese Variablen können von überall im Projekt abgerufen werden
    public static string RosIp = "127.0.0.1";
    public static string RosPort = "9090";
    public static bool IsLoaded = false;

    void Awake()
    {
        // Startet das Laden sofort, wenn das Spiel beginnt
        StartCoroutine(LoadConfig());
    }

    IEnumerator LoadConfig()
    {
        string filePath = System.IO.Path.Combine(Application.streamingAssetsPath, "config.json");

        // Wenn wir nicht im Web sind, brauchen wir "file://" davor
        if (!filePath.Contains("://"))
        {
            filePath = "file://" + filePath;
        }

        Debug.Log("Lade Config von: " + filePath);

        using (UnityWebRequest webRequest = UnityWebRequest.Get(filePath))
        {
            // Warten bis die Datei geladen ist
            yield return webRequest.SendWebRequest();

            if (webRequest.result == UnityWebRequest.Result.Success)
            {
                // JSON lesen
                ConfigData data = JsonUtility.FromJson<ConfigData>(webRequest.downloadHandler.text);
                RosIp = data.ros_ip;
                RosPort = data.ros_port;
                IsLoaded = true;
                Debug.Log($"Config geladen! Ziel ist Roboter: {RosIp}:{RosPort}");
            }
            else
            {
                Debug.LogError("Fehler beim Laden der Config: " + webRequest.error);
            }
        }
    }
}