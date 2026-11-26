# CEB Mauritius — Home Assistant integration

<img src="custom_components/ceb/icon.svg" width="96" align="right" alt="CEB Mauritius">

Unofficial Home Assistant integration for **CEB (Central Electricity Board) Mauritius**, using the
MoKouran mobile app backend. Brings your electricity account into Home Assistant: balance, meter
reading, consumption (hourly / daily / monthly) and an estimated bill on your tariff.

> Not affiliated with or endorsed by CEB. Reverse-engineered from the MoKouran app for personal use.
> No warranty. Use at your own risk.

## Features

Sensors (`sensor.ceb_<account>_*`):

| Sensor | What |
|---|---|
| `amount_due` | Account balance (Rs) |
| `bill_due_date` | Bill due date |
| `last_meter_reading` | Latest meter reading |
| `last_reading_date` | Date of that reading |
| `last_consumption` | kWh of the last completed billing period (12-month `history` attribute) |
| `daily_consumption` | Latest day kWh (30-day `history` attribute) |
| `latest_day_total` | Latest complete day, 24-hour `profile` attribute |
| `month_consumption` | kWh in the current open billing period (from the last meter read) |
| `estimated_month_cost` | Estimated Rs for the current period (inclining-block tariff + meter rental) |
| `year_consumption` | Sum of the last 12 months (kWh) |
| `estimated_year_cost` | Estimated Rs over 12 months (monthly `history` attribute) |
| `tariff` | Tariff code (e.g. 110A) |

Polls every 6 hours (CEB data lags ~1–2 days); retries in 15 min after a failure.

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add this repo, category **Integration**.
2. Install **CEB Mauritius**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → CEB Mauritius**.

## Setup

Choose **Register with my MoKouran email**:

1. Enter the email you registered **in the MoKouran app** (this may differ from your CEB bill email),
   choose a 4-digit PIN for Home Assistant, and your contract number (on your bill).
2. CEB emails a one-time code; enter it.

Home Assistant registers itself as its own MoKouran device (its own device ID + that PIN), separate
from your phone. The **Advanced** option accepts an existing device ID + PIN directly.

Common errors:
- *No MoKouran app user for that email* — use the email registered in the MoKouran app.
- *The code was rejected* — re-request and retry; codes expire.

## Tariff & cost estimate

Costs are **estimates** from the gazetted CEB residential tariffs (110A / 110 / 120 / 140; 150C
Time-of-Use is not costed), picked automatically from your account's tariff code, plus the fixed
monthly meter rental. One-time charges (connection fee, security deposit) are excluded. A CEB levy or
fuel-price adjustment, if any on your bill, is not included — see `custom_components/ceb/tariff.py`
to calibrate from a real bill. VAT is not applied (residential electricity is VAT-exempt in Mauritius).

## API notes

The MoKouran backend is a LoopBack 3 REST API at `https://mobile.ceb.mu/api/`. Full reverse-engineering
notes: [`custom_components/ceb/CEB_API.md`](custom_components/ceb/CEB_API.md).

## License

MIT — see [LICENSE](LICENSE).
