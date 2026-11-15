"""Boundary files (data/geo) and helpers. AI-assisted: written with Claude (Anthropic), reviewed by the team."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..i18n import tr


@dataclass
class Unit:
    id: str
    nome_pt: str
    nivel: str  # pais | provincia | departamento
    area_km2: float
    centroid: tuple[float, float]
    bbox: tuple[float, float, float, float]
    parent: str | None = None
    regiao: str | None = None
    feature: dict = field(repr=False, default_factory=dict)

    @property
    def nome(self) -> str:
        """Country names are translated; Argentine provinces and departments are proper names."""
        return tr(self.nome_pt) if self.nivel == "pais" else self.nome_pt


class Geo:
    def __init__(self, geo_dir: Path):
        self.paises = self._load(geo_dir / "paises.geojson")
        self.provincias = self._load(geo_dir / "provincias.geojson", parent_key="pais")
        self.departamentos = self._load(geo_dir / "departamentos.geojson", parent_key="provincia")
        self.fc = {
            "pais": {"type": "FeatureCollection", "features": [u.feature for u in self.paises.values()]},
            "prov": {"type": "FeatureCollection", "features": [u.feature for u in self.provincias.values()]},
            "dep": {"type": "FeatureCollection", "features": [u.feature for u in self.departamentos.values()]},
        }
        self.deps_of: dict[str, list[str]] = {}
        for d in self.departamentos.values():
            self.deps_of.setdefault(d.parent, []).append(d.id)

    @staticmethod
    def _load(path: Path, parent_key: str | None = None) -> dict[str, Unit]:
        fc = json.loads(path.read_text(encoding="utf-8"))
        out = {}
        for f in fc["features"]:
            p = f["properties"]
            out[f["id"]] = Unit(id=f["id"], nome_pt=p["nome"], nivel=p["nivel"], area_km2=p["area_km2"],
                                centroid=tuple(p["centroid"]), bbox=tuple(p["bbox"]),
                                parent=p.get(parent_key) if parent_key else None, regiao=p.get("regiao"), feature=f)
        return out

    def unit(self, kind: str, uid: str) -> Unit | None:
        return {"pais": self.paises, "prov": self.provincias, "dep": self.departamentos}.get(kind, {}).get(uid)

    def subset(self, kind: str, ids) -> dict:
        ids = set(ids)
        return {"type": "FeatureCollection", "features": [f for f in self.fc[kind]["features"] if f["id"] in ids]}

    def search_options(self) -> list[dict]:
        opts = [{"label": tr("{n} (país)", n=u.nome), "value": f"pais:{u.id}"} for u in self.paises.values()]
        opts += [{"label": tr("{n} (província, Argentina)", n=u.nome), "value": f"prov:{u.id}"} for u in self.provincias.values()]
        opts += [{"label": f"{u.nome} ({self.provincias[u.parent].nome})", "value": f"dep:{u.id}"}
                 for u in self.departamentos.values() if u.parent in self.provincias]
        return sorted(opts, key=lambda o: o["label"])
