# CEB MoKouran mobile API

Reverse-engineered from the MoKouran Android app (package `cebcustomerportal.cebcustomerportal`,
by Agileum) and confirmed against the live server. For the Home Assistant `ceb` integration.
No official documentation exists. Last verified: 2026-11-26.

- **Base URL:** `https://mobile.ceb.mu/api/`
- **Framework:** StrongLoop **LoopBack 3** (confirmed: error shapes, `/Model/method` routing,
  `Shared class "X" has no method handling ...` 404s, access token in `id` field).
- **Auth header:** `Authorization: <token>` (the raw token string, no `Bearer` prefix).
- **Content type:** `application/json`.
- **No Swagger:** `/explorer` and `/api/swagger.json` return 404 (disabled in production).
- `GET https://mobile.ceb.mu/` → `{"started":...,"uptime":...}` (health check, no auth).

## Auth model

- Each **device** is identified by a `deviceId` (the app uses a random GUID) and has its own
  4-digit `pinCode`. One account can have several devices (phone + HA = two devices).
- `loginPin` returns an access **token** with `ttl` 1209600 s (14 days). Store `deviceId` + `pinCode`
  and re-login on demand; the token is disposable.
- **One active token per device:** logging in again invalidates the previous token for that device.
  Do not run two clients on the same `deviceId`.
- Collection-level REST (`GET /api/ContractAccounts` etc.) needs an admin role → `401` for user tokens.
  Only the custom `getMy*` remote methods below are usable with a user token.

## Login

### POST `Accounts/loginPin`  (no auth)
Request: `{"deviceId": "<guid>", "pinCode": "1234"}`
Response `200`:
```json
{ "id": "<token>", "ttl": 1209600, "created": "...", "userId": 0,
  "appUser": { "firstname","lastname","fullName","contactEmail","contactPhone",
               "address","locality","isActivated","id", "contractaccounts": [], "role": {...} } }
```
Errors: `400 {"message":"deviceId is a required argument"}`; bad device/PIN → `400`/`401`/`404`.

### POST `Accounts/loginFingerprint`
Fingerprint variant; not used by this integration.

## Onboarding (register a new device, e.g. Home Assistant)

A fresh install has no `deviceId`/`pinCode`. Flow (routes confirmed, bodies from the APK — the
end-to-end run has **not** been executed on a live account yet, so field spelling may need a tweak):

1. Generate a random `deviceId` (GUID / uuid4 hex).
2. **POST `AppUsers/requestPinReRegistration`** `{"contactEmail": "<email>"}` → emails a one-time code.
   (`AppUsers/requestPinResetCode` is the reset-PIN variant.)
3. User reads the code from their email.
4. **POST `AppUsers/activateAccountOnAnotherDevice`**
   `{"contactEmail": "<email>", "code": "<code>", "pinCode": "<new 4-digit pin>", "deviceId": "<guid>"}`
   → binds the device. (`Accounts/createPinByValidationCode` is a related variant:
   `{email, validationCode, pin}`.)
5. **POST `Accounts/loginPin`** `{deviceId, pinCode}` → confirms and returns a token.

Empty-body POST to each route returns `400 INVALID_PARAMETERS` (route exists); a wrong name returns
`404 Shared class "AppUser" has no method handling POST /<name>`.

## Read methods (user token) — what the integration uses

### GET `ContractAccounts/getMyDashboardDetail?accountNumber=<acct>`
```json
{ "accountNumber","bpName","premAdd","mru","meter","tariff",
  "totalAmtDue": 0, "lastMtrDtl_Date","lastMtrDtl_Amt","lastMtrDtl_MtrNo","nextMtrRdngDate",
  "lastConsumptionDtl_consumption","lastConsumptionDtl_date",
  "consumptions": [ {"month":"NOV","currentConsumption":444,"previousConsumption":69}, "...x12" ] }
```

### GET `ContractAccounts/getMyContractAccounts`
List of accounts linked to the app user. **Returns `[]` here** — this account is not linked to the
app user (CEB's `Contract Account Lookup` is broken server-side), yet `getMyDashboardDetail` works when
the `accountNumber` is passed explicitly. So: do not rely on this to discover accounts; ask the user.

### GET `Meters/getMeterRegisterList?contractAcctNo=<acct>`
```json
[ {"id","customerCategory","amrFlag":false,"contractAcctNo","meterNo","registerName":"KWH-IMP","tariff"} ]
```
Pick `registerName == "KWH-IMP"` for import kWh.

### POST `EmsConsumptions/getEmsConsumptionData`  (interval data)
Request:
```json
{ "date":"YYYY-MM-DDT00:00:00.000Z", "graphType":"DAILY|MONTHLY|YEARLY",
  "meterNo":"<from register>", "regName":"KWH-IMP", "contractAcctNo":"<acct>",
  "duration1":"", "duration2":"", "intervalNo":12, "isAmr":true }
```
Response: `{"consumptionList":[{"date","times","val","dayNo","monthName","year", ...}], "percentageObj":{}}`

**Date conventions (important, see README fix):**
- `graphType: DAILY`, date D → returns **two days** (D-1 and D), 24 hourly rows each.
  `times` is the interval **end**: `"00:00"` on day D = 23:00–24:00 of D-1.
- `graphType: MONTHLY` → one row per day; the value dated D is the usage of **day D-1**.
  Sum of DAILY hourly rows for day X == MONTHLY value dated X+1.
- `isAmr: true` even though the register's `amrFlag` is false — the backend still returns interval data.

### GET `MasterInvoices/getMyInvoicesByContractAccount?accountNumber=<acct>`
List of invoices (`[]` when none). Row has `dueDate` among its fields.

### GET `MasterInvoices/getMyInvoicesByContractAccountAndPageDetail?accountNumber=<acct>&page=1&limit=10`
`{"invoiceList": [...], "isPaymentProcessing": false}`

## Other models seen in the app (not used here)

`EmsAlerts/getEmsalertConfigs`, `CallLogs/getMyCallLogs`, `AccountStatements/findOne`,
`FaultReportings` + `FaultTypes`/`FaultSubTypes`, `Feedbacks` + `FeedbackQuestions`/`FeedbackAnswers`,
`Businesspartners/registerBusinessPartner`, `ContractAccounts/generatePaymentURL` /
`generateMyTMoneyPayment[URL]`, `ContractAccounts/validateContractAcc` (needs auth; links an account),
`AppUsers/switchContractAccount`, `SmsActivationCodes/sendCodeBySMS`, `ActivationCodes/sendCodeByEmail`.

Note: `getEmsalertConfigs` and `getMyCallLogs` returned hundreds/thousands of rows here, i.e. they do
not look account-scoped — treat with caution, do not build features on them without checking.

## Rate / lockout

- Do not hammer. The web portal (`csp.ceb.mu`, a separate PHP system) locks login after ~3 bad tries;
  assume the mobile backend is similar for `loginPin`.
- The integration polls every 6 h (retry 15 min on failure).

## Tariff rates — not in the API

No tariff-rate endpoint exists (`Tariffs`, `TariffRates`, `Rates`, `Tariffs/getRates`,
`Tariffs/getMyTariff` all return `404 no method`). The account's tariff **code** is in
`getMyDashboardDetail.tariff` (e.g. `TARIF_110A`), but the Rs/kWh bands are not served.
Rates are national and gazetted; the integration hardcodes them in `tariff.py` from the CEB
domestic-tariff page and selects the band set by the account's tariff code. See README.

## One active device per account

`activateAccountOnAnotherDevice` **moves** the account to the new `deviceId` and invalidates the
previous one (confirmed 2026-11-27: after activating a second device, `loginPin` on the first returned
`404 USER_NOT_EXIST`). So HA and the phone app cannot both stay logged in. See README "Known limitation".
