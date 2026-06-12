using UnityEngine;
using System;

public class InspectionStationController : MonoBehaviour
{
    // ── Inspector ────────────────────────────────────────────────
    [Header("Servo Motor")]
    [Tooltip("Drag the rotating part of your 3D model here")]
    public Transform servoArm;

    [Tooltip("The local axis the servo rotates around (usually Y or Z)")]
    public Vector3 rotationAxis = Vector3.up;

    [Tooltip("Offset if the model's zero-angle doesn't match ROS zero")]
    public float angleOffsetDeg = 0f;

    [Header("ROS Topics")]
    public string cmdTopic = "/inspection_servo_cmd";
    public string stateTopic = "/inspection_servo_state";
    public string cmdMsgType = "std_msgs/msg/Float32";
    public string stateMsgType = "std_msgs/msg/Float32";

    [Header("Simulation / Mock")]
    public bool useMockData = false;

    // ── Internal state ───────────────────────────────────────────
    private Quaternion _initialRot;
    private float _currentAngleDeg = 0f;
    private bool _advertised = false;

    // ── Unity lifecycle ─────────────────────────────────────────
    void Start()
    {
        if (servoArm == null)
        {
            // Try to auto-find by name
            Transform found = transform.Find("ServoMotorArm");
            if (found != null) servoArm = found;
            else Debug.LogWarning("[InspectionStation] ServoArm not assigned and not found by name!");
        }

        if (servoArm != null)
            _initialRot = servoArm.localRotation;

        StartCoroutine(ConnectToRos());
    }

    // ── ROS connection ────────────────────────────────────────────
    System.Collections.IEnumerator ConnectToRos()
    {
        while (RosConnector.Instance == null) yield return new WaitForSeconds(0.5f);
        while (!RosConnector.Instance.IsConnected) yield return new WaitForSeconds(0.5f);

        // Advertise command topic (Unity → ROS)
        RosConnector.Instance.Advertise(cmdTopic, cmdMsgType);
        _advertised = true;

        // Subscribe to state topic (ROS → Unity)
        RosConnector.Instance.Subscribe(stateTopic, stateMsgType, OnServoStateReceived);

        Debug.Log("[InspectionStation] Connected to ROS.");
    }

    // ── Receive live angle from the physical servo ────────────────
    void OnServoStateReceived(string json)
    {
        // rosbridge wraps Float32 as: {"op":"publish","topic":"...","msg":{"data":45.0}}
        Float32Msg packet = JsonUtility.FromJson<Float32Msg>(json);
        if (packet?.msg == null) return;

        float angleDeg = packet.msg.data;  // angle in degrees from ROS

        // Enqueue on main thread (json callback is on background thread)
        _currentAngleDeg = angleDeg;
        ApplyAngle(angleDeg);
    }

    // ── Apply angle to the 3D model ───────────────────────────────
    void ApplyAngle(float angleDeg)
    {
        if (servoArm == null) return;

        float total = angleDeg + angleOffsetDeg;
        servoArm.localRotation = _initialRot * Quaternion.AngleAxis(total, rotationAxis);
    }

    // ── Public API: command the servo from UI or other scripts ────
    /// <summary>Send a target angle (degrees) to the physical servo via ROS.</summary>
    public void CommandServo(float targetAngleDeg)
    {
        if (useMockData)
        {
            Debug.Log($"[MOCK] Servo command: {targetAngleDeg}°");
            ApplyAngle(targetAngleDeg);   // Preview in editor
            return;
        }

        if (!_advertised || RosConnector.Instance == null) return;

        // std_msgs/Float32 JSON: {"data": 45.0}
        string json = $"{{\"data\":{targetAngleDeg.ToString("F2", System.Globalization.CultureInfo.InvariantCulture)}}}";
        RosConnector.Instance.Publish(cmdTopic, cmdMsgType, json);
        Debug.Log($"[InspectionStation] Servo command sent: {targetAngleDeg}°");
    }
}

// ── Data structs matching rosbridge JSON ─────────────────────────────
[Serializable]
public class Float32Msg
{
    public string op;
    public string topic;
    public Float32Data msg;
}

[Serializable]
public class Float32Data
{
    public float data;
}