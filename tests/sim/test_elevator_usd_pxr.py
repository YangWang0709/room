"""Optional schema-level tests, run when the OpenUSD Python bindings exist."""

import pytest

pytest.importorskip("pxr", reason="OpenUSD pxr bindings are not installed")

from pxr import Usd, UsdGeom, UsdPhysics, UsdUtils

from infinigen.core.sim.elevator_manifest import ElevatorManifest
from infinigen.core.sim.elevator_usd import (
    author_elevator_usd,
    build_usd_plan,
    write_wrapper_usda,
)
from test_elevator_manifest import manifest_payload


def test_authored_wrapper_has_only_linear_prismatic_drives_and_is_compliant(tmp_path):
    building_path = tmp_path / "building.usdc"
    building = Usd.Stage.CreateNew(str(building_path))
    world = UsdGeom.Xform.Define(building, "/World")
    building.SetDefaultPrim(world.GetPrim())
    UsdGeom.Cube.Define(building, "/World/StaticBuilding")
    building.GetRootLayer().Save()

    plan = build_usd_plan(ElevatorManifest.from_dict(manifest_payload()))
    elevator_path = tmp_path / "elevator_articulation.usda"
    wrapper_path = tmp_path / "scene_with_elevators.usda"
    author_elevator_usd(plan, elevator_path)
    write_wrapper_usda(
        building_path,
        elevator_path,
        wrapper_path,
        meters_per_unit=plan.meters_per_unit,
        up_axis=plan.up_axis,
    )

    stage = Usd.Stage.Open(str(wrapper_path))
    assert stage is not None
    assert stage.GetDefaultPrim().GetPath().pathString == "/World"
    joints = [prim for prim in stage.Traverse() if prim.IsA(UsdPhysics.PrismaticJoint)]
    assert len(joints) == plan.dof_count
    for prim in joints:
        linear_drive = UsdPhysics.DriveAPI.Get(prim, "linear")
        assert linear_drive.GetStiffnessAttr().HasAuthoredValueOpinion()
        assert linear_drive.GetTargetPositionAttr().HasAuthoredValueOpinion()
        assert not prim.GetAttribute("drive:angular:physics:stiffness").IsValid()

    articulation_roots = [
        prim for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.ArticulationRootAPI)
    ]
    assert len(articulation_roots) == len(plan.elevators)

    checker = UsdUtils.ComplianceChecker(arkit=False, skipARKitRootLayerCheck=True)
    checker.CheckCompliance(str(wrapper_path))
    assert checker.GetErrors() == []
    assert checker.GetFailedChecks() == []
