#!/usr/bin/env python3
"""
Download F1 historical data from Jolpica/Ergast API.
Run this on the HOST machine (not in the sandbox) since the sandbox blocks outbound HTTPS.
Usage: python3 download_f1_data.py
"""
import json, os, time
from urllib.request import urlopen, Request
from urllib.error import URLError

BASE_URL = "https://api.jolpi.ca/ergast/f1"
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

INNER_KEYS = {
    "results": "Results",
    "qualifying": "QualifyingResults",
    "sprint": "SprintResults"
}

def fetch_page(season, dtype, offset, limit=100):
    url = f"{BASE_URL}/{season}/{dtype}.json?limit={limit}&offset={offset}"
    req = Request(url, headers={"User-Agent": "F1Predictor/1.0"})
    try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except URLError as e:
        print(f"  ERROR fetching {url}: {e}")
        return None

def fetch_all(season, dtype):
    print(f"\nFetching {season}/{dtype}...")
    inner_key = INNER_KEYS[dtype]
    
    # Get total
    first = fetch_page(season, dtype, 0, limit=1)
    if first is None:
        return {"season": season, "type": dtype, "races": []}
    total = int(first["MRData"]["total"])
    print(f"  total={total}")
    
    if total == 0:
        return {"season": season, "type": dtype, "races": []}
    
    merged = {"season": season, "type": dtype, "races": []}
    race_map = {}
    
    offset = 0
    while offset < total:
        print(f"  page offset={offset}...")
        data = fetch_page(season, dtype, offset, limit=100)
        if data is None:
            break
        races = data["MRData"]["RaceTable"]["Races"]
        for race in races:
            rkey = (race["season"], race["round"])
            if rkey in race_map:
                idx = race_map[rkey]
                merged["races"][idx][inner_key].extend(race.get(inner_key, []))
            else:
                merged["races"].append(race)
                race_map[rkey] = len(merged["races"]) - 1
        offset += 100
        time.sleep(0.3)  # be polite
    
    print(f"  -> {len(merged['races'])} races merged")
    return merged

def fetch_schedule(season=2026):
    print(f"\nFetching {season} schedule...")
    url = f"{BASE_URL}/{season}.json"
    req = Request(url, headers={"User-Agent": "F1Predictor/1.0"})
    try:
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        races = data["MRData"]["RaceTable"]["Races"]
        print(f"  -> {len(races)} races")
        return {"races": races}
    except URLError as e:
        print(f"  ERROR: {e}")
        return {"races": []}

def main():
    seasons = [2023, 2024, 2025, 2026]
    types = ["results", "qualifying", "sprint"]
    
    for season in seasons:
        for dtype in types:
            merged = fetch_all(season, dtype)
            out_path = os.path.join(DATA_DIR, f"{season}_{dtype}.json")
            with open(out_path, "w") as f:
                json.dump(merged, f)
            print(f"  Saved {out_path}")
    
    schedule = fetch_schedule(2026)
    sched_path = os.path.join(DATA_DIR, "2026_schedule.json")
    with open(sched_path, "w") as f:
        json.dump(schedule, f)
    print(f"\nSaved {sched_path}")
    
    print("\n=== DONE ===")
    print(f"Files in {DATA_DIR}:")
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".json") and not fname.startswith("raw"):
            fpath = os.path.join(DATA_DIR, fname)
            try:
                with open(fpath) as f:
                    d = json.load(f)
                if "races" in d:
                    print(f"  {fname}: {len(d['races'])} races")
                else:
                    print(f"  {fname}: ok")
            except Exception as e:
                print(f"  {fname}: ERROR {e}")

if __name__ == "__main__":
    main()
