# Copyright (C) 2026, Princeton University.
# This source code is licensed under the BSD 3-Clause license found in the
# LICENSE file in the root directory of this source tree.

"""Pure-Python elevator specification, controller, and animation planning.

This module deliberately has no Blender or NumPy dependency.  The geometry
builder consumes the immutable snapshots produced here, while unit tests can
exercise motion, door linkage, and interlocks in a regular Python process.

Coordinate convention
---------------------
``stop_z`` is the local Z coordinate of the finished car floor at a served
landing.  X runs left/right across the center-opening doors and negative Y is
the front/landing side of the elevator.
"""

from __future__ import annotations

import colorsys
import math
import random
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, TypeAlias

LevelId: TypeAlias = int | str
_EPS = 1e-9


class ElevatorConfigurationError(ValueError):
    """Raised when an elevator cannot be built from the requested dimensions."""


class ElevatorInterlockError(RuntimeError):
    """Raised when a command would violate a motion or landing-door interlock."""


class ElevatorPhase(str, Enum):
    """Controller phases shared by static metadata and Blender animation."""

    IDLE_CLOSED = "idle_closed"
    MOVING = "moving"
    LEVELING = "leveling"
    OPENING = "opening"
    OPEN_DWELL = "open_dwell"
    CLOSING = "closing"
    FAULT = "fault"


class ElevatorBuildMode(str, Enum):
    """Whether the Blender builder creates one pose or a keyframed sequence."""

    STATIC = "static"
    ANIMATED = "animated"


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ElevatorConfigurationError(f"{name} must be finite and > 0, got {value}")


@dataclass(frozen=True)
class ElevatorSpec:
    """Geometry and stop configuration for one center-opening elevator.

    Stops may be non-uniformly spaced and level identifiers may be integers or
    strings.  Their order is bottom-to-top and remains stable in all exported
    metadata and Blender hierarchy names.
    """

    stop_z: tuple[float, ...]
    served_levels: tuple[LevelId, ...] = ()

    shaft_width: float = 2.2
    shaft_depth: float = 2.1
    shaft_wall_thickness: float = 0.12
    pit_depth: float = 0.25
    overhead: float = 0.35

    car_width: float = 1.7
    car_depth: float = 1.55
    car_height: float = 2.35
    car_panel_thickness: float = 0.07
    running_clearance: float = 0.08

    door_width: float = 1.05
    door_height: float = 2.1
    door_thickness: float = 0.045
    landing_frame_width: float = 0.10
    landing_frame_depth: float = 0.10

    def __post_init__(self) -> None:
        stops = tuple(float(z) for z in self.stop_z)
        object.__setattr__(self, "stop_z", stops)
        if not stops:
            raise ElevatorConfigurationError("at least one stop_z is required")
        if not all(math.isfinite(z) for z in stops):
            raise ElevatorConfigurationError(
                f"all stop_z values must be finite: {stops}"
            )
        if any(b <= a for a, b in zip(stops, stops[1:])):
            raise ElevatorConfigurationError(
                f"stop_z must be strictly increasing from bottom to top: {stops}"
            )

        if self.served_levels:
            levels = tuple(self.served_levels)
        else:
            levels = tuple(range(len(stops)))
        object.__setattr__(self, "served_levels", levels)
        if len(levels) != len(stops):
            raise ElevatorConfigurationError(
                "served_levels and stop_z must have the same length, got "
                f"{len(levels)} and {len(stops)}"
            )
        if any(
            isinstance(level, bool) or not isinstance(level, (int, str))
            for level in levels
        ):
            raise ElevatorConfigurationError(
                f"level identifiers must be int or str (but not bool): {levels}"
            )
        if len(set(levels)) != len(levels):
            raise ElevatorConfigurationError(f"served_levels must be unique: {levels}")

        dimension_names = (
            "shaft_width",
            "shaft_depth",
            "shaft_wall_thickness",
            "pit_depth",
            "overhead",
            "car_width",
            "car_depth",
            "car_height",
            "car_panel_thickness",
            "running_clearance",
            "door_width",
            "door_height",
            "door_thickness",
            "landing_frame_width",
            "landing_frame_depth",
        )
        for name in dimension_names:
            _positive(name, float(getattr(self, name)))

        if self.car_width + 2 * self.running_clearance >= self.shaft_width:
            raise ElevatorConfigurationError(
                "car_width plus running clearance must fit strictly inside shaft_width"
            )
        if self.car_depth + 2 * self.running_clearance >= self.shaft_depth:
            raise ElevatorConfigurationError(
                "car_depth plus running clearance must fit strictly inside shaft_depth"
            )
        if self.door_width + 2 * self.landing_frame_width >= min(
            self.car_width, self.shaft_width
        ):
            raise ElevatorConfigurationError(
                "door_width plus both landing frame sides must fit the car and shaft"
            )
        if self.door_height + self.car_panel_thickness >= self.car_height:
            raise ElevatorConfigurationError(
                "door_height plus panel thickness must be lower than car_height"
            )
        minimum_spacing = max(
            self.car_height + self.running_clearance,
            self.door_height + 2 * self.landing_frame_width,
        )
        if any((b - a) <= minimum_spacing for a, b in zip(stops, stops[1:])):
            raise ElevatorConfigurationError(
                "adjacent stops are too close for the configured car/landing geometry; "
                f"required > {minimum_spacing:.3f}, got {stops}"
            )

    @classmethod
    def evenly_spaced(
        cls,
        n_stops: int,
        floor_height: float = 3.0,
        base_z: float = 0.0,
        served_levels: Iterable[LevelId] | None = None,
        **kwargs,
    ) -> "ElevatorSpec":
        if isinstance(n_stops, bool) or not isinstance(n_stops, int) or n_stops < 1:
            raise ElevatorConfigurationError(
                f"n_stops must be a positive integer, got {n_stops!r}"
            )
        _positive("floor_height", floor_height)
        levels = () if served_levels is None else tuple(served_levels)
        return cls(
            stop_z=tuple(base_z + i * floor_height for i in range(n_stops)),
            served_levels=levels,
            **kwargs,
        )

    @property
    def n_stops(self) -> int:
        return len(self.stop_z)

    @property
    def shaft_bottom_z(self) -> float:
        return self.stop_z[0] - self.pit_depth

    @property
    def shaft_top_z(self) -> float:
        return self.stop_z[-1] + self.car_height + self.overhead

    @property
    def shaft_height(self) -> float:
        return self.shaft_top_z - self.shaft_bottom_z

    def level_index(self, level: LevelId) -> int:
        if isinstance(level, bool) or not isinstance(level, (int, str)):
            raise KeyError(f"invalid level identifier {level!r}")
        try:
            return self.served_levels.index(level)
        except ValueError as exc:
            raise KeyError(
                f"level {level!r} is not served; choices are {self.served_levels}"
            ) from exc

    def z_for_level(self, level: LevelId) -> float:
        return self.stop_z[self.level_index(level)]


@dataclass(frozen=True)
class ElevatorTiming:
    """Deterministic timing used by the controller and animation sampler."""

    travel_speed: float = 1.0
    travel_acceleration: float = 1.0
    leveling_time: float = 0.25
    door_open_time: float = 0.8
    door_dwell_time: float = 1.5
    door_close_time: float = 0.8

    def __post_init__(self) -> None:
        _positive("travel_speed", self.travel_speed)
        _positive("travel_acceleration", self.travel_acceleration)
        _positive("door_open_time", self.door_open_time)
        _positive("door_close_time", self.door_close_time)
        for name in ("leveling_time", "door_dwell_time"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ElevatorConfigurationError(
                    f"{name} must be finite and >= 0, got {value}"
                )


@dataclass(frozen=True)
class ElevatorVisualVariant:
    """Small deterministic visual choices which do not alter clearances."""

    accent_rgb: tuple[float, float, float]
    landing_station_sides: tuple[int, ...]
    seed: int


def sample_visual_variant(spec: ElevatorSpec, seed: int) -> ElevatorVisualVariant:
    """Return repeatable visual choices for a given seed and stop layout."""

    rng = random.Random(int(seed))
    hue = rng.random()
    saturation = 0.35 + 0.25 * rng.random()
    value = 0.55 + 0.25 * rng.random()
    rgb = tuple(float(c) for c in colorsys.hsv_to_rgb(hue, saturation, value))
    sides = tuple(-1 if rng.random() < 0.5 else 1 for _ in spec.stop_z)
    return ElevatorVisualVariant(rgb, sides, int(seed))


@dataclass(frozen=True)
class ElevatorSnapshot:
    """Immutable controller output suitable for tests or Blender keyframes."""

    time_s: float
    phase: ElevatorPhase
    car_z: float
    velocity: float
    current_level: LevelId | None
    target_level: LevelId | None
    car_door_fraction: float
    landing_door_fractions: tuple[tuple[LevelId, float], ...]
    pending_levels: tuple[LevelId, ...]
    fault_reason: str | None = None

    def landing_door_fraction(self, level: LevelId) -> float:
        for landing, fraction in self.landing_door_fractions:
            if landing == level and type(landing) is type(level):
                return fraction
        raise KeyError(level)


class ElevatorController:
    """A deterministic single-car controller with linked landing-door interlocks."""

    def __init__(
        self,
        spec: ElevatorSpec,
        initial_level: LevelId | None = None,
        timing: ElevatorTiming | None = None,
        seed: int = 0,
    ) -> None:
        self.spec = spec
        self.timing = timing or ElevatorTiming()
        self.seed = int(seed)
        if initial_level is None:
            initial_level = spec.served_levels[0]
        initial_index = spec.level_index(initial_level)

        self.phase = ElevatorPhase.IDLE_CLOSED
        self.time_s = 0.0
        self.car_z = spec.stop_z[initial_index]
        self.velocity = 0.0
        self._current_index: int | None = initial_index
        self._target_index: int | None = None
        self._door_fraction = 0.0
        self._landing_door_fractions = [0.0] * spec.n_stops
        self._pending: deque[int] = deque()
        self._phase_remaining = 0.0
        self._motion_profile: dict[str, float] | None = None
        self._fault_reason: str | None = None
        self.assert_invariants()

    @property
    def current_level(self) -> LevelId | None:
        if self._current_index is None:
            return None
        return self.spec.served_levels[self._current_index]

    @property
    def target_level(self) -> LevelId | None:
        if self._target_index is None:
            return None
        return self.spec.served_levels[self._target_index]

    @property
    def doors_closed(self) -> bool:
        return self._door_fraction <= _EPS and all(
            fraction <= _EPS for fraction in self._landing_door_fractions
        )

    @property
    def is_idle(self) -> bool:
        return (
            self.phase == ElevatorPhase.IDLE_CLOSED
            and not self._pending
            and self._target_index is None
            and self.doors_closed
        )

    def request(self, level: LevelId) -> bool:
        """Queue a served level, returning False when it was already pending."""

        if self.phase == ElevatorPhase.FAULT:
            raise ElevatorInterlockError("cannot accept requests while faulted")
        index = self.spec.level_index(level)

        if self.phase == ElevatorPhase.OPEN_DWELL and index == self._current_index:
            self._phase_remaining = self.timing.door_dwell_time
            return False
        if index == self._target_index or index in self._pending:
            return False
        if index == self._current_index and self.phase in {
            ElevatorPhase.OPENING,
            ElevatorPhase.CLOSING,
        }:
            return False
        self._pending.append(index)
        return True

    def move_to_floor(self, level: LevelId) -> bool:
        """Queue a floor using the generated-scene controller API."""

        return self.request(level)

    def set_current_floor(self, level: LevelId) -> None:
        """Reset an idle controller to a measured landing safely."""

        if self.phase in {ElevatorPhase.MOVING, ElevatorPhase.LEVELING}:
            raise ElevatorInterlockError("cannot reset the current floor during motion")
        if not self.doors_closed:
            raise ElevatorInterlockError("current-floor reset requires closed doors")
        index = self.spec.level_index(level)
        self._pending.clear()
        self._current_index = index
        self._target_index = None
        self.car_z = self.spec.stop_z[index]
        self.velocity = 0.0
        self._motion_profile = None
        self.phase = ElevatorPhase.IDLE_CLOSED
        self.assert_invariants()

    def set_car_door_open_fraction(self, value: float) -> None:
        """Set linked car/current-landing door fractions for preview/control."""

        self._set_door_fraction(value)
        self.assert_invariants()

    def set_landing_door_open_fraction(self, level: LevelId, value: float) -> None:
        """Set a landing fraction while enforcing car/landing interlocks."""

        index = self.spec.level_index(level)
        value = float(value)
        if value > _EPS and index != self._current_index:
            raise ElevatorInterlockError(
                "only the landing aligned with the car may be opened"
            )
        self._set_door_fraction(value)
        self.assert_invariants()

    def open_doors(self) -> None:
        """Open at the aligned landing, rejecting any unsafe request."""

        if self.phase == ElevatorPhase.FAULT:
            raise ElevatorInterlockError("cannot open doors while faulted")
        if self.phase in {ElevatorPhase.MOVING, ElevatorPhase.LEVELING}:
            raise ElevatorInterlockError(
                "cannot open doors while the car is moving/leveling"
            )
        if self._current_index is None:
            raise ElevatorInterlockError("cannot open doors while car is not aligned")
        if self.phase == ElevatorPhase.OPEN_DWELL:
            self._phase_remaining = self.timing.door_dwell_time
            return
        if self.phase == ElevatorPhase.CLOSING:
            self.phase = ElevatorPhase.OPENING
            return
        if self.phase == ElevatorPhase.IDLE_CLOSED:
            self.phase = ElevatorPhase.OPENING

    def close_doors(self) -> None:
        if self.phase == ElevatorPhase.FAULT:
            raise ElevatorInterlockError("cannot close doors while faulted")
        if self.phase in {ElevatorPhase.OPENING, ElevatorPhase.OPEN_DWELL}:
            self.phase = ElevatorPhase.CLOSING
            self._phase_remaining = 0.0

    def trigger_fault(self, reason: str) -> None:
        self.velocity = 0.0
        self._fault_reason = str(reason)
        self.phase = ElevatorPhase.FAULT

    def reset_fault(self) -> None:
        if self.phase != ElevatorPhase.FAULT:
            return
        if not self.doors_closed or self._current_index is None:
            raise ElevatorInterlockError(
                "fault reset requires closed doors and an aligned landing"
            )
        self._fault_reason = None
        self.phase = ElevatorPhase.IDLE_CLOSED

    def snapshot(self) -> ElevatorSnapshot:
        return ElevatorSnapshot(
            time_s=self.time_s,
            phase=self.phase,
            car_z=self.car_z,
            velocity=self.velocity,
            current_level=self.current_level,
            target_level=self.target_level,
            car_door_fraction=self._door_fraction,
            landing_door_fractions=tuple(
                zip(self.spec.served_levels, self._landing_door_fractions)
            ),
            pending_levels=tuple(
                self.spec.served_levels[index] for index in self._pending
            ),
            fault_reason=self._fault_reason,
        )

    def assert_invariants(self) -> None:
        if not (-_EPS <= self._door_fraction <= 1 + _EPS):
            raise ElevatorInterlockError(
                f"invalid car door fraction {self._door_fraction}"
            )
        if any(
            not (-_EPS <= fraction <= 1 + _EPS)
            for fraction in self._landing_door_fractions
        ):
            raise ElevatorInterlockError(
                f"invalid landing door fractions {self._landing_door_fractions}"
            )
        open_landings = [
            i
            for i, fraction in enumerate(self._landing_door_fractions)
            if fraction > _EPS
        ]
        if self._door_fraction > _EPS:
            if self._current_index is None:
                raise ElevatorInterlockError("car doors open while not aligned")
            if open_landings != [self._current_index]:
                raise ElevatorInterlockError(
                    "car and landing doors are not linked at exactly one landing"
                )
            if not math.isclose(
                self._landing_door_fractions[self._current_index],
                self._door_fraction,
                abs_tol=1e-8,
            ):
                raise ElevatorInterlockError("car/landing door fractions differ")
        elif open_landings:
            raise ElevatorInterlockError(
                "a landing door is open while car doors are closed"
            )

        if self.phase in {ElevatorPhase.MOVING, ElevatorPhase.LEVELING}:
            if not self.doors_closed:
                raise ElevatorInterlockError("motion phase entered with doors open")
        if self._current_index is not None and not math.isclose(
            self.car_z, self.spec.stop_z[self._current_index], abs_tol=1e-7
        ):
            raise ElevatorInterlockError(
                "aligned landing index does not match the car Z coordinate"
            )
        if (
            self.phase
            in {
                ElevatorPhase.OPENING,
                ElevatorPhase.OPEN_DWELL,
                ElevatorPhase.CLOSING,
            }
            and self._current_index is None
        ):
            raise ElevatorInterlockError("door phase requires an aligned landing")

    def _set_door_fraction(self, fraction: float) -> None:
        fraction = min(1.0, max(0.0, float(fraction)))
        if fraction > _EPS:
            if self._current_index is None:
                raise ElevatorInterlockError("cannot open doors between landings")
            if self.phase in {ElevatorPhase.MOVING, ElevatorPhase.LEVELING}:
                raise ElevatorInterlockError("cannot open doors during motion")
        self._door_fraction = fraction
        self._landing_door_fractions[:] = [0.0] * self.spec.n_stops
        if fraction > _EPS and self._current_index is not None:
            self._landing_door_fractions[self._current_index] = fraction

    def _begin_next_request(self) -> None:
        if not self._pending:
            return
        index = self._pending.popleft()
        self._target_index = index
        if index == self._current_index:
            self.phase = ElevatorPhase.OPENING
            return
        if not self.doors_closed:
            raise ElevatorInterlockError(
                "cannot begin travel until all doors are closed"
            )
        self._motion_profile = self._build_motion_profile(
            self.car_z, self.spec.stop_z[index]
        )
        self._current_index = None
        self.phase = ElevatorPhase.MOVING

    def _build_motion_profile(
        self, start_z: float, target_z: float
    ) -> dict[str, float]:
        distance = abs(target_z - start_z)
        acceleration = self.timing.travel_acceleration
        max_speed = self.timing.travel_speed
        accel_time_at_max = max_speed / acceleration
        accel_distance_at_max = 0.5 * acceleration * accel_time_at_max**2
        if 2 * accel_distance_at_max >= distance:
            accel_time = math.sqrt(distance / acceleration)
            peak_speed = acceleration * accel_time
            cruise_time = 0.0
        else:
            accel_time = accel_time_at_max
            peak_speed = max_speed
            cruise_time = (distance - 2 * accel_distance_at_max) / max_speed
        accel_distance = 0.5 * acceleration * accel_time**2
        cruise_distance = peak_speed * cruise_time
        return {
            "start_z": start_z,
            "target_z": target_z,
            "direction": 1.0 if target_z > start_z else -1.0,
            "acceleration": acceleration,
            "accel_time": accel_time,
            "cruise_time": cruise_time,
            "peak_speed": peak_speed,
            "accel_distance": accel_distance,
            "cruise_distance": cruise_distance,
            "total_time": 2 * accel_time + cruise_time,
            "elapsed": 0.0,
        }

    def _sample_motion_profile(self) -> None:
        if self._motion_profile is None:
            raise ElevatorInterlockError("moving without an acceleration profile")
        profile = self._motion_profile
        elapsed = profile["elapsed"]
        accel_time = profile["accel_time"]
        cruise_time = profile["cruise_time"]
        acceleration = profile["acceleration"]
        peak_speed = profile["peak_speed"]
        if elapsed <= accel_time:
            distance = 0.5 * acceleration * elapsed**2
            speed = acceleration * elapsed
        elif elapsed <= accel_time + cruise_time:
            cruise_elapsed = elapsed - accel_time
            distance = profile["accel_distance"] + peak_speed * cruise_elapsed
            speed = peak_speed
        else:
            decel_elapsed = elapsed - accel_time - cruise_time
            distance = (
                profile["accel_distance"]
                + profile["cruise_distance"]
                + peak_speed * decel_elapsed
                - 0.5 * acceleration * decel_elapsed**2
            )
            speed = max(0.0, peak_speed - acceleration * decel_elapsed)
        self.car_z = profile["start_z"] + profile["direction"] * distance
        self.velocity = profile["direction"] * speed

    def step(self, dt: float) -> ElevatorSnapshot:
        """Advance the controller by ``dt`` seconds and return its new snapshot."""

        if not math.isfinite(dt) or dt < 0:
            raise ValueError(f"dt must be finite and >= 0, got {dt}")
        remaining = float(dt)
        if remaining <= _EPS:
            return self.snapshot()
        if self.phase == ElevatorPhase.FAULT:
            self.time_s += remaining
            return self.snapshot()

        for _ in range(10000):
            if remaining <= _EPS:
                break

            if self.phase == ElevatorPhase.IDLE_CLOSED:
                self.velocity = 0.0
                if self._pending:
                    self._begin_next_request()
                    continue
                self.time_s += remaining
                remaining = 0.0
                continue

            if self.phase == ElevatorPhase.MOVING:
                if not self.doors_closed:
                    raise ElevatorInterlockError("motion attempted with doors open")
                if self._target_index is None:
                    raise ElevatorInterlockError("moving without a target landing")
                if self._motion_profile is None:
                    raise ElevatorInterlockError(
                        "moving without an acceleration profile"
                    )
                profile_remaining = (
                    self._motion_profile["total_time"] - self._motion_profile["elapsed"]
                )
                consume = min(remaining, profile_remaining)
                self._motion_profile["elapsed"] += consume
                self.time_s += consume
                remaining -= consume
                self._sample_motion_profile()
                if profile_remaining - consume <= _EPS:
                    self.car_z = self.spec.stop_z[self._target_index]
                    self.velocity = 0.0
                    self._motion_profile = None
                    self.phase = ElevatorPhase.LEVELING
                    self._phase_remaining = self.timing.leveling_time
                continue

            if self.phase == ElevatorPhase.LEVELING:
                self.velocity = 0.0
                consume = min(remaining, self._phase_remaining)
                self.time_s += consume
                remaining -= consume
                self._phase_remaining -= consume
                if self._phase_remaining <= _EPS:
                    if self._target_index is None:
                        raise ElevatorInterlockError(
                            "leveling without a target landing"
                        )
                    self._current_index = self._target_index
                    self.phase = ElevatorPhase.OPENING
                continue

            if self.phase == ElevatorPhase.OPENING:
                time_to_open = (1.0 - self._door_fraction) * self.timing.door_open_time
                if time_to_open <= _EPS:
                    self._set_door_fraction(1.0)
                    self.phase = ElevatorPhase.OPEN_DWELL
                    self._phase_remaining = self.timing.door_dwell_time
                    continue
                consume = min(remaining, time_to_open)
                self._set_door_fraction(
                    self._door_fraction + consume / self.timing.door_open_time
                )
                self.time_s += consume
                remaining -= consume
                if consume + _EPS >= time_to_open:
                    self._set_door_fraction(1.0)
                    self.phase = ElevatorPhase.OPEN_DWELL
                    self._phase_remaining = self.timing.door_dwell_time
                continue

            if self.phase == ElevatorPhase.OPEN_DWELL:
                consume = min(remaining, self._phase_remaining)
                self.time_s += consume
                remaining -= consume
                self._phase_remaining -= consume
                if self._phase_remaining <= _EPS:
                    self.phase = ElevatorPhase.CLOSING
                continue

            if self.phase == ElevatorPhase.CLOSING:
                time_to_close = self._door_fraction * self.timing.door_close_time
                if time_to_close <= _EPS:
                    self._set_door_fraction(0.0)
                    self.phase = ElevatorPhase.IDLE_CLOSED
                    self._target_index = None
                    continue
                consume = min(remaining, time_to_close)
                self._set_door_fraction(
                    self._door_fraction - consume / self.timing.door_close_time
                )
                self.time_s += consume
                remaining -= consume
                if consume + _EPS >= time_to_close:
                    self._set_door_fraction(0.0)
                    self.phase = ElevatorPhase.IDLE_CLOSED
                    self._target_index = None
                continue

            raise ElevatorInterlockError(f"unhandled controller phase {self.phase}")
        else:
            raise RuntimeError("elevator step exceeded transition safety limit")

        self.assert_invariants()
        return self.snapshot()


@dataclass(frozen=True)
class ElevatorAnimationPlan:
    snapshots: tuple[ElevatorSnapshot, ...]
    sample_period: float
    seed: int

    @property
    def duration(self) -> float:
        return self.snapshots[-1].time_s if self.snapshots else 0.0


def build_animation_plan(
    spec: ElevatorSpec,
    requests: Iterable[LevelId],
    *,
    initial_level: LevelId | None = None,
    timing: ElevatorTiming | None = None,
    sample_period: float = 1 / 24,
    max_duration: float = 600.0,
    seed: int = 0,
) -> ElevatorAnimationPlan:
    """Queue requests and sample an interlock-safe deterministic trajectory."""

    _positive("sample_period", sample_period)
    _positive("max_duration", max_duration)
    controller = ElevatorController(
        spec=spec,
        initial_level=initial_level,
        timing=timing,
        seed=seed,
    )
    for level in requests:
        controller.request(level)

    snapshots = [controller.snapshot()]
    while not controller.is_idle:
        if controller.time_s + sample_period > max_duration + _EPS:
            raise TimeoutError(
                f"elevator animation exceeded max_duration={max_duration} seconds"
            )
        snapshots.append(controller.step(sample_period))
    return ElevatorAnimationPlan(tuple(snapshots), float(sample_period), int(seed))


__all__ = [
    "ElevatorAnimationPlan",
    "ElevatorBuildMode",
    "ElevatorConfigurationError",
    "ElevatorController",
    "ElevatorInterlockError",
    "ElevatorPhase",
    "ElevatorSnapshot",
    "ElevatorSpec",
    "ElevatorTiming",
    "ElevatorVisualVariant",
    "LevelId",
    "build_animation_plan",
    "sample_visual_variant",
]
