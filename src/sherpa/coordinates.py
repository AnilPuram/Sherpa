from sherpa.types import Dimensions, GroundedPoint


def image_to_viewport(
    point: GroundedPoint,
    image: Dimensions,
    viewport: Dimensions,
) -> GroundedPoint:
    if not 0 <= point.x <= image.width or not 0 <= point.y <= image.height:
        raise ValueError("Grounded point is outside the image")

    return GroundedPoint(
        x=point.x * viewport.width / image.width,
        y=point.y * viewport.height / image.height,
    )


def require_in_viewport(point: GroundedPoint, viewport: Dimensions) -> None:
    if not 0 <= point.x < viewport.width or not 0 <= point.y < viewport.height:
        raise ValueError("Point is outside the viewport")
