"""Sample mappings, traversal settings, and modulation-source definitions."""

from typing import Self

from pydantic import StrictBool, model_validator

from .. import base
from . import enums


class Mapping(base.Model):
    lowest_key: base.Key
    highest_key: base.Key
    reference_pitch_hz: base.Frequency | None = None
    event_key: base.Key | None = None
    minimum_velocity: base.UnitInterval = 0.0
    maximum_velocity: base.UnitInterval = 1.0
    pitch_tracking: StrictBool = True

    @model_validator(mode='after')
    def ordered_ranges(self) -> Self:
        if self.lowest_key > self.highest_key:
            raise ValueError('lowest_key must not exceed highest_key')
        if self.pitch_tracking and self.reference_pitch_hz is None:
            raise ValueError('pitch_tracking requires reference_pitch_hz')
        if self.minimum_velocity > self.maximum_velocity:
            raise ValueError('minimum_velocity must not exceed maximum_velocity')
        return self


class Loop(base.Model):
    start_frame: base.Frame
    end_frame: base.Frame
    mode: enums.LoopMode = enums.LoopMode.until_release
    crossfade_frames: base.Frame = 0

    @model_validator(mode='after')
    def valid_interval(self) -> Self:
        length = self.end_frame - self.start_frame
        if length < 2:
            raise ValueError('A loop must contain at least two frames')
        if self.crossfade_frames and (
            self.crossfade_frames < 2 or 2 * self.crossfade_frames >= length
        ):
            raise ValueError(
                'Loop crossfade must have at least two frames '
                'and occupy less than half the loop'
            )
        return self


class Playback(base.Model):
    direction: enums.Direction = enums.Direction.forward
    mode: enums.PlaybackMode = enums.PlaybackMode.while_held


class SlotPlayback(base.Model):
    """None inherits the instrument traversal setting, including after serialization."""

    direction: enums.Direction | None = None
    mode: enums.PlaybackMode | None = None


class Slice(base.Model):
    id: base.Identifier
    asset: base.Identifier
    start_frame: base.Frame = 0
    end_frame: base.Frame
    loop: Loop | None = None

    @model_validator(mode='after')
    def contained_intervals(self) -> Self:
        if self.end_frame <= self.start_frame:
            raise ValueError('end_frame must exceed start_frame')
        if self.loop is not None and (
            self.loop.start_frame < self.start_frame
            or self.loop.end_frame > self.end_frame
        ):
            raise ValueError('Loop must be contained in the slice interval')
        return self
