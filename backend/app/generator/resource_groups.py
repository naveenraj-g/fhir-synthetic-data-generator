"""Named categories of FHIR resource types, so a caller can ask for "administrative data" or "financial data"
without knowing resource names. Groups may overlap.

Every group member is a resource type Synthea v4.0.0's R4 exporter can write (read from the exporter's own code in the
jar): AllergyIntolerance, CarePlan, CareTeam, Claim, Condition, Coverage, Device, DiagnosticReport, DocumentReference,
Encounter, ExplanationOfBenefit, Goal, ImagingStudy, Immunization, Location, Media, Medication, MedicationAdministration,
MedicationRequest, Observation, Organization, Patient, Practitioner, PractitionerRole, Procedure, Provenance,
ServiceRequest, SupplyDelivery. Types Synthea never writes (RelatedPerson, MedicationDispense, ClaimResponse...)
are deliberately absent. Not every type appears in every record: it depends on what happened to the patient and on
Synthea's export settings."""

from app.generator.errors import InvalidSpecError

GROUPS: dict[str, tuple[str, ...]] = {
    "demographics": ("Patient",),
    "encounters": ("Encounter",),
    "conditions": ("Condition", "AllergyIntolerance"),
    "procedures": ("Procedure",),
    "medications": ("MedicationRequest", "MedicationAdministration", "Medication"),
    "immunizations": ("Immunization",),
    "observations": ("Observation",),
    "diagnostics": ("Observation", "DiagnosticReport", "ImagingStudy", "Media"),
    "orders": ("ServiceRequest",),
    "care_plans": ("CarePlan", "CareTeam", "Goal"),
    "documents": ("DocumentReference", "Provenance"),
    "devices_supplies": ("Device", "SupplyDelivery"),
    # Everything about the clinical content of the record (no billing, no providers, no audit trail).
    "clinical": (
        "Encounter", "Condition", "AllergyIntolerance", "Procedure", "MedicationRequest",
        "MedicationAdministration", "Medication", "Immunization", "Observation",
        "DiagnosticReport", "ImagingStudy", "Media", "ServiceRequest", "CarePlan", "CareTeam", "Goal",
        "DocumentReference", "Device", "SupplyDelivery",
    ),  # fmt: skip
    # Money: claims, what insurers paid, and the coverage behind them.
    "financial": ("Claim", "ExplanationOfBenefit", "Coverage"),
    # Who and where: providers, organizations and facilities (these live in Synthea's separate
    # hospital/practitioner bundles, not in the patient bundles).
    "administrative": ("Practitioner", "PractitionerRole", "Organization", "Location"),
}  # fmt: skip

# Resource types that Synthea only emits in its infrastructure bundles.
INFRASTRUCTURE_TYPES = frozenset(GROUPS["administrative"])


def expand_groups(names: list[str]) -> set[str]:
    out: set[str] = set()
    for name in names:
        if name not in GROUPS:
            raise InvalidSpecError(f"Unknown resource group '{name}'. Available: {sorted(GROUPS)}")
        out.update(GROUPS[name])
    return out
