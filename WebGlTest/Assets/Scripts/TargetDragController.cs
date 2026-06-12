using UnityEngine;

public class TargetDragController : MonoBehaviour
{
    [Header("Verkn�pfungen")]
    public RobotAPIController apiController;
    public Transform robotBase;

    [Header("Einstellungen")]
    public float unityToMmScale = 1000f;

    private Vector3 mOffset;
    private float mZCoord;

    /// <summary>True solange der TCP-Ball gedraggt wird. Wird von OrbitCamera abgefragt.</summary>
    public static bool IsDragging { get; private set; }

    void OnMouseDown()
    {
        IsDragging = true;
        mZCoord = Camera.main.WorldToScreenPoint(gameObject.transform.position).z;
        mOffset = gameObject.transform.position - GetMouseAsWorldPoint();
    }

    private Vector3 GetMouseAsWorldPoint()
    {
        Vector3 mousePoint = Input.mousePosition;
        mousePoint.z = mZCoord;
        return Camera.main.ScreenToWorldPoint(mousePoint);
    }

    void OnMouseDrag()
    {
        transform.position = GetMouseAsWorldPoint() + mOffset;
        UpdateUI();
    }

    void OnMouseUp()
    {
        IsDragging = false;
        UpdateUI();
        if (apiController != null)
        {
            apiController.OnMoveToPositionClicked();
        }
    }

    private void UpdateUI()
    {
        if (apiController == null || robotBase == null) return;

        Vector3 localPos = robotBase.InverseTransformPoint(transform.position);

        float x_mm = localPos.x * unityToMmScale;
        float y_mm = localPos.y * unityToMmScale;
        float z_mm = localPos.z * unityToMmScale;

        if (apiController.inputX) apiController.inputX.text = x_mm.ToString("F0");
        if (apiController.inputY) apiController.inputY.text = y_mm.ToString("F0");
        if (apiController.inputZ) apiController.inputZ.text = z_mm.ToString("F0");
    }
}