using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class InspectionStationUI : MonoBehaviour
{
    public InspectionStationController stationController;
    public Slider servoSlider;
    public TMP_InputField angleInput;
    public Button sendButton;
    public TextMeshProUGUI liveAngleText;

    void Start()
    {
        if (sendButton)
            sendButton.onClick.AddListener(OnSendClicked);

        if (servoSlider)
            servoSlider.onValueChanged.AddListener(val => {
                if (angleInput) angleInput.text = val.ToString("F0");
            });
    }

    void OnSendClicked()
    {
        if (float.TryParse(angleInput.text, out float angle))
            stationController.CommandServo(angle);
    }

    // Call this from InspectionStationController (or poll in Update) to show live state
    public void UpdateLiveAngle(float deg)
    {
        if (liveAngleText) liveAngleText.text = $"Servo: {deg:F1}°";
    }
}