using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using System;
using System.Globalization;

[Serializable]
public class RosBridgeMsg
{
    public string op;
    public string topic;
    public JointStateMsg msg;
}

[Serializable]
public class JointStateMsg
{
    public HeaderMsg header;
    public string[] name;
    public float[] position;
}

[Serializable]
public class HeaderMsg
{
    public string frame_id;
}

public class RobotStateReceiver : MonoBehaviour
{
    [System.Serializable]
    public class JointLink
    {
        public string rosJointName;
        public Transform unityObject;
        public Vector3 rotationAxis = new Vector3(0, 1, 0);
        public float offset = 0f;
        [Tooltip("Prismatisches Gelenk = Translation statt Rotation")]
        public bool isPrismatic = false;
    }

    [Header("Konfiguration")]
    public List<JointLink> robotJoints = new List<JointLink>();

    private Dictionary<string, JointLink> _jointMap = new Dictionary<string, JointLink>();
    private Dictionary<string, Quaternion> _initialRotations = new Dictionary<string, Quaternion>();
    private Dictionary<string, Vector3> _initialPositions = new Dictionary<string, Vector3>();

    private float _lastLogTime = 0f;
    private const float LOG_INTERVAL = 2f;
    private int _messageCount = 0;

    void Start()
    {
        _jointMap.Clear();
        _initialRotations.Clear();
        _initialPositions.Clear();

        Debug.Log($"<color=cyan>[RobotStateReceiver] Starte Initialisierung von {robotJoints.Count} Gelenken...</color>");

        for (int i = 0; i < robotJoints.Count; i++)
        {
            var j = robotJoints[i];
            if (j == null) continue;

            try
            {
                if (j.unityObject == null || j.unityObject.Equals(null))
                {
                    Debug.LogWarning($"[RobotStateReceiver] Gelenk {i} ({j.rosJointName}): Unity Object fehlt!");
                    continue;
                }

                if (string.IsNullOrEmpty(j.rosJointName))
                {
                    Debug.LogWarning($"[RobotStateReceiver] Gelenk {i}: Kein ROS-Name!");
                    continue;
                }

                if (!_jointMap.ContainsKey(j.rosJointName))
                {
                    _initialRotations[j.rosJointName] = j.unityObject.localRotation;
                    _initialPositions[j.rosJointName] = j.unityObject.localPosition;
                    _jointMap.Add(j.rosJointName, j);
                    Debug.Log($"<color=cyan>[RobotStateReceiver] OK: {j.rosJointName} -> {j.unityObject.name} (Achse: {j.rotationAxis}, Prismatisch: {j.isPrismatic})</color>");
                }
            }
            catch (Exception ex) { Debug.LogError($"[Init] Error joint {i}: {ex}"); }
        }

        Debug.Log($"<color=cyan>[RobotStateReceiver] Init fertig. {_jointMap.Count} Gelenke gemappt.</color>");
        StartCoroutine(SubscribeGeneric());
    }

    IEnumerator SubscribeGeneric()
    {
        while (RosConnector.Instance == null) yield return new WaitForSeconds(0.5f);
        while (!RosConnector.Instance.IsConnected) yield return new WaitForSeconds(0.5f);

        Debug.Log("<color=yellow>[RobotStateReceiver] Subscribing to /joint_states...</color>");
        RosConnector.Instance.Subscribe("/joint_states", "sensor_msgs/msg/JointState", HandleMessage);
    }

    void HandleMessage(string jsonString)
    {
        _messageCount++;

        // === DIAGNOSE: Erste 3 Nachrichten komplett loggen ===
        if (_messageCount <= 3)
        {
            string preview = jsonString.Length > 500 ? jsonString.Substring(0, 500) + "..." : jsonString;
            Debug.Log($"<color=yellow>[RobotStateReceiver] RAW MSG #{_messageCount} (Len={jsonString.Length}): {preview}</color>");
        }

        try
        {
            // Versuch 1: JsonUtility
            RosBridgeMsg packet = JsonUtility.FromJson<RosBridgeMsg>(jsonString);

            if (packet != null && packet.msg != null && packet.msg.name != null && packet.msg.position != null
                && packet.msg.name.Length > 0 && packet.msg.position.Length > 0)
            {
                if (_messageCount <= 3)
                {
                    Debug.Log($"<color=green>[RobotStateReceiver] JsonUtility OK: {packet.msg.name.Length} names, {packet.msg.position.Length} positions</color>");
                    for (int i = 0; i < Mathf.Min(packet.msg.name.Length, packet.msg.position.Length); i++)
                        Debug.Log($"  [{i}] {packet.msg.name[i]} = {packet.msg.position[i]:F4}");
                }

                int count = Mathf.Min(packet.msg.name.Length, packet.msg.position.Length);
                for (int i = 0; i < count; i++)
                    UpdateJoint(packet.msg.name[i], packet.msg.position[i]);
            }
            else
            {
                // JsonUtility hat NICHT funktioniert -> manuelles Parsing
                if (_messageCount <= 3)
                {
                    Debug.LogWarning($"[RobotStateReceiver] JsonUtility FEHLGESCHLAGEN! packet={packet != null}, msg={packet?.msg != null}, names={packet?.msg?.name?.Length}, pos={packet?.msg?.position?.Length}");
                    Debug.Log("[RobotStateReceiver] Verwende manuellen JSON-Parser...");
                }
                ParseAndApplyManual(jsonString);
            }

            if (Time.time - _lastLogTime > LOG_INTERVAL)
                _lastLogTime = Time.time;
        }
        catch (Exception e)
        {
            Debug.LogError($"[RobotStateReceiver] HandleMessage Error: {e}");
            try { ParseAndApplyManual(jsonString); } catch { }
        }
    }

    /// <summary>
    /// Manuelles Parsing der rosbridge JSON-Nachricht ohne JsonUtility.
    /// Extrahiert "name" und "position" Arrays direkt aus dem JSON-String.
    /// </summary>
    void ParseAndApplyManual(string json)
    {
        string[] names = ExtractStringArray(json, "name");
        float[] positions = ExtractFloatArray(json, "position");

        if (names == null || positions == null || names.Length == 0 || positions.Length == 0)
        {
            if (_messageCount <= 5)
                Debug.LogError($"[RobotStateReceiver] Manuelles Parsing fehlgeschlagen! names={names?.Length}, positions={positions?.Length}");
            return;
        }

        if (_messageCount <= 3)
        {
            Debug.Log($"<color=green>[RobotStateReceiver] Manuelles Parsing OK: {names.Length} names, {positions.Length} positions</color>");
            for (int i = 0; i < Mathf.Min(names.Length, positions.Length); i++)
                Debug.Log($"  [{i}] {names[i]} = {positions[i]:F4}");
        }

        int count = Mathf.Min(names.Length, positions.Length);
        for (int i = 0; i < count; i++)
            UpdateJoint(names[i], positions[i]);

        if (Time.time - _lastLogTime > LOG_INTERVAL)
            _lastLogTime = Time.time;
    }

    /// <summary>
    /// Extrahiert ein JSON-String-Array: "key":["val1","val2",...]
    /// </summary>
    string[] ExtractStringArray(string json, string key)
    {
        string searchKey = "\"" + key + "\"";
        int keyIdx = json.IndexOf(searchKey);
        if (keyIdx < 0) return null;

        int bracketStart = json.IndexOf('[', keyIdx);
        if (bracketStart < 0) return null;

        int bracketEnd = FindMatchingBracket(json, bracketStart);
        if (bracketEnd < 0) return null;

        string arrayContent = json.Substring(bracketStart + 1, bracketEnd - bracketStart - 1).Trim();
        if (string.IsNullOrEmpty(arrayContent)) return new string[0];

        List<string> result = new List<string>();
        bool inQuote = false;
        int start = -1;

        for (int i = 0; i < arrayContent.Length; i++)
        {
            char c = arrayContent[i];
            if (c == '"' && !inQuote)
            {
                inQuote = true;
                start = i + 1;
            }
            else if (c == '"' && inQuote)
            {
                inQuote = false;
                result.Add(arrayContent.Substring(start, i - start));
            }
        }
        return result.ToArray();
    }

    /// <summary>
    /// Extrahiert ein JSON-Float-Array: "key":[1.23, -4.56, ...]
    /// </summary>
    float[] ExtractFloatArray(string json, string key)
    {
        string searchKey = "\"" + key + "\"";
        int keyIdx = json.IndexOf(searchKey);
        if (keyIdx < 0) return null;

        int bracketStart = json.IndexOf('[', keyIdx);
        if (bracketStart < 0) return null;

        int bracketEnd = FindMatchingBracket(json, bracketStart);
        if (bracketEnd < 0) return null;

        string arrayContent = json.Substring(bracketStart + 1, bracketEnd - bracketStart - 1).Trim();
        if (string.IsNullOrEmpty(arrayContent)) return new float[0];

        string[] parts = arrayContent.Split(',');
        List<float> result = new List<float>();
        for (int i = 0; i < parts.Length; i++)
        {
            string s = parts[i].Trim();
            if (float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out float val))
                result.Add(val);
        }
        return result.ToArray();
    }

    int FindMatchingBracket(string json, int openIdx)
    {
        int depth = 0;
        for (int i = openIdx; i < json.Length; i++)
        {
            if (json[i] == '[') depth++;
            else if (json[i] == ']') { depth--; if (depth == 0) return i; }
        }
        return -1;
    }

    void UpdateJoint(string jointName, float posRad)
    {
        if (_jointMap.ContainsKey(jointName))
        {
            try
            {
                JointLink link = _jointMap[jointName];
                if (link == null || link.unityObject == null) return;

                if (link.isPrismatic)
                {
                    float posMeters = posRad + link.offset;
                    link.unityObject.localPosition = _initialPositions[jointName] + link.rotationAxis * posMeters;

                    if (Time.time - _lastLogTime > LOG_INTERVAL)
                        Debug.Log($"[RobotStateReceiver] Prismatic {jointName} -> {posMeters:F4} m");
                }
                else
                {
                    float angleDeg = posRad * Mathf.Rad2Deg;
                    float finalAngle = angleDeg + link.offset;

                    Quaternion rot = Quaternion.AngleAxis(finalAngle, link.rotationAxis);
                    link.unityObject.localRotation = _initialRotations[jointName] * rot;

                    if (Time.time - _lastLogTime > LOG_INTERVAL)
                        Debug.Log($"[RobotStateReceiver] {jointName} -> ROS: {posRad:F3} rad | Unity: {finalAngle:F1} deg");
                }
            }
            catch (Exception e)
            {
                Debug.LogError($"[RobotStateReceiver] UpdateJoint Error {jointName}: {e.Message}");
            }
        }
        else
        {
            if (Time.time - _lastLogTime > LOG_INTERVAL)
                Debug.LogWarning($"[RobotStateReceiver] Unbekanntes Gelenk: {jointName}");
        }
    }
}
