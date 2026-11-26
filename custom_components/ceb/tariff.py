"""CEB residential tariff cost estimate.

Inclining-block tariff: consumption is split into bands, each band priced per kWh,
"per month or part thereof". Rates are national (gazetted). The integration picks the
band set from the account's live `tariff` field, so it estimates for any residential
tariff, important for publishing to other accounts.

Source: The Mauritius Government Gazette, 30 April 2026, Appendix I
"Tariff 110A, 110, 120, 140 and 150C for residential consumers" (pp. 2215-2216).
  - "Tariff 110A shall remain unchanged" -> 110A keeps the prior schedule (below), min Rs 31.
  - 110 / 120 / 140 revised to the rates below (higher than the pre-2026 schedule), new min charges.
  - 110 = declared load <= 300 W; 120 = 301-5000 W; 140 = > 5000 W.
  - 150C = Time-of-Use (flat per-kWh by time-of-day), NOT an inclining block -> see TOU_150C;
    monthly_cost() returns None for it because it needs an hourly split, not a single total.
Residential electricity in Mauritius is VAT-exempt, so EXTRAS_PCT is 0 until a bill says otherwise
(a real bill may still add a small CEB levy / fuel-price adjustment; calibrate from one if so).
Update knob: if CEB re-gazettes, edit BANDS / MIN_CHARGE / TOU_150C / EFFECTIVE.
"""
from __future__ import annotations

EFFECTIVE = "Gazette 30 April 2026, Appendix I (110A unchanged)"

# band = (kWh size or None for "all additional", Rs/kWh).
_110A = [  # unchanged by the 2026 gazette
    (25, 2.18), (25, 3.04), (25, 3.28), (25, 5.45), (100, 6.15),
    (50, 7.02), (50, 7.90), (None, 8.77),
]
_REVISED = [  # 110 / 120 / 140, gazette 30 April 2026
    (25, 3.63), (25, 5.04), (25, 5.45), (25, 6.27), (100, 7.07),
    (50, 8.07), (50, 9.09), (200, 12.03), (500, 12.28), (500, 12.55),
    (500, 12.80), (None, 13.06),
]
BANDS: dict[str, list[tuple[int | None, float]]] = {
    "110A": _110A, "110": _REVISED, "120": _REVISED, "140": _REVISED,
}
MIN_CHARGE: dict[str, float] = {"110A": 31.0, "110": 50.60, "120": 211.60, "140": 424.35}
EXTRAS_PCT: dict[str, float] = {t: 0.0 for t in BANDS}

# Fixed monthly meter rental, added on top of the energy charge (CEB).
# Single-phase Rs 20.00; three-phase (direct connection) Rs 120.00.
# Reconciles the one real bill exactly: 244 kWh 110A (Rs 1272.63) + 20.00 = Rs 1292.63 ~= Rs 1293 paid.
# NOTE: connection fee (Rs 750) and security deposit (110A/110 Rs 200, 120 Rs 600, 140 Rs 1200) are
# ONE-TIME charges at account setup, NOT monthly -> deliberately excluded from monthly_cost.
METER_RENTAL = {"single": 20.00, "three": 120.00}
DEFAULT_PHASE = "single"  # this account; confirmed by the Rs 1293 bill reconciliation

# Tariff 150C Time-of-Use (Rs/kWh by clock band), min charge Rs 424.35. Not block-based.
TOU_150C = {"day_04_18": 7.53, "evening_18_21": 11.50, "night_21_04": 4.60, "min_charge": 424.35}

DEFAULT_TARIFF = "110A"


def normalize(code: str | None) -> str:
    """Map the API tariff field (e.g. 'TARIF_110A', 'tariff 110') to a band key."""
    c = (code or "").upper().replace("TARIF_", "").replace("TARIFF", "").strip()
    return c or DEFAULT_TARIFF


def monthly_cost(
    kwh: float, tariff: str = DEFAULT_TARIFF, phase: str = DEFAULT_PHASE
) -> float | None:
    """Estimated Rs for `kwh` units in one billing month on `tariff`:
    max(energy on the band ladder, minimum charge) + fixed monthly meter rental.
    None for unknown tariffs and for 150C (Time-of-Use needs an hourly split, not a total)."""
    t = normalize(tariff)
    bands = BANDS.get(t)
    if bands is None:
        return None
    rem, energy = kwh, 0.0
    for size, rate in bands:
        take = rem if size is None else min(rem, size)
        if take <= 0:
            break
        energy += take * rate
        rem -= take
    energy *= 1.0 + EXTRAS_PCT.get(t, 0.0)
    total = max(energy, MIN_CHARGE.get(t, 0.0)) + METER_RENTAL.get(phase, 0.0)
    return round(total, 2)


def demo() -> None:
    assert monthly_cost(0, "110A") == 31.0 + 20.0  # min charge + meter rental
    assert monthly_cost(10, "140") == 424.35 + 20.0
    assert monthly_cost(25, "110A") == round(25 * 2.18 + 20.0, 2)
    # reconcile the one real bill: 244 kWh on 110A single-phase
    assert monthly_cost(244, "110A") == 1292.63, monthly_cost(244, "110A")
    assert monthly_cost(300, "110A") < monthly_cost(300, "110")
    assert monthly_cost(500, "110A") > monthly_cost(300, "110A") > monthly_cost(100, "110A")
    assert monthly_cost(100, "150C") is None and monthly_cost(100, "COMMERCIAL") is None
    assert monthly_cost(100, "TARIF_110A") == monthly_cost(100, "110A")
    print("tariff.demo OK  110A:230kWh=Rs", monthly_cost(230.107, "110A"),
          "| 244kWh=Rs", monthly_cost(244, "110A"), "(bill was Rs1293)")


if __name__ == "__main__":
    demo()
