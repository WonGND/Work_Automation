"""2D similarity transform with optional reflection (MCAD drawing → ECAD board frame).

    p_board = s · R · M · p_drawing + t

* ``M = diag(−1, 1)`` when ``mirror`` is set (a bottom-view drawing is the
  board seen from below, i.e. mirrored about the y axis), identity otherwise.
* ``R`` is a proper rotation by ``angle`` (CCW, radians).
* ``s`` is a uniform scale (1 unless unit-error detection is enabled).

The parameters are estimated in closed form by the weighted Umeyama/Kabsch
method (see :func:`pcbsim.registration.solve.umeyama`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from shapely import affinity
from shapely.geometry.base import BaseGeometry

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Similarity2D:
    angle: float = 0.0
    tx: float = 0.0
    ty: float = 0.0
    scale: float = 1.0
    mirror: bool = False

    @property
    def linear(self) -> FloatArray:
        """2×2 matrix ``s · R · M``."""
        c, s = math.cos(self.angle), math.sin(self.angle)
        rot = np.array([[c, -s], [s, c]])
        m = np.diag([-1.0, 1.0]) if self.mirror else np.eye(2)
        out: FloatArray = self.scale * rot @ m
        return out

    @property
    def angle_deg(self) -> float:
        a = math.degrees(self.angle) % 360.0
        return a - 360.0 if a > 180.0 else a

    def apply(self, points: ArrayLike) -> FloatArray:
        p = np.atleast_2d(np.asarray(points, dtype=np.float64))
        out: FloatArray = p @ self.linear.T + np.array([self.tx, self.ty])
        return out

    def apply_angle(self, angle_deg: float) -> float:
        """Map an in-plane orientation (degrees CCW) through the transform."""
        a = -angle_deg if self.mirror else angle_deg
        return (a + math.degrees(self.angle)) % 360.0

    def apply_geometry(self, geom: BaseGeometry) -> BaseGeometry:
        a = self.linear
        return affinity.affine_transform(
            geom, [a[0, 0], a[0, 1], a[1, 0], a[1, 1], self.tx, self.ty]
        )

    def inverse(self) -> Similarity2D:
        inv_lin = np.linalg.inv(self.linear)
        t = -inv_lin @ np.array([self.tx, self.ty])
        # inverse of s·R(θ)·M is (1/s)·M·R(−θ) = (1/s)·R(±θ)·M
        ang = self.angle if self.mirror else -self.angle
        return Similarity2D(ang, float(t[0]), float(t[1]), 1.0 / self.scale, self.mirror)

    def distance_to(self, other: Similarity2D, extent: float) -> float:
        """Max displacement between the two transforms over a square of half-size ``extent``."""
        corners = np.array(
            [[-extent, -extent], [extent, -extent], [extent, extent], [-extent, extent]]
        )
        return float(np.linalg.norm(self.apply(corners) - other.apply(corners), axis=1).max())

    def to_dict(self) -> dict[str, Any]:
        return {
            "rotation_deg": self.angle_deg,
            "translation_m": [self.tx, self.ty],
            "scale": self.scale,
            "mirror": self.mirror,
            "matrix": [[float(v) for v in row] for row in self.linear],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Similarity2D:
        return cls(
            math.radians(float(d["rotation_deg"])),
            float(d["translation_m"][0]),
            float(d["translation_m"][1]),
            float(d.get("scale", 1.0)),
            bool(d.get("mirror", False)),
        )
