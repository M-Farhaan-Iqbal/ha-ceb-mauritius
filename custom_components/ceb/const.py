DOMAIN = "ceb"
BASE_URL = "https://mobile.ceb.mu/api/"

CONF_DEVICE_ID = "device_id"
CONF_PIN = "pin"
CONF_ACCOUNT = "account_number"
CONF_EMAIL = "email"
CONF_DISTRICT = "district"
CONF_LOCALITY = "locality"

# polling interval; CEB meter data changes at most monthly, dashboard syncs a few times/day
SCAN_INTERVAL_HOURS = 6

# planned outages. Primary source: MrSunshyne's hourly-updated open dataset (structured JSON,
# ISO times, today/future split). Fallback: scrape the CEB page directly. Changes slowly.
OUTAGE_DATASET_URL = (
    "https://raw.githubusercontent.com/MrSunshyne/mauritius-dataset-electricity"
    "/main/data/power-outages.latest.json"
)
OUTAGE_URL = "https://ceb.mu/customer-corner/power-outage-information"
OUTAGE_SCAN_HOURS = 6

# district key (as used on the CEB page) -> label
DISTRICTS = {
    "blackriver": "Black River",
    "flacq": "Flacq",
    "grandport": "Grand Port",
    "moka": "Moka",
    "pamplemousses": "Pamplemousses",
    "plainewilhems": "Plaines Wilhems",
    "portlouis": "Port Louis",
    "rivieredurempart": "Riviere du Rempart",
    "savanne": "Savanne",
    "rodrigues": "Rodrigues",
}
