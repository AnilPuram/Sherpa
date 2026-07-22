import pytest

from sherpa.coordinates import image_to_viewport, require_in_viewport
from sherpa.types import Dimensions, GroundedPoint


def test_image_to_viewport_scales_each_axis() -> None:
    point = image_to_viewport(
        GroundedPoint(x=100, y=50),
        Dimensions(width=200, height=100),
        Dimensions(width=1000, height=500),
    )

    assert point == GroundedPoint(x=500, y=250)


def test_image_to_viewport_rejects_point_outside_image() -> None:
    with pytest.raises(ValueError, match="outside the image"):
        image_to_viewport(
            GroundedPoint(x=201, y=50),
            Dimensions(width=200, height=100),
            Dimensions(width=1000, height=500),
        )


def test_viewport_excludes_bottom_right_boundary() -> None:
    with pytest.raises(ValueError, match="outside the viewport"):
        require_in_viewport(
            GroundedPoint(x=1000, y=500),
            Dimensions(width=1000, height=500),
        )
