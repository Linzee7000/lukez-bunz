"""Victorian school holidays and public holidays, shared by the report tools (and copied into data/run-history.json for the app)."""
from datetime import date

SCHOOL = [(date(2024, 9, 21), date(2024, 10, 6)), (date(2024, 12, 21), date(2025, 1, 27)),
          (date(2025, 4, 5), date(2025, 4, 21)), (date(2025, 6, 28), date(2025, 7, 13)), (date(2025, 9, 20), date(2025, 10, 5)), (date(2025, 12, 20), date(2026, 1, 27)),
          (date(2026, 4, 3), date(2026, 4, 19)), (date(2026, 6, 27), date(2026, 7, 12)), (date(2026, 9, 19), date(2026, 10, 4)), (date(2026, 12, 19), date(2027, 1, 27))]
PH = {date(2024, 11, 5), date(2024, 12, 25), date(2024, 12, 26), date(2025, 1, 1), date(2025, 1, 27), date(2025, 3, 10), date(2025, 4, 18), date(2025, 4, 21), date(2025, 4, 25), date(2025, 6, 9), date(2025, 9, 26), date(2025, 11, 4),
      date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 1, 26), date(2026, 3, 9), date(2026, 4, 3), date(2026, 4, 6), date(2026, 6, 8), date(2026, 9, 25), date(2026, 11, 3),
      date(2026, 12, 25), date(2026, 12, 28), date(2027, 1, 1), date(2027, 1, 26)}

def hol(d):
    return d in PH or any(a <= d <= b for a, b in SCHOOL)
