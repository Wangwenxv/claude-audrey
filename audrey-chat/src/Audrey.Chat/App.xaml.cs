using System.Windows;

namespace Audrey.Chat;

public partial class App : Application
{
    private void Application_Startup(object sender, StartupEventArgs e)
    {
        var hidden = e.Args.Any(arg => string.Equals(arg, "--hidden", StringComparison.OrdinalIgnoreCase));
        var window = new MainWindow();
        MainWindow = window;
        if (hidden)
        {
            window.ShowActivated = false;
            window.Show();
            window.Hide();
        }
        else
        {
            window.Show();
        }
    }
}
