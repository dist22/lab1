using ImplantsService.Models;
using Microsoft.EntityFrameworkCore;

namespace ImplantsService.Data.Context;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Implant> Implants { get; set; }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Implant>()
            .HasIndex(i => i.SerialNumber)
            .IsUnique();
        
        modelBuilder.Entity<Implant>()
            .HasIndex(i => i.DeviceType);
    }
}