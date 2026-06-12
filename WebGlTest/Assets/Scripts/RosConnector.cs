using UnityEngine;
using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.IO;

public class RosConnector : MonoBehaviour
{
    public static RosConnector Instance { get; private set; }

    [Header("ROS Connection Settings")]
    public string rosIP = "127.0.0.1"; 
    public string rosPort = "9090";       

    private ClientWebSocket _socket = new ClientWebSocket();
    private CancellationTokenSource _cts = new CancellationTokenSource();

    private Dictionary<string, Action<string>> _subscribers = new Dictionary<string, Action<string>>();
    private HashSet<string> _advertisedTopics = new HashSet<string>();
    private List<string> _pendingMessages = new List<string>();
    private ConcurrentQueue<Action> _mainThreadQueue = new ConcurrentQueue<Action>();

    // Subscriber-Info für Re-Subscribe nach Reconnect
    private Dictionary<string, string> _subscriberTypes = new Dictionary<string, string>();

    [Header("Reconnect")]
    public float reconnectInterval = 5f;
    private bool _reconnecting = false;

    public bool IsConnected => _socket != null && _socket.State == WebSocketState.Open;

    void Awake()
    {
        if (Instance == null) Instance = this;
        else Destroy(gameObject);
        DontDestroyOnLoad(gameObject);
    }

    async void Start()
    {
        // Warte auf AppConfig, falls vorhanden
        float timeout = 3f;
        float waited = 0f;
        while (!AppConfig.IsLoaded && waited < timeout)
        {
            await Task.Delay(100);
            waited += 0.1f;
        }

        if (AppConfig.IsLoaded)
        {
            rosIP = AppConfig.RosIp;
            rosPort = AppConfig.RosPort;
            Debug.Log($"[RosConnector] Config geladen: {rosIP}:{rosPort}");
        }
        else
        {
            Debug.LogWarning($"[RosConnector] AppConfig nicht geladen, verwende Inspector-Werte: {rosIP}:{rosPort}");
        }

        await ConnectToRos();

        // Starte Reconnect-Coroutine
        StartCoroutine(ReconnectLoop());
    }

    void Update()
    {
        while (!_mainThreadQueue.IsEmpty)
        {
            if (_mainThreadQueue.TryDequeue(out var action)) action?.Invoke();
        }
    }

    public async Task ConnectToRos()
    {
        if (_socket.State == WebSocketState.Aborted || _socket.State == WebSocketState.Closed)
        {
            _socket.Dispose();
            _socket = new ClientWebSocket();
            _cts = new CancellationTokenSource();
        }

        string url = $"ws://{rosIP}:{rosPort}";
        Debug.Log($"[RosConnector] Versuche Verbindung zu {url} ...");

        try
        {
            await _socket.ConnectAsync(new Uri(url), _cts.Token);
            Debug.Log("<color=green>[RosConnector] Verbunden mit ROS!</color>");

            _ = ReceiveLoop();

            foreach (var msg in _pendingMessages)
            {
               await SendWebSocketMessageRaw(msg);
            }
            _pendingMessages.Clear();
        }
        catch (Exception e)
        {
            Debug.LogError($"[RosConnector] Verbindungsfehler: {e.Message}");
        }
    }

    // --- ADVERTISE ---
    public async void Advertise(string topic, string type)
    {
        if (_advertisedTopics.Contains(topic)) return;

        string advMsg = "{\"op\":\"advertise\",\"topic\":\"" + topic + "\", \"type\":\"" + type + "\"}";
        await SendWebSocketMessage(advMsg);
        _advertisedTopics.Add(topic);
        Debug.Log($"[RosConnector] Advertised: {topic} ({type})");
    }

    // --- SENDEN ---
    // Update: Sendet jetzt auch den Typ mit, um "advertise" implizit zu machen
    public async void Publish(string topic, string type, string jsonMessage)
    {
        // JSON Format mit Typ
        string rosPacket = "{\"op\":\"publish\",\"topic\":\"" + topic + "\", \"type\":\"" + type + "\",\"msg\":" + jsonMessage + "}";
        await SendWebSocketMessage(rosPacket);
    }

    public void PublishRaw(string topic, string type, string jsonMessage)
    {
        Publish(topic, type, jsonMessage);
    }

    // --- EMPFANGEN ---
    // Update: Nimmt jetzt auch den Typ entgegen
    public async void Subscribe(string topic, string type, Action<string> callback)
    {
        Debug.Log($"[RosConnector] Registriere Subscriber f�r: {topic} ({type})");

        if (!_subscribers.ContainsKey(topic)) 
            _subscribers.Add(topic, callback);
        else 
            _subscribers[topic] += callback;

        // Typ merken für Re-Subscribe nach Reconnect
        _subscriberTypes[topic] = type;

        // Nachricht senden oder vormerken - JETZT MIT TYPE
        string subMsg = "{\"op\":\"subscribe\",\"topic\":\"" + topic + "\", \"type\": \"" + type + "\"}";

        await SendWebSocketMessage(subMsg);
    }

    private async Task ReceiveLoop()
    {
        var buffer = new byte[81920]; 
        while (IsConnected && !_cts.IsCancellationRequested)
        {
            try
            {
                WebSocketReceiveResult result;
                using (var ms = new MemoryStream())
                {
                    do
                    {
                        result = await _socket.ReceiveAsync(new ArraySegment<byte>(buffer), _cts.Token);
                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, string.Empty, CancellationToken.None);
                            return;
                        }
                        ms.Write(buffer, 0, result.Count);
                    } 
                    while (!result.EndOfMessage);

                    if (result.MessageType == WebSocketMessageType.Text)
                    {
                        string json = Encoding.UTF8.GetString(ms.ToArray());
                        // Raw ROS Debug Log - aktiv fuer Diagnose
                        string debugJson = json.Length > 300 ? json.Substring(0, 300) + "..." : json;
                        Debug.Log($"[RosConnector RAW] Laenge: {json.Length} | Inhalt: {debugJson}");
                        _mainThreadQueue.Enqueue(() => ProcessIncomingMessage(json));
                    }
                }
            }
            catch (Exception) { break; }
        }
    }

    private void ProcessIncomingMessage(string json)
    {
        // Verbessertes Topic-Matching: Suche nach "topic":"/xyz" im JSON
        string parsedTopic = ExtractTopicFromJson(json);

        foreach (var kvp in _subscribers)
        {
            bool match = false;
            if (parsedTopic != null)
                match = (parsedTopic == kvp.Key);
            else
                match = json.Contains(kvp.Key); // Fallback

            if (match)
            {
                try
                {
                    kvp.Value?.Invoke(json);
                }
                catch (Exception e) 
                {
                    Debug.LogError($"[RosConnector] Callback Error for {kvp.Key}: {e.Message}");
                }
            }
        }
    }

    /// <summary>
    /// Extrahiert den Topic-Namen aus dem rosbridge JSON, ohne einen vollen JSON-Parser zu benötigen.
    /// </summary>
    private string ExtractTopicFromJson(string json)
    {
        // Suche nach "topic":" und extrahiere den Wert
        int idx = json.IndexOf("\"topic\"");
        if (idx < 0) return null;

        int colonIdx = json.IndexOf(':', idx + 7);
        if (colonIdx < 0) return null;

        int quoteStart = json.IndexOf('"', colonIdx + 1);
        if (quoteStart < 0) return null;

        int quoteEnd = json.IndexOf('"', quoteStart + 1);
        if (quoteEnd < 0) return null;

        // rosbridge escaped Slashes: "\/" -> "/" (JSON-Standard)
        string topic = json.Substring(quoteStart + 1, quoteEnd - quoteStart - 1);
        return topic.Replace("\\/", "/");
    }

    // --- RECONNECT ---
    private IEnumerator ReconnectLoop()
    {
        while (true)
        {
            yield return new WaitForSeconds(reconnectInterval);

            if (!IsConnected && !_reconnecting)
            {
                _reconnecting = true;
                Debug.Log("[RosConnector] Verbindung verloren. Versuche Reconnect...");

                var task = ConnectToRos();
                // Warte bis der Task fertig ist
                while (!task.IsCompleted)
                    yield return null;

                if (IsConnected)
                {
                    Debug.Log("<color=green>[RosConnector] Reconnect erfolgreich!</color>");
                    // Re-Subscribe für alle aktiven Subscriptions
                    foreach (var kvp in _subscriberTypes)
                    {
                        string subMsg = "{\"op\":\"subscribe\",\"topic\":\"" + kvp.Key + "\", \"type\": \"" + kvp.Value + "\"}";
                        var sendTask = SendWebSocketMessageRaw(subMsg);
                        while (!sendTask.IsCompleted)
                            yield return null;
                    }
                    // Re-Advertise
                    var topicsCopy = new List<string>(_advertisedTopics);
                    _advertisedTopics.Clear();
                    foreach (var topic in topicsCopy)
                    {
                        // Wir können den Type nicht wiederherstellen, aber das Advertise
                        // wird beim nächsten Publish erneut getriggert.
                    }
                }
                else
                {
                    Debug.LogWarning("[RosConnector] Reconnect fehlgeschlagen. Nächster Versuch in " + reconnectInterval + "s");
                }

                _reconnecting = false;
            }
        }
    }

    private async Task SendWebSocketMessage(string message)
    {
        if (IsConnected)
        {
            await SendWebSocketMessageRaw(message);
        }
        else
        {
            Debug.Log($"[RosConnector] Noch nicht verbunden. Nachricht gepuffert.");
            _pendingMessages.Add(message);
        }
    }

    private async Task SendWebSocketMessageRaw(string message)
    {
        var bytes = Encoding.UTF8.GetBytes(message);
        await _socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, _cts.Token);
    }

    private void OnDestroy()
    {
        _cts.Cancel();
        _socket?.Dispose();
    }
}
