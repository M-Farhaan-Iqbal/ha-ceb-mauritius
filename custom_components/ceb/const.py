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

# planned-outage scrape (ceb.mu website, not the MoKouran API); changes slowly
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
