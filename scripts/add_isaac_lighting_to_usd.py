#!/usr/bin/env python3
"""Add Isaac-friendly lighting to an exported USD stage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


USD_SUFFIXES = {".usd", ".usdc", ".usda"}
DOME_LIGHT_PATH = "/World/IsaacDefaultDomeLight"
FILL_LIGHT_PATH = "/World/IsaacDefaultFillLight"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usd-dir", type=Path, required=True)
    parser.add_argument("--add-dome-light", action="store_true")
    parser.add_argument("--dome-intensity", type=float, default=30000.0)
    parser.add_argument("--dome-color", default="1,1,1")
    parser.add_argument("--dome-exposure", type=float)
    parser.add_argument("--add-fill-light", action="store_true")
    parser.add_argument("--fill-intensity", type=float, default=1000.0)
    parser.add_argument("--fill-color", default="1,1,1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-lights", action="store_true")
    return parser.parse_args()


def parse_color(value: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Expected R,G,B color, got {value!r}")
    return tuple(float(part) for part in parts)  # type: ignore[return-value]


def usd_candidates(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in USD_SUFFIXES else []
    if not path.exists():
        return []
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in USD_SUFFIXES
    )


def choose_main_usd(path: Path) -> Path:
    candidates = usd_candidates(path)
    if not candidates:
        raise FileNotFoundError(f"No USD/USDc/USDa files found under {path}")
    if len(candidates) == 1:
        return candidates[0]

    priority_names = (
        "export_scene.usdc",
        "export_scene.usd",
        "export_scene.usda",
        "scene.usdc",
        "scene.usd",
        "scene.usda",
    )
    for name in priority_names:
        matches = [candidate for candidate in candidates if candidate.name == name]
        if len(matches) == 1:
            return matches[0]

    export_scene_matches = [
        candidate
        for candidate in candidates
        if candidate.parent.name == "export_scene.blend"
        and candidate.stem == "export_scene"
    ]
    if len(export_scene_matches) == 1:
        return export_scene_matches[0]

    candidate_text = "\n".join(f"  - {candidate}" for candidate in candidates)
    raise RuntimeError(
        "Multiple USD candidates found and no unique scene entry could be chosen:\n"
        f"{candidate_text}"
    )


def load_pxr():
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux
    except ImportError as exc:
        raise RuntimeError(
            "Could not import pxr. Activate an environment with USD Python bindings "
            "before running add_isaac_lighting_to_usd.py."
        ) from exc
    return Gf, Sdf, Usd, UsdGeom, UsdLux


def list_lights(stage) -> list[str]:
    rows = []
    for prim in stage.Traverse():
        type_name = str(prim.GetTypeName())
        if type_name.endswith("Light") or type_name in {"DomeLight", "SphereLight"}:
            intensity = prim.GetAttribute("intensity").Get()
            color = prim.GetAttribute("color").Get()
            rows.append(
                f"{prim.GetPath()} type={type_name} intensity={intensity} color={color}"
            )
    return rows


def ensure_world(stage, UsdGeom) -> None:
    if not stage.GetPrimAtPath("/World"):
        UsdGeom.Xform.Define(stage, "/World")


def add_or_update_dome(stage, Gf, Sdf, UsdLux, intensity, color, exposure) -> None:
    path = Sdf.Path(DOME_LIGHT_PATH)
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid() and prim.GetTypeName() not in {"", "DomeLight"}:
        raise RuntimeError(f"{DOME_LIGHT_PATH} exists and is not a DomeLight")
    light = UsdLux.DomeLight.Define(stage, path)
    light.CreateIntensityAttr().Set(float(intensity))
    light.CreateColorAttr().Set(Gf.Vec3f(*color))
    if exposure is not None:
        light.CreateExposureAttr().Set(float(exposure))


def add_or_update_fill(stage, Gf, Sdf, UsdGeom, UsdLux, intensity, color) -> None:
    path = Sdf.Path(FILL_LIGHT_PATH)
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid() and prim.GetTypeName() not in {"", "SphereLight"}:
        raise RuntimeError(f"{FILL_LIGHT_PATH} exists and is not a SphereLight")
    light = UsdLux.SphereLight.Define(stage, path)
    light.CreateIntensityAttr().Set(float(intensity))
    light.CreateColorAttr().Set(Gf.Vec3f(*color))
    light.CreateRadiusAttr().Set(5.0)
    xformable = UsdGeom.Xformable(light.GetPrim())
    if not xformable.GetOrderedXformOps():
        xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 4.0))


def main() -> int:
    args = parse_args()
    if not (args.add_dome_light or args.add_fill_light or args.list_lights):
        print(
            "Nothing to do. Use --add-dome-light, --add-fill-light, or --list-lights.",
            file=sys.stderr,
        )
        return 2

    try:
        dome_color = parse_color(args.dome_color)
        fill_color = parse_color(args.fill_color)
        usd_path = choose_main_usd(args.usd_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"usd_file={usd_path}", flush=True)
    if args.dry_run and not args.list_lights:
        if args.add_dome_light:
            print(
                f"dry_run: would add/update {DOME_LIGHT_PATH} "
                f"intensity={args.dome_intensity}"
            )
        if args.add_fill_light:
            print(
                f"dry_run: would add/update {FILL_LIGHT_PATH} "
                f"intensity={args.fill_intensity}"
            )
        return 0

    try:
        Gf, Sdf, Usd, UsdGeom, UsdLux = load_pxr()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        print(f"ERROR: could not open USD stage: {usd_path}", file=sys.stderr)
        return 2

    if args.list_lights:
        lights = list_lights(stage)
        if lights:
            print("lights:")
            for row in lights:
                print(f"  {row}")
        else:
            print("lights: none")

    if args.dry_run:
        if args.add_dome_light:
            print(
                f"dry_run: would add/update {DOME_LIGHT_PATH} "
                f"intensity={args.dome_intensity}"
            )
        if args.add_fill_light:
            print(
                f"dry_run: would add/update {FILL_LIGHT_PATH} "
                f"intensity={args.fill_intensity}"
            )
        return 0

    ensure_world(stage, UsdGeom)
    if args.add_dome_light:
        add_or_update_dome(
            stage,
            Gf,
            Sdf,
            UsdLux,
            args.dome_intensity,
            dome_color,
            args.dome_exposure,
        )
        print(
            f"dome_light_added=yes path={DOME_LIGHT_PATH} "
            f"intensity={args.dome_intensity}"
        )
    if args.add_fill_light:
        add_or_update_fill(
            stage, Gf, Sdf, UsdGeom, UsdLux, args.fill_intensity, fill_color
        )
        print(
            f"fill_light_added=yes path={FILL_LIGHT_PATH} "
            f"intensity={args.fill_intensity}"
        )

    stage.GetRootLayer().Save()
    print("status=complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
