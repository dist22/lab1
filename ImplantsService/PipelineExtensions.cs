using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;

namespace ImplantsService;

public static class PipelineExtensions
{
    public static WebApplication UseCustomObservability(this WebApplication app)
    {
        var podName = Environment.GetEnvironmentVariable("POD_NAME") ?? Environment.MachineName;
        app.Use(async (context, next) =>
        {
            context.Response.Headers.Append("X-Pod", podName);
            await next.Invoke();
        });

        app.MapGet("/livez", () => Results.Ok("OK"));

        return app;
    }
}