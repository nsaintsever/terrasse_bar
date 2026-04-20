"""Script à lancer UNE FOIS pour précharger les données des villes."""
from shadow_engine import CITIES, fetch_bars, fetch_buildings, _bars_path, _buildings_path
import time

def preload():
    for name, info in CITIES.items():
        lat, lon = info["center"]
        radius = info["radius"]
        slug = info["slug"]

        print(f"\n=== {name} (rayon {radius}m) ===")

        bars_p = _bars_path(slug)
        if bars_p.exists():
            print(f"  ✓ bars déjà présents ({bars_p})")
        else:
            t0 = time.time()
            print(f"  → fetch bars...")
            bars = fetch_bars(lat, lon, radius)
            bars.to_parquet(bars_p)
            print(f"  ✓ {len(bars)} bars sauvegardés en {time.time()-t0:.1f}s")

        bld_p = _buildings_path(slug)
        if bld_p.exists():
            print(f"  ✓ bâtiments déjà présents ({bld_p})")
        else:
            t0 = time.time()
            print(f"  → fetch bâtiments (peut prendre 30s+)...")
            bld = fetch_buildings(lat, lon, radius)
            bld.to_parquet(bld_p)
            print(f"  ✓ {len(bld)} bâtiments sauvegardés en {time.time()-t0:.1f}s")

    print("\n✅ Préchargement terminé !")

if __name__ == "__main__":
    preload()
