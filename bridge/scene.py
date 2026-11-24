"""Builds the 3D radar drawn by Foxglove's 3D panel.

The bridge never draws anything itself. This module turns a list of
networks into shapes (a SceneUpdate message) and Foxglove renders them.

Layout, seen from above:
    - you are a blue sphere at the center (frame "base")
    - each Wi-Fi channel owns one slice of the circle
    - each network is a bar inside its channel's slice
    - stronger networks sit closer, stand taller, and are greener
    - faint rings mark -50, -70 and -90 dBm
"""

import hashlib
import math

from foxglove.messages import (
    Color,
    CubePrimitive,
    CylinderPrimitive,
    Duration,
    FrameTransform,
    LinePrimitive,
    LinePrimitiveLineType,
    Point3,
    Pose,
    Quaternion,
    SceneEntity,
    SceneUpdate,
    SpherePrimitive,
    TextPrimitive,
    Vector3,
)

import config

# ---------- Shared constants ----------

# The "no rotation" quaternion. Every shape in the radar uses it.
NO_ROTATION = Quaternion(x=0, y=0, z=0, w=1)

# A pose at the center of the frame, facing forward
ORIGIN = Pose(position=Vector3(x=0, y=0, z=0), orientation=NO_ROTATION)

# Colors are red, green, blue, alpha (opacity), each from 0 to 1
WHITE = Color(r=1, g=1, b=1, a=1)
GUIDE_GRAY = Color(r=0.6, g=0.6, b=0.6, a=0.35)
YOU_BLUE = Color(r=0.2, g=0.4, b=0.9, a=1)

# Signal levels that get a reference ring
RING_LEVELS_DBM = (-50, -70, -90)


# ---------- Math helpers ----------

def strength(rssi: float) -> float:
    """Convert RSSI in dBm to a strength from 0.0 (weak) to 1.0 (strong)."""
    s = (rssi - config.RSSI_WEAK) / (config.RSSI_STRONG - config.RSSI_WEAK)
    return max(0.0, min(1.0, s))


def strength_color(s: float, alpha: float = 1.0) -> Color:
    """Map strength to a color: 0 is red, 0.5 is yellow, 1 is green."""
    red = 1.0 if s < 0.5 else 1.0 - (s - 0.5) * 2
    green = s * 2 if s < 0.5 else 1.0
    return Color(r=red, g=green, b=0.1, a=alpha)


def stable_fraction(text: str) -> float:
    """Hash text into a number from 0 to 1. Same text always gives the same number."""
    digest = hashlib.sha1(text.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def rssi_to_distance(rssi: float) -> float:
    """Strong signals sit close to you, weak ones sit far away."""
    span = config.RADAR_MAX_DIST - config.RADAR_MIN_DIST
    return config.RADAR_MIN_DIST + (1 - strength(rssi)) * span


def slice_angle(channel: int, fraction: float) -> float:
    """Angle in radians for a point `fraction` of the way through a channel's slice."""
    slice_size = 2 * math.pi / config.CHANNELS
    index = max(1, min(channel, config.CHANNELS)) - 1  # channel 1 -> slice 0
    return (index + fraction) * slice_size


def radar_xy(channel: int, key: str, rssi: float) -> tuple[float, float]:
    """Floor position (x, y) of a network on the radar."""
    # Stay between 15% and 85% of the slice so bars don't sit on the slice lines
    angle = slice_angle(channel, 0.15 + 0.7 * stable_fraction(key))
    distance = rssi_to_distance(rssi)
    return distance * math.cos(angle), distance * math.sin(angle)


# ---------- Shape builders ----------

def text_label(x: float, y: float, z: float, text: str,
               size: float = 12, color: Color = WHITE) -> TextPrimitive:
    """Floating text that always faces the camera and stays the same size on screen."""
    return TextPrimitive(
        pose=Pose(position=Vector3(x=x, y=y, z=z), orientation=NO_ROTATION),
        billboard=True,          # always face the camera
        font_size=size,
        scale_invariant=True,    # same size on screen no matter the zoom
        color=color,
        text=text,
    )


def base_transform() -> FrameTransform:
    """Place frame 'base' (you) at the center of 'world', not rotated."""
    return FrameTransform(
        parent_frame_id="world",
        child_frame_id="base",
        translation=Vector3(x=0, y=0, z=0),
        rotation=NO_ROTATION,
    )


def you_entity() -> SceneEntity:
    """The blue sphere at the center, with a label."""
    return SceneEntity(
        frame_id="base",
        id="you",
        spheres=[SpherePrimitive(
            pose=Pose(position=Vector3(x=0, y=0, z=0.2), orientation=NO_ROTATION),
            size=Vector3(x=0.4, y=0.4, z=0.4),
            color=YOU_BLUE,
        )],
        texts=[text_label(0, 0, 0.7, "you", size=14)],
    )


def ring_entities() -> list[SceneEntity]:
    """Flat see-through discs marking signal levels, with dBm labels."""
    rings = []
    for level in RING_LEVELS_DBM:
        radius = rssi_to_distance(level)
        rings.append(SceneEntity(
            frame_id="base",
            id=f"ring{level}",
            cylinders=[CylinderPrimitive(
                pose=ORIGIN,
                size=Vector3(x=radius * 2, y=radius * 2, z=0.01),  # size is a diameter
                bottom_scale=1,
                top_scale=1,
                color=Color(r=0.6, g=0.6, b=0.6, a=0.08),
            )],
            texts=[text_label(radius, 0, 0.05, f"{level} dBm", size=10, color=GUIDE_GRAY)],
        ))
    return rings


def channel_slices_entity() -> SceneEntity:
    """Lines dividing the circle into one slice per channel, with labels."""
    edge = config.RADAR_MAX_DIST + 0.5
    points = []
    labels = []
    for channel in range(1, config.CHANNELS + 1):
        # One line from the center to the edge at the start of each slice
        start = slice_angle(channel, 0.0)
        points.append(Point3(x=0, y=0, z=0.01))
        points.append(Point3(x=edge * math.cos(start), y=edge * math.sin(start), z=0.01))

        # Label in the middle of the slice, just past the edge
        middle = slice_angle(channel, 0.5)
        labels.append(text_label(
            (edge + 0.4) * math.cos(middle),
            (edge + 0.4) * math.sin(middle),
            0.05,
            f"ch {channel}",
            size=11,
            color=GUIDE_GRAY,
        ))

    return SceneEntity(
        frame_id="base",
        id="slices",
        lines=[LinePrimitive(
            type=LinePrimitiveLineType.LineList,  # every 2 points form one line
            pose=ORIGIN,
            thickness=1,
            scale_invariant=True,  # thickness in screen pixels
            points=points,
            color=GUIDE_GRAY,
        )],
        texts=labels,
    )


def network_entity(net: dict) -> SceneEntity:
    """One bar and label for one network."""
    s = strength(net["rssi"])
    x, y = radar_xy(net["ch"], net["id"], net["rssi"])
    height = 0.1 + s * config.BAR_MAX_HEIGHT  # never fully flat

    return SceneEntity(
        frame_id="base",
        id=net["id"],  # same id every scan, so Foxglove replaces the old bar
        lifetime=Duration(sec=config.BAR_LIFETIME_SEC, nsec=0),
        cubes=[CubePrimitive(
            # A cube's position is its center, so raise it by half its height
            pose=Pose(position=Vector3(x=x, y=y, z=height / 2), orientation=NO_ROTATION),
            size=Vector3(x=config.BAR_WIDTH, y=config.BAR_WIDTH, z=height),
            color=strength_color(s, alpha=1.0 if net["mine"] else 0.85),
        )],
        texts=[text_label(x, y, height + 0.3, f'{net["label"]}  {net["rssi"]}')],
    )


# ---------- Public entry point ----------

def build_scene(networks: list[dict]) -> SceneUpdate:
    """Build the whole radar for one scan."""
    guides = [you_entity(), *ring_entities(), channel_slices_entity()]
    bars = [network_entity(net) for net in networks]
    return SceneUpdate(entities=guides + bars)