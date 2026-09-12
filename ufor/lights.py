"""Logical light geometry, component contracts, and physical wiring order."""

from enum import StrEnum, auto
from math import cos, sin, tau
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Model, unique


class Interpretation(StrEnum):
    drive = auto()
    linear_srgb = auto()


class Light(Model):
    name: Identifier
    position: list[float] = Field(min_length=1, max_length=3)


class Layout(Model):
    """List order is logical frame order; positions need not form a grid."""

    name: Identifier
    axes: list[Identifier] = Field(min_length=1, max_length=3)
    unit: Literal['metres', 'unitless'] = 'unitless'
    frame: Identifier = 'local'
    lights: list[Light] = Field(min_length=1)
    regions: dict[Identifier, list[Identifier]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def geometry(self) -> Self:
        unique(self.axes, 'layout axis')
        unique((p.name for p in self.lights), 'light name')
        names = {p.name for p in self.lights}
        if any(len(p.position) != len(self.axes) for p in self.lights):
            raise ValueError('positions must match layout axes')
        for region in self.regions.values():
            unique(region, 'region light')
            if not region or set(region) - names:
                raise ValueError('regions require known light names')
        return self


class Wiring(Model):
    """For each physical output slot, select a logical light by name."""

    order: list[Identifier] = Field(min_length=1)

    def indexes(self, layout: Layout) -> list[int]:
        names = [p.name for p in layout.lights]
        if len(self.order) != len(names) or set(self.order) != set(names):
            raise ValueError('wiring must be a permutation of layout light names')
        indexes = {n: i for i, n in enumerate(names)}
        return [indexes[n] for n in self.order]


class LightType(Model):
    family: Literal['sampled'] = 'sampled'
    quantity: Literal['light'] = 'light'
    timebase: Identifier
    components: list[Identifier] = Field(min_length=1)
    interpretation: Interpretation = Interpretation.drive
    layout: Layout

    @model_validator(mode='after')
    def component_contract(self) -> Self:
        unique(self.components, 'light component')
        if self.interpretation == Interpretation.linear_srgb and self.components != [
            'red',
            'green',
            'blue',
        ]:
            raise ValueError('linear_srgb requires red, green, blue in that order')
        return self


def strip(count: int, name: str = 'strip') -> Layout:
    if count <= 0:
        raise ValueError('strip count must be positive')
    return Layout(
        name=name,
        axes=['x'],
        lights=[Light(name=f'light_{i}', position=[i]) for i in range(count)],
    )


def matrix(width: int, height: int, name: str = 'matrix') -> Layout:
    if width <= 0 or height <= 0:
        raise ValueError('matrix dimensions must be positive')
    return Layout(
        name=name,
        axes=['x', 'y'],
        lights=[
            Light(name=f'light_{y * width + x}', position=[x, y])
            for y in range(height)
            for x in range(width)
        ],
    )


def serpentine(width: int, height: int) -> Wiring:
    layout = matrix(width, height)
    return Wiring(
        order=[
            layout.lights[y * width + x].name
            for y in range(height)
            for x in (range(width) if y % 2 == 0 else reversed(range(width)))
        ]
    )


def rings(counts: list[int], radii: list[float], name: str = 'rings') -> Layout:
    if not counts or len(counts) != len(radii):
        raise ValueError('each ring requires a count and radius')
    if any(c <= 0 for c in counts) or any(r <= 0 for r in radii):
        raise ValueError('ring counts and radii must be positive')
    lights = []
    regions = {}
    for ring, (count, radius) in enumerate(zip(counts, radii, strict=True)):
        region = [
            Light(
                name=f'ring_{ring}_{i}',
                position=[radius * cos(tau * i / count), radius * sin(tau * i / count)],
            )
            for i in range(count)
        ]
        regions[f'ring_{ring}'] = [p.name for p in region]
        lights.extend(region)
    return Layout(name=name, axes=['x', 'y'], lights=lights, regions=regions)
