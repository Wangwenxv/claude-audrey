# Audrey.Chat

WPF native chat shell for Audrey Hall. The Python desktop pet process owns the Claude session and launches this process as a lightweight native chat UI over stdio JSON Lines.

## Requirements

- .NET 8 SDK on Windows
- Windows Desktop Runtime is required for framework-dependent published builds

## Build

```powershell
dotnet build .\Audrey.Chat.sln -c Release
```

The Python host looks for the chat executable at:

```text
audrey-chat\src\Audrey.Chat\bin\Release\net8.0-windows\Audrey.Chat.exe
audrey-chat\src\Audrey.Chat\bin\Debug\net8.0-windows\Audrey.Chat.exe
```

You can also override the path with:

```powershell
$env:AUDREY_CHAT_EXE = "C:\path\to\Audrey.Chat.exe"
```

## IPC

Communication uses one JSON object per line over stdio.

WPF -> Python examples:

```json
{"type":"chat.ready"}
{"type":"message.send","text":"你好"}
{"type":"message.stop"}
{"type":"permission.respond","request_id":"...","allow":true}
```

Python -> WPF examples:

```json
{"type":"chat.show"}
{"type":"message.append","role":"assistant","text":"..."}
{"type":"status.update","text":"奥黛丽 正在思考..."}
{"type":"permission.request","request_id":"...","tool_name":"Bash","input":{}}
```
