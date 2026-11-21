"""Determine physical and logical release phases for an instrument event."""

from typing import Annotated, Literal

from pydantic import Field

from .base import Bipolar, Identifier, Model, UnitInterval
from .instrument_trace import ActiveTrigger
from .samples.enums import TriggerKind


class KeyRelease(Model):
    kind: Literal['key_release'] = 'key_release'
    part: Identifier
    trigger_id: Identifier
    sustain_pressed: bool


class PedalChange(Model):
    kind: Literal['pedal_change'] = 'pedal_change'
    part: Identifier
    was_pressed: bool
    value: Bipolar
    threshold: UnitInterval


class ReleaseRequest(Model):
    triggers: list[ActiveTrigger]
    event: Annotated[KeyRelease | PedalChange, Field(discriminator='kind')]


class ReleasePlan(Model):
    unknown_release: bool = False
    physical_index: int | None = None
    logical_indices: list[int] = Field(default_factory=list)
    sustain_pressed: bool | None = None
    sustain_trigger: TriggerKind | None = None


def plan_release(request: ReleaseRequest) -> ReleasePlan:
    event = request.event
    if isinstance(event, KeyRelease):
        for index, trigger in enumerate(request.triggers):
            if (trigger.part, trigger.trigger_id) == (event.part, event.trigger_id):
                if trigger.physically_released:
                    return ReleasePlan()
                return ReleasePlan(
                    physical_index=index,
                    logical_indices=[] if event.sustain_pressed else [index],
                )
        return ReleasePlan(unknown_release=True)

    pressed = event.value >= event.threshold
    if pressed == event.was_pressed:
        return ReleasePlan(sustain_pressed=pressed)
    if pressed:
        return ReleasePlan(
            sustain_pressed=True, sustain_trigger=TriggerKind.sustain_press
        )
    return ReleasePlan(
        sustain_pressed=False,
        sustain_trigger=TriggerKind.sustain_release,
        logical_indices=[
            i
            for i, t in enumerate(request.triggers)
            if t.part == event.part and t.physically_released and not t.logical_released
        ],
    )
