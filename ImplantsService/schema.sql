CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory" (
    "MigrationId" character varying(150) NOT NULL,
    "ProductVersion" character varying(32) NOT NULL,
    CONSTRAINT "PK___EFMigrationsHistory" PRIMARY KEY ("MigrationId")
);

START TRANSACTION;
CREATE TABLE "Implants" (
    "Id" uuid NOT NULL,
    "PatientCode" text NOT NULL,
    "DeviceType" text NOT NULL,
    "Manufacturer" text NOT NULL,
    "SerialNumber" text NOT NULL,
    "InstallationDate" timestamp with time zone NOT NULL,
    "LifespanYears" integer NOT NULL,
    CONSTRAINT "PK_Implants" PRIMARY KEY ("Id")
);

CREATE INDEX "IX_Implants_DeviceType" ON "Implants" ("DeviceType");

CREATE UNIQUE INDEX "IX_Implants_SerialNumber" ON "Implants" ("SerialNumber");

INSERT INTO "__EFMigrationsHistory" ("MigrationId", "ProductVersion")
VALUES ('20261005183458_Initial', '9.0.20');

COMMIT;

