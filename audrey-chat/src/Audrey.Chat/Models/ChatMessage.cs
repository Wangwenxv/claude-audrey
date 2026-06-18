using System.IO;

namespace Audrey.Chat.Models;

public sealed class ChatMessage
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Role { get; set; } = "assistant";
    public string Author { get; set; } = "奥黛丽";
    public string Text { get; set; } = string.Empty;
    public string Timestamp { get; set; } = DateTime.Now.ToString("HH:mm:ss");
    public string Kind { get; set; } = "message";
    public string StreamKey { get; set; } = string.Empty;

    public bool IsUser => Role == "user";
    public bool IsStatus => Kind == "status" || Role == "system" || Role == "tool";
    public bool HasAvatarImage => !IsStatus;
    public string Avatar => IsUser ? "你" : IsStatus ? "•" : "奥";
    public string AvatarPath => Path.Combine(AppContext.BaseDirectory, "Assets", IsUser ? "avat2.png" : "avat.png");
    public string BubbleBackground => IsUser ? "#E7F3F0" : IsStatus ? "#FFF7E8" : "#FFFDF8";
    public string BubbleBorder => IsUser ? "#A8CEC7" : IsStatus ? "#D6B36A" : "#D8E8E4";
    public string HorizontalAlignment => IsUser ? "Right" : "Left";
}
