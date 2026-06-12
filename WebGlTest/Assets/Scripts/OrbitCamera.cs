using UnityEngine;

public class OrbitCamera : MonoBehaviour
{
    [Header("Kamera Einstellungen")]
    [SerializeField] private Transform target;
    [SerializeField] private float distance = 1f;
    [SerializeField] private float minDistance = 0.2f;
    [SerializeField] private float maxDistance = 5f; // Erhöht für mehr Spielraum
    [SerializeField] private float defaultHeight = 2; // später noch kamera anheben

    [Header("Geschwindigkeiten")]
    [SerializeField] private float rotationSpeed = 5f;
    [SerializeField] private float zoomSpeed = 25f;    // Deutlich erhöht für spürbaren Zoom
    [SerializeField] private float panSpeed = 10f;      // Von 0.3 auf 5 erhöht

    [Header("View-Abstände (pro Button)")]
    [SerializeField] private float frontViewDistance = 8f;
    [SerializeField] private float topViewDistance = 12f;
    [SerializeField] private float sideViewDistance = 8f;
    [SerializeField] private float isometricViewDistance = 10f;

    [Header("Angle Limits")]
    [SerializeField] private float minVerticalAngle = -80f;
    [SerializeField] private float maxVerticalAngle = 80f;

    private float currentX = 0f;
    private float currentY = 30f;
    private Vector3 offset = Vector3.zero;

    private float targetX;
    private float targetY;
    private float targetDistance;
    private Vector3 targetOffset;
    private bool isTransitioning = false;
    private float transitionSpeed = 5f;

    void Start()
    {
        if (target == null)
        {
            GameObject robot = GameObject.Find("Robot");
            if (robot != null) target = robot.transform;
        }
        ResetCamera();
    }

    void LateUpdate()
    {
        if (target == null) return;

        HandleInput();
        UpdateTransitions();
        UpdateCameraPosition();
    }

    void HandleInput()
    {
        // Transition abbrechen, wenn der Nutzer manuell eingreift
        if (Input.GetMouseButtonDown(0) || Input.GetMouseButtonDown(1) || Mathf.Abs(Input.GetAxis("Mouse ScrollWheel")) > 0.01f)
        {
            isTransitioning = false;
        }

        if (isTransitioning) return;

        // Linksklick: Rotation (nur wenn kein 3D-Objekt gedraggt wird)
        if (Input.GetMouseButton(0) && !TargetDragController.IsDragging)
        {
            currentX += Input.GetAxis("Mouse X") * rotationSpeed;
            currentY -= Input.GetAxis("Mouse Y") * rotationSpeed;
            currentY = Mathf.Clamp(currentY, minVerticalAngle, maxVerticalAngle);
        }

        // Rechtsklick: Panning (Verschieben)
        if (Input.GetMouseButton(1))
        {
            // Wir multiplizieren mit der Distanz, damit das Panning 
            // sich bei weitem Zoom nicht "lahm" anfühlt
            float factor = distance * 0.2f; 
            float h = -Input.GetAxis("Mouse X") * panSpeed * factor;
            float v = -Input.GetAxis("Mouse Y") * panSpeed * factor;
            offset += transform.right * h * Time.deltaTime;
            offset += transform.up * v * Time.deltaTime;
        }

        // Mausrad: Zoom
        float scroll = Input.GetAxis("Mouse ScrollWheel");
        if (Mathf.Abs(scroll) > 0.001f)
        {
            distance -= scroll * zoomSpeed;
            distance = Mathf.Clamp(distance, minDistance, maxDistance);
        }

        if (Input.GetKeyDown(KeyCode.R)) ResetCamera();
    }

    // Rest des Skripts (UpdateTransitions, UpdateCameraPosition, View Buttons) bleibt logisch gleich wie vorher
    // ... (hier die bestehenden Methoden einfügen oder einfach das ganze File ersetzen)
    
    void UpdateTransitions()
    {
        if (!isTransitioning) return;
        currentX = Mathf.LerpAngle(currentX, targetX, Time.deltaTime * transitionSpeed);
        currentY = Mathf.Lerp(currentY, targetY, Time.deltaTime * transitionSpeed);
        distance = Mathf.Lerp(distance, targetDistance, Time.deltaTime * transitionSpeed);
        offset = Vector3.Lerp(offset, targetOffset, Time.deltaTime * transitionSpeed);

        if (Mathf.Abs(currentX - targetX) < 0.1f && Mathf.Abs(distance - targetDistance) < 0.1f)
            isTransitioning = false;
    }

    void UpdateCameraPosition()
    {
        Quaternion rotation = Quaternion.Euler(currentY, currentX, 0);
        Vector3 lookAtPoint = target.position + offset;
        transform.position = lookAtPoint + (rotation * Vector3.back * distance);
        transform.LookAt(lookAtPoint);
    }

    public void SetFrontView() => StartTransition(0f, 20f, frontViewDistance, Vector3.zero);
    public void SetTopView() => StartTransition(0f, 89f, topViewDistance, Vector3.zero);
    public void SetSideView() => StartTransition(90f, 20f, sideViewDistance, Vector3.zero);
    public void SetIsometricView() => StartTransition(45f, 35f, isometricViewDistance, Vector3.zero);

    void StartTransition(float rotX, float rotY, float dist, Vector3 newOffset)
    {
        targetX = rotX; targetY = rotY; targetDistance = dist; targetOffset = newOffset;
        isTransitioning = true;
    }

    public void ResetCamera()
    {
        currentX = 0f; currentY = 20f; distance = 1f; offset = Vector3.zero;
        isTransitioning = false;
    }
}