# Cached TLEs

In-repo cache for reproducible offline runs. Source: CelesTrak public GP data.

Refresh:

```bash
python3 backend/scripts/fetch_tles.py
```

Selected NORAD IDs (mvp-thesis): 25544 (ISS), 48274 (CSS Tianhe), 43013 (NOAA 20).

`leo_constellation.tle` adds more public CelesTrak records (HST, Terra, Aqua, Landsat 8, Sentinel-2A/3A, Suomi NPP, MetOp-B) for the `leo-constellation` scenario.
