"""Portable audio encoding names, independent of codec implementations."""

from enum import StrEnum, auto


class Format(StrEnum):
    flac = auto()
    mp3 = auto()
    ogg = auto()
    raw = auto()
    rf64 = auto()
    wav = auto()

    _default = flac


class Subtype(StrEnum):
    alac_16 = auto()
    alac_20 = auto()
    alac_24 = auto()
    alac_32 = auto()
    double = auto()
    float = auto()
    mpeg_layer_i = auto()
    mpeg_layer_ii = auto()
    mpeg_layer_iii = auto()
    opus = auto()
    pcm_16 = auto()
    pcm_24 = auto()
    pcm_32 = auto()
    pcm_s8 = auto()
    pcm_u8 = auto()
    vorbis = auto()
