using ImplantsService.Data.Context;
using ImplantsService.DTOs;
using ImplantsService.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace ImplantsService.Controllers;

[ApiController]
public class ImplantsController(AppDbContext context) : ControllerBase
{
    [HttpPost("implants")]
    public async Task<IActionResult> Create([FromBody] ImplantDto dto)
    {
        if (await context.Implants.AnyAsync(i => i.SerialNumber == dto.SerialNumber))
        {
            return BadRequest(new { Error = "Серійний номер вже існує." });
        }

        var implant = new Implant
        {
            Id = Guid.NewGuid(),
            PatientCode = dto.PatientCode,
            DeviceType = dto.DeviceType,
            Manufacturer = dto.Manufacturer,
            SerialNumber = dto.SerialNumber,
            InstallationDate = dto.InstallationDate,
            LifespanYears = dto.LifespanYears
        };

        context.Implants.Add(implant);
        await context.SaveChangesAsync();

        return CreatedAtAction(nameof(GetById), new { id = implant.Id }, implant);
    }

    [HttpGet("implants")]
    public async Task<IActionResult> GetAll([FromQuery] int limit = 10, [FromQuery] int offset = 0, [FromQuery] string? deviceType = null)
    {
        limit = Math.Min(limit, 100); // Верхня межа ліміту
        var query = context.Implants.AsQueryable();

        if (!string.IsNullOrEmpty(deviceType))
        {
            query = query.Where(i => i.DeviceType == deviceType);
        }

        var totalCount = await query.CountAsync();
        var items = await query.OrderBy(i => i.Id)
                               .Skip(offset)
                               .Take(limit)
                               .ToListAsync();

        return Ok(new PagedResponse<Implant>
        {
            Items = items,
            TotalCount = totalCount
        });
    }

    [HttpGet("implants/{id}")]
    public async Task<IActionResult> GetById(Guid id)
    {
        var implant = await context.Implants.FindAsync(id);
        if (implant == null) return NotFound();
        return Ok(implant);
    }

    [HttpPut("implants/{id}")]
    public async Task<IActionResult> Update(Guid id, [FromBody] ImplantDto dto)
    {
        var implant = await context.Implants.FindAsync(id);
        if (implant == null) return NotFound();

        if (implant.SerialNumber != dto.SerialNumber && await context.Implants.AnyAsync(i => i.SerialNumber == dto.SerialNumber))
        {
            return BadRequest(new { Error = "Серійний номер вже використовується іншим записом." });
        }

        implant.PatientCode = dto.PatientCode;
        implant.DeviceType = dto.DeviceType;
        implant.Manufacturer = dto.Manufacturer;
        implant.SerialNumber = dto.SerialNumber;
        implant.InstallationDate = dto.InstallationDate;
        implant.LifespanYears = dto.LifespanYears;

        await context.SaveChangesAsync();
        return Ok(implant);
    }

    [HttpDelete("implants/{id}")]
    public async Task<IActionResult> Delete(Guid id)
    {
        var implant = await context.Implants.FindAsync(id);
        if (implant == null) return NotFound(); 

        context.Implants.Remove(implant);
        await context.SaveChangesAsync();
        return NoContent();
    }

    [HttpGet("healthz")]
    public async Task<IActionResult> HealthCheck()
    {
        var canConnect = await context.Database.CanConnectAsync();
        if (canConnect)
        {
            return Ok(new { Status = "Healthy" });
        }
        
        return StatusCode(503, new { Status = "Unhealthy", Error = "Database is not available" });
    }
}