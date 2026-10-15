# Current fare and seat data

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
