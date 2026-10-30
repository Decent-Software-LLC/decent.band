#!/usr/bin/env python3
"""Build one GeoJSON feature per hometown from the Billboard artist CSV."""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "public/data/billboard-global-200-2023-2026/top_300_billboard_global_200_performers_2023_2026.csv"
OUTPUT_PATH = ROOT / "site-public/data/artists.geojson"
CACHE_PATH = ROOT / ".geocode-cache.json"
USER_AGENT = "decent.band hometown mapper (donnie@kjw3.llc)"

QUERY_OVERRIDES = {
    "Ahome (Ciudad Obregon), Sinaloa, Mexico": "Ciudad Obregon, Sinaloa, Mexico",
    "Chgo, Minnesota, USA": "Minnesota, USA",
    "Colombia (regional, city n/a)": "Colombia",
    "Italy (regional, city n/a)": "Italy",
    "Jalisco, Mexico (regional)": "Jalisco, Mexico",
    "K-pop supergroup (USA/South Korea)": "Seoul, South Korea",
    "Lithia (Tampa), Florida, USA": "Tampa, Florida, USA",
    "Mexico (regional, city n/a)": "Mexico",
    "Puerto Rico / Mexico (regional)": "Puerto Rico",
    "Saint-Maur-des-Fosses (Paris), France": "Saint-Maur-des-Fossés, France",
    "Sandy Bay, Saint Michael, Barbados": "Saint Michael, Barbados",
    "Sinaloa, Mexico (regional)": "Sinaloa, Mexico",
    "United States (regional, city n/a)": "United States",
    "Venezuela / Colombia (regional)": "Venezuela",
}


def geocode_query(hometown: str) -> str:
    query = QUERY_OVERRIDES.get(hometown, hometown)
    for suffix in (
        " (USA-based K-pop)",
        " (Greece-origin members)",
        " (Puerto Rican origin)",
    ):
        query = query.removesuffix(suffix)
    return query


def geocode(query: str) -> dict | None:
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1})
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        results = json.load(response)
    if not results:
        return None
    result = results[0]
    return {
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
        "display_name": result.get("display_name", query),
    }


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def artist_record(row: dict) -> dict:
    return {
        "rank": int(row["rank"]),
        "name": row["artist_name"],
        "slug": row["artist_id_or_slug"],
        "genre": row["genre"],
        "country": row["home_country"],
        "notes": row["notes"],
        "weeksCharted": int(row["weeks_charted"]),
        "chartedSongs": int(row["charted_songs"]),
        "peakPosition": int(row["peak_position"]),
    }


def main() -> int:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["home_city"]].append(artist_record(row))

    cache = load_cache()
    features = []
    unresolved = []

    for index, hometown in enumerate(sorted(grouped), start=1):
        query = geocode_query(hometown)
        location = cache.get(query)
        if location is None:
            print(f"[{index}/{len(grouped)}] Geocoding {query}", flush=True)
            try:
                location = geocode(query)
            except Exception as error:  # Network errors are reported and retried on the next run.
                print(f"  error: {error}", file=sys.stderr, flush=True)
                location = None
            if location:
                cache[query] = location
                save_cache(cache)
            time.sleep(1.1)

        if not location:
            unresolved.append(hometown)
            continue

        artists = sorted(grouped[hometown], key=lambda artist: artist["rank"])
        countries = sorted({artist["country"] for artist in artists})
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [location["longitude"], location["latitude"]],
                },
                "properties": {
                    "hometown": hometown,
                    "countries": ", ".join(countries),
                    "artistCount": len(artists),
                    "topRank": min(artist["rank"] for artist in artists),
                    "artists": json.dumps(artists, ensure_ascii=False, separators=(",", ":")),
                    "geocodeLabel": location["display_name"],
                },
            }
        )

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "artistCount": len(rows),
            "hometownCount": len(features),
            "unresolvedHometowns": unresolved,
            "source": CSV_PATH.name,
        },
        "features": features,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(features)} hometowns and {sum(feature['properties']['artistCount'] for feature in features)} artists to {OUTPUT_PATH}",
        flush=True,
    )
    if unresolved:
        print("Unresolved hometowns:", *unresolved, sep="\n- ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
