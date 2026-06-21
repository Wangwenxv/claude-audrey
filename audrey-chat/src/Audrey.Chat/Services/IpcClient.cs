using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text;
using System.IO;
using System.Windows;

namespace Audrey.Chat.Services;

public sealed class IpcClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly CancellationTokenSource _cts = new();
    private readonly StreamReader? _stdinReader;
    private readonly StreamWriter? _stdoutWriter;

    public event Action<JsonElement>? EventReceived;

    public IpcClient()
    {
        try
        {
            var stdin = Console.OpenStandardInput();
            _stdinReader = new StreamReader(stdin, new UTF8Encoding(false), detectEncodingFromByteOrderMarks: true);
        }
        catch
        {
            _stdinReader = null;
        }

        try
        {
            var stdout = Console.OpenStandardOutput();
            _stdoutWriter = new StreamWriter(stdout, new UTF8Encoding(false))
            {
                AutoFlush = true,
            };
        }
        catch
        {
            _stdoutWriter = null;
        }
    }

    public void Start()
    {
        if (_stdinReader is not null)
        {
            _ = Task.Run(ReadLoopAsync);
        }
        Send(new { type = "chat.ready" });
    }

    public void Stop()
    {
        _cts.Cancel();
    }

    public void Send(object payload)
    {
        if (_stdoutWriter is null)
        {
            return;
        }
        try
        {
            var json = JsonSerializer.Serialize(payload, JsonOptions);
            _stdoutWriter.WriteLine(json);
        }
        catch
        {
            // IPC failures are non-fatal for the UI shell.
        }
    }

    private async Task ReadLoopAsync()
    {
        if (_stdinReader is null)
        {
            return;
        }
        while (!_cts.IsCancellationRequested)
        {
            string? line;
            try
            {
                line = await _stdinReader.ReadLineAsync(_cts.Token).ConfigureAwait(false);
            }
            catch
            {
                break;
            }

            if (line is null)
            {
                break;
            }

            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            try
            {
                using var document = JsonDocument.Parse(line);
                var clone = document.RootElement.Clone();
                Application.Current.Dispatcher.Invoke(() => EventReceived?.Invoke(clone));
            }
            catch
            {
                // Ignore malformed host messages and keep the chat window alive.
            }
        }
    }
}
