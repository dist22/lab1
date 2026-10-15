using System.ComponentModel.DataAnnotations;

namespace ImplantsService.DTOs;

public class ImplantDto
{
    [Required]
    public string PatientCode { get; set; } = string.Empty;
    
    [Required]
    public string DeviceType { get; set; } = string.Empty;
    
    [Required]
    public string Manufacturer { get; set; } = string.Empty;
    
    [Required]
    public string SerialNumber { get; set; } = string.Empty;
    
    [Required]
    public DateTime InstallationDate { get; set; }
    
    [Required]
    [Range(1, 30, ErrorMessage = "Термін служби має бути від 1 до 30 років.")]
    public int LifespanYears { get; set; }
}