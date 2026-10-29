using ImplantsService;
using ImplantsService.Data.Context;
using ImplantsService.Middleware;
using Microsoft.EntityFrameworkCore;
using Prometheus;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddDatabase(builder.Configuration);
builder.Services.AddMetricsCollector();

var app = builder.Build();

app.UseSwagger();
app.UseSwaggerUI();

app.UseMetricServer(); 
app.UseMiddleware<PrometheusMetricsMiddleware>();

app.UseCustomObservability();

app.MapControllers();

using (var scope = app.Services.CreateScope())
{
    var dbContext = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    dbContext.Database.Migrate();
}

app.Run();