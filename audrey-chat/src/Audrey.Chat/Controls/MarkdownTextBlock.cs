using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace Audrey.Chat.Controls;

public sealed class MarkdownTextBlock : TextBlock
{
    public static readonly DependencyProperty MarkdownProperty = DependencyProperty.Register(
        nameof(Markdown),
        typeof(string),
        typeof(MarkdownTextBlock),
        new PropertyMetadata(string.Empty, OnMarkdownChanged));

    private static readonly Regex InlinePattern = new(@"(\*\*[^*\n]+\*\*|`[^`\n]+`)", RegexOptions.Compiled);

    public string Markdown
    {
        get => (string)GetValue(MarkdownProperty);
        set => SetValue(MarkdownProperty, value);
    }

    private static void OnMarkdownChanged(DependencyObject target, DependencyPropertyChangedEventArgs args)
    {
        if (target is MarkdownTextBlock block)
        {
            block.RenderMarkdown(args.NewValue as string ?? string.Empty);
        }
    }

    private void RenderMarkdown(string markdown)
    {
        Inlines.Clear();
        var lines = markdown.Replace("\r\n", "\n").Split('\n');
        var inCode = false;
        foreach (var rawLine in lines)
        {
            var line = rawLine.TrimEnd('\r');
            if (line.TrimStart().StartsWith("```", StringComparison.Ordinal))
            {
                inCode = !inCode;
                continue;
            }

            if (inCode)
            {
                Inlines.Add(new Run(line) { FontFamily = new FontFamily("Consolas"), Background = Brushes.AntiqueWhite });
                Inlines.Add(new LineBreak());
                continue;
            }

            var heading = Regex.Match(line, @"^\s{0,3}#{1,6}\s+(.+?)\s*$");
            if (heading.Success)
            {
                Inlines.Add(new Run(heading.Groups[1].Value) { FontWeight = FontWeights.SemiBold });
                Inlines.Add(new LineBreak());
                continue;
            }

            var bullet = Regex.Match(line, @"^\s*[-*]\s+(.+?)\s*$");
            if (bullet.Success)
            {
                Inlines.Add(new Run("• ") { Foreground = Brushes.DarkCyan });
                AddInlineRuns(bullet.Groups[1].Value);
                Inlines.Add(new LineBreak());
                continue;
            }

            AddInlineRuns(line);
            Inlines.Add(new LineBreak());
        }
    }

    private void AddInlineRuns(string text)
    {
        var last = 0;
        foreach (Match match in InlinePattern.Matches(text))
        {
            if (match.Index > last)
            {
                Inlines.Add(new Run(text[last..match.Index]));
            }

            var token = match.Value;
            if (token.StartsWith("**", StringComparison.Ordinal) && token.EndsWith("**", StringComparison.Ordinal))
            {
                Inlines.Add(new Run(token[2..^2]) { FontWeight = FontWeights.SemiBold });
            }
            else if (token.StartsWith('`') && token.EndsWith('`'))
            {
                Inlines.Add(new Run(token[1..^1]) { FontFamily = new FontFamily("Consolas"), Background = Brushes.AntiqueWhite });
            }
            else
            {
                Inlines.Add(new Run(token));
            }
            last = match.Index + match.Length;
        }

        if (last < text.Length)
        {
            Inlines.Add(new Run(text[last..]));
        }
    }
}
