"""Decoded and encoded asset facts supplied by the importing application."""

from pydantic import Field

from .. import base


class EmbeddedLoop(base.Model):
    start_frame: base.Frame
    end_frame: base.Frame
    loop_type: int = 0


class AudioMetadata(base.Model):
    channels: int = Field(gt=0, strict=True)
    sample_rate: int = Field(gt=0, strict=True)
    encoding: str = Field(min_length=1)
    byte_length: int = Field(ge=0, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    frames: base.Frame
    embedded_loop: EmbeddedLoop | None = None
    embedded_loop_known: bool = False
