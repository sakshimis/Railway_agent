# Current fare and seat data

## RapidAPI PNR connection for the selected provider

The passenger support page can call the **GET `/getPNRStatus/{pnr}`** endpoint shown in the RapidAPI playground. This is a third-party provider, not proof of an official IRCTC integration. The request is made by Python on the server; the API key is never added to `web/app.js` or committed to Git.

In RapidAPI, open the PNR endpoint's **Code snippet** and copy its `X-RapidAPI-Host` value. Review the provider's plan and terms. In the PowerShell window you will use to start the app, set the values below, replacing the placeholders with your own values. Do **not** send the key in chat or upload a screenshot that reveals it.

```powershell
$env:RAPIDAPI_HOST = "HOST_FROM_RAPIDAPI_CODE_SNIPPET"
$env:RAPIDAPI_KEY = "YOUR_PRIVATE_RAPIDAPI_KEY"
$env:RAPIDAPI_PATH_PNR = "/getPNRStatus/{pnrNumber}"
.\.venv\Scripts\python.exe app.py
```

The path variable is optional for this PNR endpoint; it is shown to make the mapping explicit. Sign in as a passenger, open **Passenger support → Check PNR status**, and enter a current 10-digit PNR you are allowed to use. The app only displays a live result when the provider returns usable data. For `success: false` (including “FLUSHED PNR / PNR NOT YET GENERATED”), it shows the provider's error instead. A `200 OK` HTTP response alone is not a successful PNR lookup. The fictional sample PNRs remain in a separate expandable demonstration.

**PNR access does not provide live fares, seats, train search or booking.** Those features stay unavailable unless you separately configure and verify suitable endpoints, response mappings and usage rights. The route and seat RapidAPI paths are intentionally blank by default because the selected PNR page does not document them.

## Train-number timetable endpoint

The same provider's code snippet shows `GET /schedule/{trainNo}`. The journey planner now has a separate **Know your train number?** form using that path. It uses the same `RAPIDAPI_HOST` and `RAPIDAPI_KEY` as PNR, so no additional secret is needed. The adapter accepts common `route`/`stations`/`schedule` stop arrays and displays only station names/codes and arrival/departure times. An unfamiliar response is reported as a mapping error rather than invented timetable data. A provider timetable does not by itself verify that the train runs on a particular travel date.

This is a train-number lookup, **not** a trains-between-stations API. The main route comparison still uses historical data until a separate documented route-search endpoint is connected.

## Route/class fare enquiry

The selected provider also documents `GET /fare` with `adults`, `from`, `to`, `class`, `children` and `quota` query fields. The planner has a separate fare-enquiry form using these exact fields. It uses the same server-side RapidAPI host and key. Its response contains `data.trains[]`, each with a `fares[]` entry for the requested class. The adapter displays valid per-train `total_fare` amounts sorted by fare and flags dynamic base fares.

The page accepts a travel date and displays it as the user's planning context. The provider request has **no train number or travel date** (the provider selects trains for the route), so the date does not affect the returned fares or verify that a train runs that day. Returned amounts are indicative, not dated ticket quotes. The provider says `dynamic_fare: true` entries show base prices rather than live dynamic prices. The response does not establish seat availability or permit booking.

The passenger page no longer sends people to an external railway website. Its own server has `/api/live-status` and `/api/live-search` endpoints. Without approved provider access, the page says that current fares and seats are unavailable and continues to show clearly labeled historical comparisons. This is an integration point, **not a working IRCTC connection**.

## How to obtain authorized data

IRCTC's [Train Information Enquiry Service (TIES) policy](https://contents.irctc.co.in/en/TIES_Policy.pdf) covers trains between stations, availability, fare, schedules and PNR enquiry. It describes registration of a service provider, eligibility, charges, an agreement and subsequent technical integration. It is not a free student API key. For a final-year project, ask your supervisor or institution whether it has an approved railway data partnership or a licensed academic sandbox. A commercial provider may offer a separate contract and test environment; confirm its permission to display current fares and seats before using it. Do not scrape consumer websites or use another party's credentials.

## Connect a provider after approval

`live_railway.py` keeps credentials on the Python server. It currently expects a provider gateway that accepts a bearer token and these URL query fields: `origin`, `destination`, `date` (YYYY-MM-DD) and `class` (for example `SL`). The response must be normalized to:

```json
{
  "as_of": "2026-10-15T12:00:00+05:30",
  "trains": [
    {
      "train_no": "12345",
      "name": "Example Express",
      "class": "SL",
      "fare_rupees": 750,
      "availability": "AVAILABLE",
      "departure": "18:30",
      "arrival": "09:40"
    }
  ]
}
```

Different providers use different authentication, fields and request formats. Update `live_railway.py` to match the provider's documentation and test it with that provider's sandbox before setting production credentials. Do not point this adapter directly at IRCTC without its issued API specification and authorization.

Set the endpoint and token as **private server environment variables**, then restart the app. Do not put the token in JavaScript, Git, a public `.env` file, or a screenshot. The endpoint must use HTTPS. Example variable names: `RAILWAY_LIVE_API_URL` and `RAILWAY_LIVE_API_TOKEN`.
