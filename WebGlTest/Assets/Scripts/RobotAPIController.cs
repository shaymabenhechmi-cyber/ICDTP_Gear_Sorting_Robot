using UnityEngine;
using UnityEngine.UI;
using TMPro;
using System.Collections;
using System;
using System.Threading.Tasks;

public class RobotAPIController : MonoBehaviour
{
    // ===================================================================
    // 1. EINSTELLUNGEN & VARIABLEN
    // ===================================================================

    [Header("Verbindungs-Modus")]
    [Tooltip("Wenn angehakt, werden Befehle nur simuliert (kein ROS n�tig)")]
    public bool useMockData = false;

    [Header("ROS Einstellungen")]
    // Der Topic-Name muss mit dem Subscriber auf dem Pi �bereinstimmen
    public string topicName = "/robot_cmd";
    // Der Typ muss exakt so hei�en wie in deinem ROS2-Paket
    public string messageType = "my_robot_interfaces/msg/RobotCommand";

    [Header("Robot Kinematik")]
    public float stepsPerDegree = 88.888f;

    [Header("Gelenke (Drag & Drop aus Hierarchy)")]
    public Transform joint1;
    public Transform joint2;
    public Transform joint3;
    public Transform joint4;
    public Transform[] gripperFingers;

    [Header("UI Elements - Koordinaten")]
    public TMP_InputField inputX;
    public TMP_InputField inputY;
    public TMP_InputField inputZ;
    public Button buttonMoveToPosition;

    [Header("UI Elements - Steuerung")]
    public Button buttonGripperOpen;
    public Button buttonGripperClose;
    public Button buttonHome;
    public Button buttonReset;
    public Button buttonEmergencyStop;
    public Slider sliderSpeed;
    public TextMeshProUGUI textSpeedValue;

    // ===================================================================
    // 2. INTERNER STATUS
    // ===================================================================

    private Quaternion initialRot1, initialRot2, initialRot3, initialRot4;
    private Quaternion[] initialFingerRots;

    private bool isGripperOpen = true;
    private float currentSpeed = 100f;
    private bool _hasAdvertised = false;

    // ===================================================================
    // 3. START & INITIALISIERUNG
    // ===================================================================

    void Start()
    {
        // Initiale Rotationen speichern
        if (joint1) initialRot1 = joint1.localRotation;
        if (joint2) initialRot2 = joint2.localRotation;
        if (joint3) initialRot3 = joint3.localRotation;
        if (joint4) initialRot4 = joint4.localRotation;

        if (gripperFingers != null)
        {
            initialFingerRots = new Quaternion[gripperFingers.Length];
            for (int i = 0; i < gripperFingers.Length; i++)
            {
                if (gripperFingers[i]) initialFingerRots[i] = gripperFingers[i].localRotation;
            }
        }

        // UI Event Listener
        if (buttonMoveToPosition) buttonMoveToPosition.onClick.AddListener(OnMoveToPositionClicked);
        if (buttonGripperOpen) buttonGripperOpen.onClick.AddListener(OnGripperOpenClicked);
        if (buttonGripperClose) buttonGripperClose.onClick.AddListener(OnGripperCloseClicked);
        if (buttonHome) buttonHome.onClick.AddListener(OnHomeClicked);
        if (buttonReset) buttonReset.onClick.AddListener(OnResetClicked);
        if (buttonEmergencyStop) buttonEmergencyStop.onClick.AddListener(OnEmergencyStopClicked);

        if (sliderSpeed)
        {
            sliderSpeed.onValueChanged.AddListener((val) => {
                currentSpeed = val;
                if (textSpeedValue) textSpeedValue.text = $"{val:F0} mm/s";
            });
        }

        // Advertise beim Start (Coroutine wartet auf Verbindung)
        StartCoroutine(AdvertiseOnConnect());
    }

    IEnumerator AdvertiseOnConnect()
    {
        // Warte auf RosConnector
        while (RosConnector.Instance == null) yield return new WaitForSeconds(0.5f);
        while (!RosConnector.Instance.IsConnected) yield return new WaitForSeconds(0.5f);

        RosConnector.Instance.Advertise(topicName, messageType);
        _hasAdvertised = true;
        Debug.Log($"[RobotAPIController] Topic '{topicName}' advertised.");
    }

    // ===================================================================
    // 4. UI EVENT HANDLER
    // ===================================================================

    public void OnMoveToPositionClicked()
    {
        float x = ParseFloat(inputX.text, 0);
        float y = ParseFloat(inputY.text, 200);
        float z = ParseFloat(inputZ.text, 100);

        SendRobotCommand(x, y, z, isGripperOpen);
    }

    public void OnGripperOpenClicked()
    {
        if (isGripperOpen) return; // Already open — skip duplicate command
        isGripperOpen = true;
        SendGripperCommand(true);
    }

    public void OnGripperCloseClicked()
    {
        if (!isGripperOpen) return; // Already closed — skip duplicate command
        isGripperOpen = false;
        SendGripperCommand(false);
    }

    public void OnHomeClicked()
    {
        Debug.Log("[RobotAPIController] HOME gesendet.");
        SendSpecialCommand("HOME");
    }

    public void OnResetClicked()
    {
        Debug.Log("[RobotAPIController] RESET (StallGuard Homing) gesendet.");
        SendSpecialCommand("RESET");
    }

    public void OnEmergencyStopClicked()
    {
        Debug.LogWarning("NOT-AUS GESENDET!");
        SendSpecialCommand("ESTOP");
    }

    // ===================================================================
    // 5. SEND LOGIC
    // ===================================================================

    void SendRobotCommand(float x, float y, float z, bool gripperOpen)
    {
        if (useMockData)
        {
            Debug.Log($"[MOCK] Sende an ROS -> Pos: {x}/{y}/{z}, Greifer: {gripperOpen}");
            return;
        }

        // Nachricht erstellen (passend zu my_robot_interfaces/msg/RobotCommand)
        RobotCommandMsg cmd = new RobotCommandMsg();
        cmd.base_id = "unity_web_client";
        cmd.gripper_state = gripperOpen;

        cmd.target_pose = new PoseMsg();
        cmd.target_pose.position = new PointMsg();

        // KOORDINATEN-TRANSFORMATION Unity (mm) -> ROS (m)
        // Unity: X-Rechts, Y-Oben, Z-Vorne
        // ROS:   X-Vorne, Y-Links, Z-Oben

        // Beispiel-Mapping (muss ggf. an deine URDF angepasst werden):
        cmd.target_pose.position.x = z / 1000f;   // Unity Z -> ROS X
        cmd.target_pose.position.y = -x / 1000f;  // Unity X -> ROS Y (negativ)
        cmd.target_pose.position.z = y / 1000f;   // Unity Y -> ROS Z

        // Orientierung: Greifer zeigt nach unten
        // (Hier nur statisch, k�nnte man dynamisch machen)
        cmd.target_pose.orientation = new QuaternionMsg { x = 1.0f, y = 0.0f, z = 0.0f, w = 0.0f }; // Beispiel: 180 deg um X

        string jsonMsg = JsonUtility.ToJson(cmd);

        // Advertise falls noch nicht geschehen
        if (!_hasAdvertised && RosConnector.Instance != null && RosConnector.Instance.IsConnected)
        {
            RosConnector.Instance.Advertise(topicName, messageType);
            _hasAdvertised = true;
        }

        // Publish (RosConnector buffert automatisch wenn nicht verbunden)
        if (RosConnector.Instance != null)
        {
            RosConnector.Instance.Publish(topicName, messageType, jsonMsg);
            Debug.Log($"[RobotAPIController] Gesendet: Pos({x},{y},{z}) -> ROS({cmd.target_pose.position.x:F3},{cmd.target_pose.position.y:F3},{cmd.target_pose.position.z:F3}) Greifer: {gripperOpen}");
        }
        else
        {
            Debug.LogWarning("[RobotAPIController] RosConnector nicht verf\u00fcgbar!");
        }
    }
    // ── Gripper command via base_id (no MoveIt planning) ────────
    void SendGripperCommand(bool open)
    {
        string command = open ? "GRIP_OPEN" : "GRIP_CLOSE";
        Debug.Log($"[RobotAPIController] Greifer: {command}");
        SendSpecialCommand(command);
    }

    // ── Special command (RESET / ESTOP / HOME) via base_id ──────
    void SendSpecialCommand(string command)
    {
        if (useMockData)
        {
            Debug.Log($"[MOCK] Spezieller Befehl: {command}");
            return;
        }

        RobotCommandMsg cmd = new RobotCommandMsg();
        cmd.base_id = command;  // Bridge erkennt RESET / ESTOP / HOME
        cmd.gripper_state = isGripperOpen;
        cmd.target_pose = new PoseMsg
        {
            position = new PointMsg { x = 0, y = 0, z = 0 },
            orientation = new QuaternionMsg { x = 0, y = 0, z = 0, w = 1 }
        };

        string jsonMsg = JsonUtility.ToJson(cmd);
        if (RosConnector.Instance != null)
        {
            if (!_hasAdvertised && RosConnector.Instance.IsConnected)
            {
                RosConnector.Instance.Advertise(topicName, messageType);
                _hasAdvertised = true;
            }
            RosConnector.Instance.Publish(topicName, messageType, jsonMsg);
            Debug.Log($"[RobotAPIController] Spezialbefehl gesendet: {command}");
        }
    }
    // Helper f�r Input Parsing
    float ParseFloat(string txt, float defaultVal = 0)
    {
        if (string.IsNullOrEmpty(txt)) return defaultVal;

        // Ersetze Komma durch Punkt f�r float.Parse
        txt = txt.Replace(",", ".");

        if (float.TryParse(txt, System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out float result))
        {
            return result;
        }
        return defaultVal;
    }
}

// ===================================================================
// 6. DATENSTRUKTUREN (m�ssen exakt zum ROS-JSON passen)
// ===================================================================

[Serializable]
public class RobotCommandMsg
{
    public string base_id;
    public PoseMsg target_pose;
    public bool gripper_state;
}

[Serializable]
public class PoseMsg
{
    public PointMsg position;
    public QuaternionMsg orientation;
}

[Serializable]
public class PointMsg
{
    public float x;
    public float y;
    public float z;
}

[Serializable]
public class QuaternionMsg
{
    public float x;
    public float y;
    public float z;
    public float w;
}

public class RobotStatus
{
    public int[] motor_positions;
}
