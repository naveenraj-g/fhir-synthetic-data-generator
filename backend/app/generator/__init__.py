"""Framework-free synthetic FHIR generation library. Importing this package
registers the built-in connectors, slicers and sinks."""

from app.generator.connectors import static_fixtures as _static_fixtures  # noqa: F401
from app.generator.connectors import synthea as _synthea  # noqa: F401
from app.generator.sinks import builtin as _sinks  # noqa: F401
from app.generator.slicers import builtin as _slicers  # noqa: F401
from app.generator.slicers import episodes as _episodes  # noqa: F401
