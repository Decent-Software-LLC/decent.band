#!/usr/bin/env python3
"""Merge Billboard artist metadata and build one GeoJSON feature per hometown."""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOP_300_PATH = ROOT / "public/data/billboard-global-200-2023-2026/top_300_billboard_global_200_performers_2023_2026.csv"
ALL_ARTISTS_PATH = ROOT / "public/data/billboard-global-200-2023-2026/all-953-enrichment/all_953_performers_metadata.csv"
OUTPUT_PATH = ROOT / "site-public/data/artists.geojson"
CACHE_PATH = ROOT / ".geocode-cache.json"
USER_AGENT = "decent.band hometown mapper (donnie@kjw3.llc)"

COUNTRY_ALIASES = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium",
    "BG": "Bulgaria", "BR": "Brazil", "Brasil": "Brazil", "CA": "Canada",
    "CO": "Colombia", "DE": "Germany", "DK": "Denmark", "DO": "Dominican Republic",
    "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "ID": "Indonesia", "IE": "Ireland", "IN": "India",
    "IT": "Italy", "Icelandic": "Iceland", "JM": "Jamaica", "JP": "Japan",
    "KR": "South Korea", "MA": "Morocco", "MX": "Mexico", "New Jersey": "United States",
    "NL": "Netherlands", "NO": "Norway", "NZ": "New Zealand", "PH": "Philippines",
    "PR": "Puerto Rico", "RO": "Romania", "RU": "Russia", "SE": "Sweden",
    "Sofia": "Bulgaria", "TH": "Thailand", "TR": "Turkey", "US": "United States",
    "VE": "Venezuela",
}

CITY_ALIASES = {
    "Bronx": "New York", "Brooklyn": "New York", "Queens": "New York",
    "New York (The Bronx)": "New York", "New York (Brooklyn)": "New York",
    "New York (Harlem)": "New York", "Bronx (New York)": "New York",
    "Brooklyn (New York)": "New York", "Queens (New York)": "New York",
    "Pinner (London)": "London", "Tottenham (London)": "London",
    "London (Shepherd's Bush)": "London", "Saint-Maur-des-Fosses (Paris)": "Paris",
    "Barcelona (Vilassar de Mar)": "Barcelona",
    "Sant Climent de Llobregat (Barcelona)": "Barcelona",
    "Ahome (Ciudad Obregon)": "Ciudad Obregon", "Cali (Santiago de Cali)": "Cali",
    "Lithia (Tampa)": "Tampa", "Hawaii (Hilo)": "Hilo",
    "Chgo": "Chicago", "Culiacán": "Culiacan", "The Bronx": "New York",
}

QUERY_OVERRIDES = {
    "Slater-Brownfield, United States": "West Virginia, United States",
}

CITY_COUNTRY_OVERRIDES = {
    "Bogota": "Colombia", "Delhi": "India", "Johannesburg": "South Africa",
    "Los Angeles": "United States", "New Delhi": "India", "New York": "United States",
    "Osaka": "Japan", "Zagreb": "Croatia",
}


def normalized_artist_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.casefold())


def normalized_country(value: str) -> str:
    value = value.strip()
    if value in {"", "None"}:
        return "Unknown"
    return COUNTRY_ALIASES.get(value, value)


def normalized_city(value: str, country: str) -> str:
    value = value.strip()
    if value in {"", "None"}:
        if country == "Unknown":
            return "Location unknown"
        return f"{country} (regional, city n/a)"
    value = CITY_ALIASES.get(value, value)
    if value.endswith("(regional"):
        value += ")"
    return value


def hometown_label(city: str, country: str) -> str:
    if city == "Location unknown":
        return city
    if "regional" in city or "city n/a" in city:
        if city.casefold().startswith(country.casefold()):
            return city
        return f"{city}, {country}"
    return f"{city}, {country}"


def geocode_query(hometown: str) -> str:
    if hometown == "Location unknown":
        return hometown
    if hometown in QUERY_OVERRIDES:
        return QUERY_OVERRIDES[hometown]
    query = hometown.replace(" (regional, city n/a)", "").replace(" (regional)", "")
    if query.startswith("K-pop supergroup"):
        return "Seoul, South Korea"
    if " / " in query:
        return query.split(" / ", 1)[0]
    return query


def geocode(query: str) -> dict | None:
    if query == "Location unknown":
        return {"latitude": 0.0, "longitude": 0.0, "display_name": query}
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


def optional_int(value: str | None) -> int | None:
    return int(value) if value not in {None, ""} else None


def artist_record(metadata: dict, chart: dict | None, rank: int) -> dict:
    return {
        "rank": rank,
        "name": metadata["artist_name"].strip(),
        "slug": metadata["artist_id_or_slug"].strip(),
        "genre": metadata["genre"].strip(),
        "country": normalized_country(metadata["home_country"]),
        "notes": metadata["notes"].strip() or "No additional notes available.",
        "weeksCharted": optional_int(chart.get("weeks_charted") if chart else None),
        "chartedSongs": optional_int(chart.get("charted_songs") if chart else None),
        "peakPosition": optional_int(chart.get("peak_position") if chart else None),
    }


def main() -> int:
    with TOP_300_PATH.open(newline="", encoding="utf-8-sig") as source:
        top_rows = list(csv.DictReader(source))
    with ALL_ARTISTS_PATH.open(newline="", encoding="utf-8-sig") as source:
        metadata_rows = list(csv.DictReader(source))

    chart_by_name = {normalized_artist_name(row["artist_name"]): row for row in top_rows}
    unique_artists = {}
    duplicate_names = []
    for rank, row in enumerate(metadata_rows, start=1):
        key = normalized_artist_name(row["artist_name"])
        if key in unique_artists:
            duplicate_names.append(row["artist_name"])
            continue
        unique_artists[key] = (rank, row)

    grouped = defaultdict(list)
    for key, (rank, row) in unique_artists.items():
        chart = chart_by_name.get(key)
        country = normalized_country(chart["home_country"] if chart else row["home_country"])
        source_city = chart["home_city"].split(",", 1)[0] if chart else row["home_city"]
        city = normalized_city(source_city, country)
        country = CITY_COUNTRY_OVERRIDES.get(city, country)
        hometown = hometown_label(city, country)
        grouped[hometown].append(artist_record(row, chart, rank))

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
            except Exception as error:
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
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [location["longitude"], location["latitude"]]},
            "properties": {
                "hometown": hometown,
                "countries": ", ".join(countries),
                "artistCount": len(artists),
                "topRank": min(artist["rank"] for artist in artists),
                "artists": json.dumps(artists, ensure_ascii=False, separators=(",", ":")),
                "geocodeLabel": location["display_name"],
            },
        })

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "artistCount": len(unique_artists),
            "hometownCount": len(features),
            "duplicateArtistsRemoved": duplicate_names,
            "unresolvedHometowns": unresolved,
            "sources": [TOP_300_PATH.name, ALL_ARTISTS_PATH.name],
        },
        "features": features,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mapped_count = sum(feature["properties"]["artistCount"] for feature in features)
    print(f"Wrote {len(features)} hometowns and {mapped_count} artists to {OUTPUT_PATH}", flush=True)
    print(f"Removed {len(duplicate_names)} duplicate artist rows", flush=True)
    if unresolved:
        print("Unresolved hometowns:", *unresolved, sep="\n- ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
