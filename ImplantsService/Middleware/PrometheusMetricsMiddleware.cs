using System.Diagnostics;
using Prometheus;

namespace ImplantsService.Middleware;

public class PrometheusMetricsMiddleware
{
    private readonly RequestDelegate _next;

    private static readonly Counter RequestCounter = Metrics.CreateCounter(
        "http_requests_total",
        "Total number of HTTP requests.",
        new CounterConfiguration { LabelNames = new[] { "method", "path_template", "code" } });

    private static readonly Histogram RequestDuration = Metrics.CreateHistogram(
        "http_request_duration_seconds",
        "Duration of HTTP requests in seconds.",
        new HistogramConfiguration
        {
            LabelNames = new[] { "method", "path_template", "code" },
            Buckets = new[] { 0.002, 0.005, 0.010, 0.020, 0.050, 0.100, 0.200, 0.500, 1.000, 2.000 }
        });

    private static readonly Gauge RequestsInFlight = Metrics.CreateGauge(
        "http_requests_in_flight",
        "Number of requests currently processing.");

    public PrometheusMetricsMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        if (context.Request.Path.StartsWithSegments("/metrics"))
        {
            await _next(context);
            return;
        }

        RequestsInFlight.Inc();
        var stopwatch = Stopwatch.StartNew();

        try
        {
            await _next(context);
        }
        finally
        {
            stopwatch.Stop();
            RequestsInFlight.Dec();

            var endpoint = context.GetEndpoint();
            var pathTemplate = endpoint != null && endpoint is RouteEndpoint routeEndpoint
                ? routeEndpoint.RoutePattern.RawText
                : context.Request.Path.Value;

            if (!string.IsNullOrEmpty(pathTemplate) && !pathTemplate.StartsWith("/"))
            {
                pathTemplate = "/" + pathTemplate;
            }
            if (string.IsNullOrEmpty(pathTemplate))
            {
                pathTemplate = "/";
            }

            var method = context.Request.Method;
            var statusCode = context.Response.StatusCode.ToString();

            RequestCounter.WithLabels(method, pathTemplate, statusCode).Inc();
            RequestDuration.WithLabels(method, pathTemplate, statusCode).Observe(stopwatch.Elapsed.TotalSeconds);
        }
    }
}