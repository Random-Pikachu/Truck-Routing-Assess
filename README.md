# Spotter — weather-aware truck routing

Picks the safest truck route using the forecast for the hour the truck actually reaches each point on the road, not the weather at departure.

- **Live app:** https://spott-assessment.vercel.app
- **Walkthrough video:** https://youtu.be/-rvGPvx7ROA
- **API:** https://truck-routing-assess.vercel.app/api/health

## what it does

- you give it an origin, destination, departure time, load (lb) and a checkpoint interval (10 / 25 / 50 mi)
- it gets 3 truck routes and puts a checkpoint every N miles, each with an ETA and the forecast for that hour
- every checkpoint gets a risk level from the brief's table + load rules, routes are ranked and one is recommended with a one-line reason
- map shows the routes coloured by risk along the road, a checkpoint list, and a 0–48 h forecast heatmap slider

## how it works

```
origin / destination  → geocode (ORS)
                      → 3 truck routes (TomTom, ORS as fallback)
                      → checkpoints every N mi, ETA from the route's steps
                      → forecast at each checkpoint's ETA hour (Open-Meteo)
                      → risk per checkpoint (risk table + load rules)
                      → rank: drivable → fewest Severe mi → fewest High mi → lowest avg risk → shortest time
```

## decisions

| | what i did | why |
|---|---|---|
| routes | TomTom truck routing, with traffic for the departure hour and weight = load + 35,000 lb empty truck. fewer than 3 different roads → forced detours through points 25% / 50% to the side. ORS is the fallback | ORS alternatives only work under 100 km |
| "different" route | same road if 85% of it runs within ~1 mi of another route (checked both ways) | comparing totals only showed I-25 twice |
| ETA | departure + time along the route's steps, each stretch between two turns has its own duration | an average speed was off by up to 8 min, enough to read the wrong forecast hour |
| forecast hour | wind → nearest hour, rain / snow → the hour being driven, rain = rain + showers | open-meteo rain / snow are last-hour totals |
| missing forecast | the plan fails, never treated as Low. departure ≤ 14 days | unknown weather isn't safe weather |
| risk | worst of the wind / rain / snow bands, load rules can only raise it. edges as the table writes them (wind ≥ 55, rain > 1.00, snow > 3.0) | |
| ties *(my addition)* | Severe / High miles within 1 mi, avg risk within 0.05 = tie → next rule | checkpoint miles are estimates, small gaps are noise |
| end tolerance | a checkpoint within 1 mi of the destination is dropped | marks at 300 and 300.0000001 counted the same weather twice |
| trade-off | the reason says "…but it takes 5h 06m longer" when the safer pick is slower | kept the brief's order, but the cost is visible |
| heatmap | points every 25 mi along the routes ± 20 mi, 0.25° grid, all 49 hours fetched once | the slider only switches frames, no network calls |

## run it locally

needs python 3.12 + [uv](https://docs.astral.sh/uv/), node 20.19+, a free [OpenRouteService](https://openrouteservice.org/dev/#/signup) key and a free [TomTom](https://developer.tomtom.com/) key (optional).

```bash
# backend → http://127.0.0.1:8000
cd backend
echo "ORS_API_KEY=your-key" > .env
echo "TOMTOM_API_KEY=your-key" >> .env
uv sync
uv run python manage.py runserver

# frontend → http://localhost:5173 (vite proxies /api to django)
cd frontend
npm install
npm run dev
```

tests: `cd backend && uv run pytest` (388 tests, no network calls, ~2s)

production env vars: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` on the backend, `VITE_API_URL` on the frontend.

## stack

django 6 · python 3.12 · httpx · react 19 · vite · typescript · tailwind 4 · maplibre · TomTom · OpenRouteService · Open-Meteo · pytest
