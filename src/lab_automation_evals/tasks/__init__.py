"""Task definitions, in suite order."""

from . import (
    la01_serial_dilution,
    la02_normalize_plate,
    la03_cherry_pick,
    la04_find_the_error,
    la05_dye_qc,
    la06_run_log_triage,
)

ALL_TASKS = [
    la01_serial_dilution,
    la02_normalize_plate,
    la03_cherry_pick,
    la04_find_the_error,
    la05_dye_qc,
    la06_run_log_triage,
]
