namespace ImplantsService.Models;

public class Implant
{
    public Guid Id { get; set; }
    public string PatientCode { get; set; } = string.Empty;
    public string DeviceType { get; set; } = string.Empty;
    public string Manufacturer { get; set; } = string.Empty;
    public string SerialNumber { get; set; } = string.Empty;
    public DateTime InstallationDate { get; set; }
    public int LifespanYears { get; set; }
}