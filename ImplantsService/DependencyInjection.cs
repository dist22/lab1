using ImplantsService.Data.Context;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace ImplantsService;

public static class DependencyInjection
{
    public static IServiceCollection AddDatabase(this IServiceCollection services, IConfiguration configuration)
    {
        var baseConnectionString = configuration.GetConnectionString("DefaultConnection");

        var dbPoolSizeStr = Environment.GetEnvironmentVariable("DB_POOL_SIZE");
        int dbPoolSize = int.TryParse(dbPoolSizeStr, out int ps) ? ps : 15;

        var connStringBuilder = new NpgsqlConnectionStringBuilder(baseConnectionString)
        {
            MaxPoolSize = dbPoolSize
        };

        services.AddDbContextPool<AppDbContext>(options =>
            options.UseNpgsql(connStringBuilder.ConnectionString));

        return services;
    }
    
    public static IServiceCollection AddMetricsCollector(this IServiceCollection services)
    {
        services.AddHostedService<CgroupCpuStatCollector>();
        return services;
    }
}