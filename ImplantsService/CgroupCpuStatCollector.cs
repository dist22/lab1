using System.IO;
using Prometheus;
using Microsoft.Extensions.Hosting;

namespace ImplantsService; 

public class CgroupCpuStatCollector : BackgroundService
{
    private static readonly Counter NrPeriods = Metrics.CreateCounter(
        "cpu_nr_periods_total", "Number of enforcement intervals.");
    private static readonly Counter NrThrottled = Metrics.CreateCounter(
        "cpu_nr_throttled_total", "Number of throttled intervals.");

    private long _lastNrPeriods = 0;
    private long _lastNrThrottled = 0;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            UpdateMetrics();
            await Task.Delay(5000, stoppingToken);
        }
    }

    private void UpdateMetrics()
    {
        // cgroup v2 (сучасний Docker)
        string path = "/sys/fs/cgroup/cpu.stat"; 
        
        // cgroup v1 (fallback)
        if (!File.Exists(path)) path = "/sys/fs/cgroup/cpu,cpuacct/cpu.stat"; 

        if (File.Exists(path))
        {
            try
            {
                var lines = File.ReadAllLines(path);
                long currentNrPeriods = 0;
                long currentNrThrottled = 0;

                foreach (var line in lines)
                {
                    if (line.StartsWith("nr_periods"))
                        long.TryParse(line.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1], out currentNrPeriods);
                    else if (line.StartsWith("nr_throttled"))
                        long.TryParse(line.Split(' ', StringSplitOptions.RemoveEmptyEntries)[1], out currentNrThrottled);
                }

                if (currentNrPeriods > _lastNrPeriods && _lastNrPeriods > 0)
                    NrPeriods.Inc(currentNrPeriods - _lastNrPeriods);
                
                if (currentNrThrottled > _lastNrThrottled && _lastNrThrottled > 0)
                    NrThrottled.Inc(currentNrThrottled - _lastNrThrottled);

                _lastNrPeriods = currentNrPeriods > 0 ? currentNrPeriods : _lastNrPeriods;
                _lastNrThrottled = currentNrThrottled > 0 ? currentNrThrottled : _lastNrThrottled;
            }
            catch { /* Ігноруємо помилки читання */ }
        }
    }
}