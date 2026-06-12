using UnityEngine;

[ExecuteAlways]
public class CanvasAutoScaler : MonoBehaviour
{
    [Header("Settings")]
    public Vector3 playModeScale = Vector3.one;
    public float editModeScaleFactor = 0.001f;

    void Update()
    {
        if (Application.isPlaying)
        {
            if (transform.localScale != playModeScale)
            {
                transform.localScale = playModeScale;
            }
        }
        else
        {
            Vector3 targetScale = playModeScale * editModeScaleFactor;
            if (Vector3.Distance(transform.localScale, targetScale) > 0.00001f)
            {
                transform.localScale = targetScale;
            }
        }
    }
}
