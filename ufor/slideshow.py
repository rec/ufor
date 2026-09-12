"""Editable still-image performances and recorded operator decisions."""

from enum import StrEnum, auto
from fnmatch import fnmatchcase
from typing import Literal, Self

from pydantic import Field, model_validator

from .assets import Asset
from .base import Identifier, Model, unique
from .score import Score
from .time import Timebase


class Fit(StrEnum):
    contain = auto()
    cover = auto()
    stretch = auto()


class Advance(StrEnum):
    automatic = auto()
    manual = auto()
    cue = auto()


class VisualKind(StrEnum):
    image = auto()
    video = auto()


class ManualAudioPolicy(StrEnum):
    continue_ = 'continue'
    pause = auto()
    seek = auto()


class Crop(Model):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode='after')
    def inside_asset(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError('crop must remain inside the asset')
        return self


class DirectorySelection(Model):
    name: Identifier
    directory: str = Field(min_length=1)
    recursive: bool = False
    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)


class Slide(Model):
    name: Identifier
    asset: Identifier
    duration: int = Field(gt=0, strict=True)
    alt: str = Field(min_length=1)
    description: str | None = None
    crop: Crop = Crop(x=0, y=0, width=1, height=1)
    rotation: Literal[0, 90, 180, 270] = 0
    fit: Fit = Fit.contain
    advance: Advance = Advance.automatic
    cue: Identifier | None = None
    visual_kind: VisualKind = VisualKind.image
    source_start: int | None = Field(default=None, ge=0, strict=True)
    source_end: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode='after')
    def cue_policy(self) -> Self:
        if (self.advance == Advance.cue) != (self.cue is not None):
            raise ValueError('cue advance requires exactly one cue name')
        video_range = self.source_start is not None or self.source_end is not None
        if self.visual_kind == VisualKind.video:
            if (
                self.source_start is None
                or self.source_end is None
                or self.source_end <= self.source_start
            ):
                raise ValueError('video requires a finite source range')
        elif video_range:
            raise ValueError('only video declares a source range')
        return self


class Transition(Model):
    outgoing: Identifier
    incoming: Identifier
    kind: Literal['cut', 'crossfade', 'wipe'] = 'cut'
    duration: int = Field(default=0, ge=0, strict=True)


class Accompaniment(Model):
    asset: Identifier
    start: int = Field(ge=0, strict=True)
    source_start: int = Field(ge=0, strict=True)
    source_end: int = Field(gt=0, strict=True)

    @model_validator(mode='after')
    def source_range(self) -> Self:
        if self.source_end <= self.source_start:
            raise ValueError('accompaniment source end must exceed start')
        return self


class Caption(Model):
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    language: str = Field(min_length=2)
    text: str = Field(min_length=1)
    speaker: str | None = None

    @model_validator(mode='after')
    def interval(self) -> Self:
        if self.end <= self.start:
            raise ValueError('caption end must exceed start')
        return self


class CaptionTrack(Model):
    language: str = Field(min_length=2)
    captions: list[Caption] = Field(default_factory=list)
    asset: Identifier | None = None
    offset: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode='after')
    def source(self) -> Self:
        if bool(self.captions) == (self.asset is not None):
            raise ValueError('caption track requires captions or one caption asset')
        if any(
            b.start < a.end
            for a, b in zip(self.captions, self.captions[1:], strict=False)
        ):
            raise ValueError('captions must not overlap')
        return self


class RunEvent(Model):
    tick: int = Field(ge=0, strict=True)
    ordinal: int = Field(ge=0, strict=True)
    action: Literal[
        'enter', 'advance', 'back', 'hold', 'cue', 'transition', 'caption', 'failure'
    ]
    item: Identifier
    detail: str | None = None


class SlideshowRun(Model):
    events: list[RunEvent] = Field(default_factory=list)

    @model_validator(mode='after')
    def ordered(self) -> Self:
        if [(e.tick, e.ordinal) for e in self.events] != sorted(
            (e.tick, e.ordinal) for e in self.events
        ):
            raise ValueError('run events must be ordered by tick and ordinal')
        unique((str(e.ordinal) for e in self.events), 'run event ordinal')
        return self


class Slideshow(Model):
    assets: list[Asset]
    selections: list[DirectorySelection] = Field(default_factory=list)
    items: list[Slide] = Field(min_length=1)
    transitions: list[Transition] = Field(default_factory=list)
    default_advance: Advance = Advance.automatic
    accompaniment: Accompaniment | None = None
    manual_audio: ManualAudioPolicy = ManualAudioPolicy.continue_
    captions: list[CaptionTrack] = Field(default_factory=list)
    run: SlideshowRun | None = None

    @model_validator(mode='after')
    def references(self) -> Self:
        unique((a.name for a in self.assets), 'asset')
        unique((s.name for s in self.selections), 'selection')
        unique((i.name for i in self.items), 'slide')
        assets = {a.name for a in self.assets}
        names = {i.name for i in self.items}
        if any(i.asset not in assets for i in self.items):
            raise ValueError('slide references an unknown asset')
        for transition in self.transitions:
            if transition.outgoing not in names or transition.incoming not in names:
                raise ValueError('transition references an unknown slide')
            outgoing = next(
                i
                for i, slide in enumerate(self.items)
                if slide.name == transition.outgoing
            )
            if (
                outgoing + 1 == len(self.items)
                or transition.incoming != self.items[outgoing + 1].name
            ):
                raise ValueError('transition must join adjacent slides')
            incoming = self.items[outgoing + 1]
            if transition.duration > min(
                self.items[outgoing].duration, incoming.duration
            ):
                raise ValueError('transition exceeds a visible item duration')
        if self.accompaniment is not None and self.accompaniment.asset not in assets:
            raise ValueError('accompaniment references an unknown asset')
        for track in self.captions:
            if track.asset is not None and track.asset not in assets:
                raise ValueError('caption track references an unknown asset')
        if self.accompaniment is not None and not self.captions:
            raise ValueError('audible accompaniment requires captions')
        if self.run is not None and any(e.item not in names for e in self.run.events):
            raise ValueError('run event references an unknown slide')
        return self


class SlideshowScore(Score):
    kind: Literal['slideshow'] = 'slideshow'
    timebase: Timebase
    body: Slideshow


def resolve_selection(
    selection: DirectorySelection, candidates: list[str]
) -> list[str]:
    """Resolve normalized relative paths supplied by a host, without filesystem I/O."""
    prefix = selection.directory.rstrip('/') + '/'
    result = []
    for path in candidates:
        if (
            not path.startswith(prefix)
            or path.startswith('/')
            or '..' in path.split('/')
        ):
            continue
        relative = path[len(prefix) :]
        if not relative or (not selection.recursive and '/' in relative):
            continue
        if any(
            fnmatchcase(relative, pattern) or fnmatchcase(path, pattern)
            for pattern in selection.exclude
        ):
            continue
        if any(
            fnmatchcase(relative, pattern) or fnmatchcase(path, pattern)
            for pattern in selection.include
        ):
            result.append(path)
    return sorted(result)
