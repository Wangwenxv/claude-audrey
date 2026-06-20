namespace Audrey.Chat.Models;

public sealed class AgentActivity
{
    public string Phase { get; set; } = "idle";
    public string Title { get; set; } = string.Empty;
    public string Detail { get; set; } = string.Empty;
    public string Badge { get; set; } = "LIVE";
    public string Mode { get; set; } = string.Empty;
    public string Chain { get; set; } = string.Empty;
    public string Timestamp { get; set; } = DateTime.Now.ToString("HH:mm:ss");
}
