"""Build the boundary files used by the app (data/geo/*.geojson).

AI-assisted: written with Claude (Anthropic) and reviewed by the team.

Sources (downloaded once into data/cache/):
- Countries: Natural Earth 1:50m via the `world-atlas` npm package (TopoJSON).
- Provinces/states (ADM1) and departments/municipalities (ADM2) of Argentina, Brazil and the Netherlands:
  geoBoundaries gbOpen. Every province carries its country (`pais`), every department its province.

Fixes applied:
- geoBoundaries ADM1 merges Entre Ríos into Buenos Aires; we split it along the Paraná.
- Natural Earth draws French Guiana as part of France; we cut it out as its own unit.

Run:  python scripts/build_geo.py
"""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "geo"

URLS = {
    "countries": "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json",
    "adm1": "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/ARG/ADM1/geoBoundaries-ARG-ADM1_simplified.geojson",
    "adm2": "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/ARG/ADM2/geoBoundaries-ARG-ADM2_simplified.geojson",
}
GB = "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/{iso}/{lvl}/geoBoundaries-{iso}-{lvl}_simplified.geojson"
# Other countries with the full drill-down: ISO3 -> (simplification of ADM1, of ADM2, in degrees)
EXTRA_ADM = {"BRA": (0.01, 0.005), "NLD": (0.002, 0.001)}
for _iso in EXTRA_ADM:
    URLS[f"{_iso}_adm1"] = GB.format(iso=_iso, lvl="ADM1")
    URLS[f"{_iso}_adm2"] = GB.format(iso=_iso, lvl="ADM2")

# Country names exactly as they appear in the data team's files -> (ISO3, Natural Earth name)
COUNTRIES = {
    "Argentina": ("ARG", "Argentina"),
    "Bolívia": ("BOL", "Bolivia"),
    "Brasil": ("BRA", "Brazil"),
    "Chile": ("CHL", "Chile"),
    "Colômbia": ("COL", "Colombia"),
    "Equador": ("ECU", "Ecuador"),
    "Guiana": ("GUY", "Guyana"),
    "Guiana Francesa": ("GUF", None),  # cut from France below
    "Paraguai": ("PRY", "Paraguay"),
    "Peru": ("PER", "Peru"),
    "Suriname": ("SUR", "Suriname"),
    "Uruguai": ("URY", "Uruguay"),
    "Venezuela": ("VEN", "Venezuela"),
    "Países Baixos": ("NLD", "Netherlands"),  # European part only (clipped below)
}
# geoBoundaries spells Brazilian states without accents (and two with typos): official names by ISO code
STATE_NAMES = {"BR-AC": "Acre", "BR-AL": "Alagoas", "BR-AP": "Amapá", "BR-AM": "Amazonas", "BR-BA": "Bahia", "BR-CE": "Ceará",
               "BR-DF": "Distrito Federal", "BR-ES": "Espírito Santo", "BR-GO": "Goiás", "BR-MA": "Maranhão", "BR-MT": "Mato Grosso",
               "BR-MS": "Mato Grosso do Sul", "BR-MG": "Minas Gerais", "BR-PA": "Pará", "BR-PB": "Paraíba", "BR-PR": "Paraná",
               "BR-PE": "Pernambuco", "BR-PI": "Piauí", "BR-RJ": "Rio de Janeiro", "BR-RN": "Rio Grande do Norte", "BR-RS": "Rio Grande do Sul",
               "BR-RO": "Rondônia", "BR-RR": "Roraima", "BR-SC": "Santa Catarina", "BR-SP": "São Paulo", "BR-SE": "Sergipe", "BR-TO": "Tocantins"}
CLIP = {"NLD": Polygon([(3, 50.5), (7.5, 50.5), (7.5, 54), (3, 54)])}

REGION = {  # Argentine statistical regions
    "Jujuy": "NOA", "Salta": "NOA", "Tucumán": "NOA", "Catamarca": "NOA", "Santiago del Estero": "NOA",
    "Formosa": "NEA", "Chaco": "NEA", "Misiones": "NEA", "Corrientes": "NEA",
    "La Rioja": "Cuyo", "San Juan": "Cuyo", "Mendoza": "Cuyo", "San Luis": "Cuyo",
    "Córdoba": "Centro", "Santa Fe": "Centro", "Entre Ríos": "Centro", "Buenos Aires": "Centro",
    "La Pampa": "Centro", "Ciudad Autónoma de Buenos Aires": "Centro",
    "Neuquén": "Patagonia", "Río Negro": "Patagonia", "Chubut": "Patagonia",
    "Santa Cruz": "Patagonia", "Tierra del Fuego": "Patagonia",
}
NAME_FIX = {"La Roja": "La Rioja"}

# Cut line along the Paraná river separating Entre Ríos (north/east) from Buenos Aires.
ENTRE_RIOS_CUT = Polygon([(-61, -29.5), (-55, -29.5), (-55, -33.95), (-58.4, -34.05), (-58.9, -34.12),
                          (-59.3, -33.92), (-59.7, -33.67), (-60.1, -33.45), (-60.5, -33.15), (-61, -32.9)])


def fetch(key: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / Path(URLS[key]).name
    if not path.exists():
        print(f"download {URLS[key]}")
        urllib.request.urlretrieve(URLS[key], path)
    return path


def topo_countries(path: Path) -> dict[str, MultiPolygon]:
    topo = json.loads(path.read_text())
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts

    out = {}
    for g in topo["objects"]["countries"]["geometries"]:
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        mp = MultiPolygon([Polygon(ring(p[0]), [ring(h) for h in p[1:]]) for p in polys]).buffer(0)
        out[g["properties"]["name"]] = mp
    return out


def area_km2(geom) -> float:
    """Equal-area (sinusoidal) approximation, good enough for densities."""
    from shapely.ops import transform

    def fwd(x, y, z=None):
        import numpy as np
        x = np.asarray(x)
        y = np.asarray(y)
        return x * 111.32 * np.cos(np.radians(y)), y * 110.57

    return transform(fwd, geom).area


def to_feature(geom, props: dict, tol: float) -> dict:
    g = geom.simplify(tol, preserve_topology=True)
    parts = list(g.geoms) if hasattr(g, "geoms") else [g]
    parts = [orient(p, sign=1.0) for p in parts if p.area > tol * tol]  # RFC 7946: CCW exterior
    if not parts:
        parts = [orient(geom.buffer(0), sign=1.0)] if geom.geom_type == "Polygon" else [orient(max(geom.geoms, key=lambda p: p.area), 1.0)]
    mp = MultiPolygon(parts)
    rounded = json.loads(json.dumps(mapping(mp)), parse_float=lambda s: round(float(s), 4))
    c = geom.representative_point()
    minx, miny, maxx, maxy = geom.bounds
    props = {**props, "area_km2": round(area_km2(geom), 1), "centroid": [round(c.x, 4), round(c.y, 4)],
             "bbox": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)]}
    return {"type": "Feature", "id": props["id"], "properties": props, "geometry": rounded}


def write(name: str, features: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")))
    print(f"{path.relative_to(ROOT)}: {len(features)} features, {path.stat().st_size/1024:.0f} KB")


def main() -> None:
    world = topo_countries(fetch("countries"))
    feats = []
    for nome, (iso, ne) in COUNTRIES.items():
        if ne:
            geom = world[ne].intersection(CLIP[iso]) if iso in CLIP else world[ne]
        else:  # French Guiana: the part of France inside South America
            box = Polygon([(-55, 1.5), (-51, 1.5), (-51, 6.5), (-55, 6.5)])
            geom = world["France"].intersection(box)
        feats.append(to_feature(geom, {"id": iso, "nome": nome, "nivel": "pais"}, 0.02))
    write("paises.geojson", feats)

    adm1 = json.loads(fetch("adm1").read_text())
    provs: dict[str, tuple[str, object]] = {}
    for f in adm1["features"]:
        nome = NAME_FIX.get(f["properties"]["shapeName"], f["properties"]["shapeName"])
        provs[nome] = (f["properties"]["shapeISO"], shape(f["geometry"]).buffer(0))
    ba_iso, ba = provs["Buenos Aires"]
    provs["Entre Ríos"] = ("AR-E", ba.intersection(ENTRE_RIOS_CUT))
    provs["Buenos Aires"] = (ba_iso, ba.difference(ENTRE_RIOS_CUT))
    pfeats = [to_feature(g, {"id": iso, "nome": n, "regiao": REGION[n], "pais": "ARG", "nivel": "provincia"}, 0.01)
              for n, (iso, g) in sorted(provs.items())]
    pgeoms = {iso: g for _, (iso, g) in provs.items()}
    adm2 = json.loads(fetch("adm2").read_text())
    dfeats = []
    for f in adm2["features"]:
        g = shape(f["geometry"]).buffer(0)
        if g.is_empty:
            continue
        pt = g.representative_point()
        parent = next((iso for iso, pg in pgeoms.items() if pg.contains(pt)), None)
        if parent is None:
            parent = min(pgeoms, key=lambda iso: pgeoms[iso].distance(pt))
        dfeats.append(to_feature(g, {"id": f["properties"]["shapeID"], "nome": f["properties"]["shapeName"],
                                     "provincia": parent, "nivel": "departamento"}, 0.005))
    for iso, (tol1, tol2) in EXTRA_ADM.items():
        p2, d2 = extra_country(iso, tol1, tol2)
        pfeats += p2
        dfeats += d2
    write("provincias.geojson", pfeats)
    write("departamentos.geojson", dfeats)


def extra_country(iso: str, tol1: float, tol2: float) -> tuple[list[dict], list[dict]]:
    """ADM1 + ADM2 of another country; departments get the province that contains them."""
    pgeoms, pfeats = {}, []
    for f in json.loads(fetch(f"{iso}_adm1").read_text())["features"]:
        pr = f["properties"]
        pid = pr.get("shapeISO") or pr["shapeID"]
        g = shape(f["geometry"]).buffer(0)
        pgeoms[pid] = g
        pfeats.append(to_feature(g, {"id": pid, "nome": STATE_NAMES.get(pid, pr["shapeName"]), "pais": iso, "nivel": "provincia"}, tol1))
    tree_ids = list(pgeoms)
    tree = shapely.STRtree([pgeoms[k] for k in tree_ids])
    dfeats = []
    for f in json.loads(fetch(f"{iso}_adm2").read_text())["features"]:
        g = shape(f["geometry"]).buffer(0)
        if g.is_empty:
            continue
        pt = g.representative_point()
        hit = tree.query(pt, predicate="within")
        parent = tree_ids[hit[0]] if len(hit) else tree_ids[tree.query_nearest(pt)[0]]
        dfeats.append(to_feature(g, {"id": f["properties"]["shapeID"], "nome": f["properties"]["shapeName"],
                                     "provincia": parent, "nivel": "departamento"}, tol2))
    print(f"{iso}: {len(pfeats)} provinces/states, {len(dfeats)} departments/municipalities")
    return pfeats, dfeats


if __name__ == "__main__":
    main()
