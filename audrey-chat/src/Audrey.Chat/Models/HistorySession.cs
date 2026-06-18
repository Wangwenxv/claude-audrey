namespace Audrey.Chat.Models;

public sealed class HistorySession
{
    public string SessionId { get; set; } = string.Empty;
    public string Title { get; set; } = "新对话";
    public string Summary { get; set; } = string.Empty;
    public string Timestamp { get; set; } = string.Empty;
    public bool IsActive { get; set; }
}
