using System.Collections.ObjectModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using Audrey.Chat.Models;
using Audrey.Chat.Services;
using Microsoft.Win32;

namespace Audrey.Chat;

public partial class MainWindow : Window
{
    private readonly IpcClient _ipc = new();
    private readonly List<string> _pendingImagePaths = new();
    private bool _allowClose;
    private bool _suppressHistorySelection;
    private bool _suppressSelectionEvents;
    private bool _uiReady;
    private string? _currentPermissionId;

    public ObservableCollection<ChatMessage> Messages { get; } = new();
    public ObservableCollection<HistorySession> HistorySessions { get; } = new();

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;
        AppendMessage("assistant", "WPF 原生聊天窗口已准备好。", "message", "奥黛丽", null);
        _ipc.EventReceived += HandleHostEvent;
        Loaded += (_, _) =>
        {
            _uiReady = true;
            BeginEntranceAnimation();
            _ipc.Start();
            _ipc.Send(new { type = "history.refresh" });
        };
        Closing += (_, args) =>
        {
            if (_allowClose)
            {
                return;
            }
            args.Cancel = true;
            Hide();
            _ipc.Send(new { type = "chat.hide" });
        };
    }

    private void HandleHostEvent(JsonElement evt)
    {
        var type = GetString(evt, "type");
        switch (type)
        {
            case "chat.show":
                Show();
                WindowState = WindowState.Normal;
                Activate();
                BeginEntranceAnimation();
                break;
            case "chat.close":
                _allowClose = true;
                _ipc.Stop();
                Application.Current.Shutdown();
                break;
            case "app.state":
                StatusText.Text = GetString(evt, "status_text") ?? StatusText.Text;
                SelectComboByTagSafe(ModeCombo, GetString(evt, "mode"));
                SelectComboByTagSafe(ConnectionCombo, GetString(evt, "connection_target"));
                UpdateAgentActivity(new AgentActivity
                {
                    Phase = "idle",
                    Title = "等待连接",
                    Detail = GetString(evt, "status_text") ?? "请选择思维链后点击连接。",
                    Badge = "READY",
                    Mode = ModeLabel(GetString(evt, "mode")),
                    Chain = ConnectionLabel(GetString(evt, "connection_target")),
                });
                break;
            case "status.update":
                var status = GetString(evt, "text") ?? string.Empty;
                StatusText.Text = status;
                UpdateAgentActivity(new AgentActivity
                {
                    Phase = GetString(evt, "phase") ?? "status",
                    Title = GetString(evt, "title") ?? status,
                    Detail = GetString(evt, "detail") ?? status,
                    Badge = GetString(evt, "badge") ?? "LIVE",
                    Mode = ModeLabel(GetString(evt, "mode")),
                    Chain = ConnectionLabel(GetString(evt, "connection_target")),
                    Timestamp = GetString(evt, "timestamp") ?? DateTime.Now.ToString("HH:mm:ss"),
                });
                break;
            case "session.state":
                SessionLabel.Text = GetString(evt, "label") ?? "当前会话：新对话";
                MarkActiveHistory(GetString(evt, "session_id") ?? string.Empty);
                break;
            case "history.items":
                ApplyHistory(evt);
                break;
            case "message.clear":
                Messages.Clear();
                break;
            case "message.append":
                AppendMessage(
                    GetString(evt, "role") ?? "assistant",
                    GetString(evt, "text") ?? string.Empty,
                    GetString(evt, "kind") ?? "message",
                    GetString(evt, "author"),
                    GetString(evt, "timestamp"),
                    GetString(evt, "stream_key"));
                break;
            case "permission.request":
                _currentPermissionId = GetString(evt, "request_id");
                var toolName = GetString(evt, "tool_name") ?? "未知工具";
                PermissionText.Text = $"请求执行工具：{toolName}";
                PermissionPanel.Visibility = Visibility.Visible;
                UpdateAgentActivity(new AgentActivity
                {
                    Phase = "permission",
                    Title = "等待你授予工具权限",
                    Detail = toolName,
                    Badge = "NEEDS ACTION",
                    Mode = ModeLabel(GetString(evt, "mode")),
                    Chain = ConnectionLabel(GetString(evt, "connection_target")),
                });
                break;
            case "error":
                AppendMessage("error", GetString(evt, "text") ?? "未知错误", "message", "错误", null);
                StatusText.Text = "发生错误";
                UpdateAgentActivity(new AgentActivity
                {
                    Phase = "error",
                    Title = "工作流中断",
                    Detail = GetString(evt, "text") ?? "未知错误",
                    Badge = "ERROR",
                });
                break;
        }
    }

    private void UpdateAgentActivity(AgentActivity activity)
    {
        var phase = activity.Phase.Trim().ToLowerInvariant();
        if (phase == "idle" || phase == "done")
        {
            AgentActivityPanel.Visibility = Visibility.Collapsed;
            return;
        }

        AgentActivityPanel.Visibility = Visibility.Visible;
        AgentActivityTitle.Text = string.IsNullOrWhiteSpace(activity.Title) ? "Agent 正在工作" : activity.Title;
        AgentActivityDetail.Text = string.IsNullOrWhiteSpace(activity.Detail) ? "正在处理当前请求" : activity.Detail;
        AgentActivityBadgeText.Text = string.IsNullOrWhiteSpace(activity.Badge) ? "LIVE" : activity.Badge;
        AgentActivityTime.Text = string.IsNullOrWhiteSpace(activity.Timestamp) ? DateTime.Now.ToString("HH:mm:ss") : activity.Timestamp;
        AgentActivityMode.Text = string.IsNullOrWhiteSpace(activity.Mode) ? string.Empty : $"模式：{activity.Mode}";
        AgentActivityChain.Text = string.IsNullOrWhiteSpace(activity.Chain) ? string.Empty : $"思维链：{activity.Chain}";
    }

    private void AppendMessage(string role, string text, string kind, string? author, string? timestamp, string? streamKey = null)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return;
        }
        var message = new ChatMessage
        {
            Role = role,
            Author = author ?? RoleLabel(role),
            Text = text,
            Kind = kind,
            Timestamp = timestamp ?? DateTime.Now.ToString("HH:mm:ss"),
            StreamKey = streamKey ?? string.Empty,
        };
        if (!string.IsNullOrWhiteSpace(message.StreamKey))
        {
            for (var index = 0; index < Messages.Count; index++)
            {
                if (string.Equals(Messages[index].StreamKey, message.StreamKey, StringComparison.Ordinal))
                {
                    Messages[index] = message;
                    if (_uiReady)
                    {
                        MessagesList.ScrollIntoView(message);
                    }
                    return;
                }
            }
        }
        Messages.Add(message);
        if (_uiReady)
        {
            MessagesList.ScrollIntoView(message);
        }
    }

    private void ApplyHistory(JsonElement evt)
    {
        _suppressHistorySelection = true;
        HistorySessions.Clear();
        if (!evt.TryGetProperty("items", out var items) || items.ValueKind != JsonValueKind.Array)
        {
            _suppressHistorySelection = false;
            return;
        }
        foreach (var item in items.EnumerateArray())
        {
            HistorySessions.Add(new HistorySession
            {
                SessionId = GetString(item, "session_id") ?? string.Empty,
                Title = GetString(item, "title") ?? "新对话",
                Summary = GetString(item, "summary") ?? string.Empty,
                Timestamp = GetString(item, "timestamp") ?? string.Empty,
                IsActive = GetBool(item, "is_active"),
            });
        }
        _suppressHistorySelection = false;
    }

    private void MarkActiveHistory(string sessionId)
    {
        foreach (var item in HistorySessions)
        {
            item.IsActive = !string.IsNullOrWhiteSpace(sessionId) && string.Equals(item.SessionId, sessionId, StringComparison.Ordinal);
        }
        HistoryList.Items.Refresh();
    }

    private void SendButton_Click(object sender, RoutedEventArgs e)
    {
        SendCurrentText();
    }

    private void StopButton_Click(object sender, RoutedEventArgs e)
    {
        _ipc.Send(new { type = "message.stop" });
    }

    private void ClearButton_Click(object sender, RoutedEventArgs e)
    {
        _pendingImagePaths.Clear();
        _ipc.Send(new { type = "message.clear" });
    }

    private void UploadButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "选择要发送的图片",
            Filter = "图片文件|*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp|所有文件|*.*",
            Multiselect = true,
        };
        if (dialog.ShowDialog(this) == true)
        {
            _pendingImagePaths.AddRange(dialog.FileNames);
            StatusText.Text = $"已添加 {_pendingImagePaths.Count} 张图片";
        }
    }

    private void AllowPermissionButton_Click(object sender, RoutedEventArgs e)
    {
        RespondPermission(true);
    }

    private void AlwaysAllowPermissionButton_Click(object sender, RoutedEventArgs e)
    {
        RespondPermission(true, always: true);
    }

    private void DenyPermissionButton_Click(object sender, RoutedEventArgs e)
    {
        RespondPermission(false);
    }

    private void NewSessionButton_Click(object sender, RoutedEventArgs e)
    {
        _pendingImagePaths.Clear();
        _ipc.Send(new { type = "session.new" });
    }

    private void ConnectButton_Click(object sender, RoutedEventArgs e)
    {
        _ipc.Send(new { type = "session.connect" });
    }

    private void RefreshHistoryButton_Click(object sender, RoutedEventArgs e)
    {
        _ipc.Send(new { type = "history.refresh" });
    }

    private void DeleteHistoryButton_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string sessionId && !string.IsNullOrWhiteSpace(sessionId))
        {
            _ipc.Send(new { type = "history.delete", session_id = sessionId });
        }
    }

    private void HistoryList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_suppressHistorySelection)
        {
            return;
        }
        if (HistoryList.SelectedItem is HistorySession item && !string.IsNullOrWhiteSpace(item.SessionId))
        {
            _ipc.Send(new { type = "session.resume", session_id = item.SessionId });
        }
    }

    private void MessagesList_PreviewMouseRightButtonDown(object sender, MouseButtonEventArgs e)
    {
        var source = e.OriginalSource as DependencyObject;
        while (source is not null && source is not ListBoxItem)
        {
            source = System.Windows.Media.VisualTreeHelper.GetParent(source);
        }
        if (source is ListBoxItem item)
        {
            item.IsSelected = true;
        }
    }

    private void CopyMessageMenuItem_Click(object sender, RoutedEventArgs e)
    {
        if (MessagesList.SelectedItem is ChatMessage item && !string.IsNullOrWhiteSpace(item.Text))
        {
            Clipboard.SetText(item.Text);
        }
    }

    private void ModeCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_uiReady || _suppressSelectionEvents || ModeCombo.SelectedItem is not ComboBoxItem item || item.Tag is not string mode)
        {
            return;
        }
        _ipc.Send(new { type = "mode.set", mode });
    }

    private void ConnectionCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!_uiReady || _suppressSelectionEvents || ConnectionCombo.SelectedItem is not ComboBoxItem item || item.Tag is not string target)
        {
            return;
        }
        if (string.IsNullOrWhiteSpace(target))
        {
            StatusText.Text = "请选择思维链后点击连接。";
            return;
        }
        _ipc.Send(new { type = "connection.set", target });
    }

    private void InputBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            e.Handled = true;
            SendCurrentText();
        }
    }

    private void InputBox_Pasting(object sender, DataObjectPastingEventArgs e)
    {
        if (Clipboard.ContainsImage())
        {
            var image = Clipboard.GetImage();
            if (image is not null)
            {
                var path = SaveClipboardImage(image);
                if (!string.IsNullOrWhiteSpace(path))
                {
                    _pendingImagePaths.Add(path);
                    StatusText.Text = $"已从剪贴板添加图片，共 {_pendingImagePaths.Count} 张";
                    e.CancelCommand();
                }
            }
        }
    }

    private void SendCurrentText()
    {
        var text = InputBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(text) && _pendingImagePaths.Count == 0)
        {
            return;
        }
        _ipc.Send(new { type = "message.send", text, image_paths = _pendingImagePaths.ToArray() });
        _pendingImagePaths.Clear();
        InputBox.Clear();
    }

    private void RespondPermission(bool allow, bool always = false)
    {
        if (string.IsNullOrWhiteSpace(_currentPermissionId))
        {
            PermissionPanel.Visibility = Visibility.Collapsed;
            return;
        }
        _ipc.Send(new { type = "permission.respond", request_id = _currentPermissionId, allow, always });
        _currentPermissionId = null;
        PermissionPanel.Visibility = Visibility.Collapsed;
    }

    private static string SaveClipboardImage(BitmapSource image)
    {
        try
        {
            var dir = Path.Combine(Path.GetTempPath(), "audrey-chat-images");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, $"clipboard-{DateTime.Now:yyyyMMdd-HHmmss-fff}.png");
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(image));
            using var stream = File.Create(path);
            encoder.Save(stream);
            return path;
        }
        catch
        {
            return string.Empty;
        }
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
        {
            ToggleMaximize();
            return;
        }
        DragMove();
    }

    private void MinimizeButton_Click(object sender, RoutedEventArgs e)
    {
        WindowState = WindowState.Minimized;
    }

    private void MaximizeButton_Click(object sender, RoutedEventArgs e)
    {
        ToggleMaximize();
    }

    private void CloseButton_Click(object sender, RoutedEventArgs e)
    {
        Hide();
        _ipc.Send(new { type = "chat.hide" });
    }

    private void ToggleMaximize()
    {
        WindowState = WindowState == WindowState.Maximized ? WindowState.Normal : WindowState.Maximized;
    }

    private void BeginEntranceAnimation()
    {
        Opacity = 0;
        var animation = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(140));
        BeginAnimation(OpacityProperty, animation);
    }

    private void SelectComboByTagSafe(ComboBox comboBox, string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag))
        {
            return;
        }
        _suppressSelectionEvents = true;
        try
        {
            foreach (var item in comboBox.Items)
            {
                if (item is ComboBoxItem comboItem && string.Equals(comboItem.Tag as string, tag, StringComparison.Ordinal))
                {
                    comboBox.SelectedItem = comboItem;
                    return;
                }
            }
        }
        finally
        {
            _suppressSelectionEvents = false;
        }
    }

    private static string? GetString(JsonElement evt, string property)
    {
        return evt.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;
    }

    private static bool GetBool(JsonElement evt, string property)
    {
        return evt.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.True;
    }

    private static string RoleLabel(string? role)
    {
        return role switch
        {
            "user" => "你",
            "assistant" => "奥黛丽",
            "system" => "状态",
            "tool" => "工具",
            "error" => "错误",
            _ => role ?? "奥黛丽",
        };
    }

    private static string ModeLabel(string? mode)
    {
        return mode switch
        {
            "default" => "默认陪伴",
            "acceptEdits" => "更改权限",
            "bypassPermissions" => "全部权限",
            _ => mode ?? string.Empty,
        };
    }

    private static string ConnectionLabel(string? target)
    {
        return target switch
        {
            "project" => "本项目 Claude",
            "system" => "本地 Claude",
            "auto" => "自动选择",
            _ => string.Empty,
        };
    }
}
