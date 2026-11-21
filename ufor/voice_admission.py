"""Retire existing voices before starting an instrument's selected batch."""

from typing import Annotated

from pydantic import Field

from .base import Identifier, NoteKey
from .instrument_trace import ActiveVoice, RetirementCause, TraceAction, VoiceRetirement
from .samples import enums
from .samples.selection import Choke, VoicePolicy


class VoiceAdmission(TraceAction):
    part: Identifier
    key: NoteKey | None
    voices: list[ActiveVoice]
    chokes: list[Choke]
    count: int = Field(strict=True, ge=0)
    policy: VoicePolicy | None = None
    pool_counts: dict[Identifier, Annotated[int, Field(strict=True, ge=0)]] = Field(
        default_factory=dict
    )
    pools: dict[Identifier, VoicePolicy] = Field(default_factory=dict)
    pool_by_template: dict[Identifier, Identifier | None] = Field(default_factory=dict)


def plan_retirements(batch: VoiceAdmission) -> list[VoiceRetirement]:
    """Apply chokes, per-part pools, then the global voice policy."""
    voices = batch.voices.copy()
    actions: list[VoiceRetirement] = []
    for voice in batch.voices:
        if voice.part != batch.part:
            continue
        rules = [c for c in batch.chokes if c.group == voice.choke_group]
        if not rules:
            continue
        modes = {c.mode for c in rules}
        fade = None
        if enums.ChokeMode.immediate in modes:
            action = 'stop'
        elif modes == {enums.ChokeMode.release}:
            action = 'release'
        elif modes == {enums.ChokeMode.fade}:
            action = 'fade'
            fade = min(c.fade_seconds for c in rules if c.fade_seconds is not None)
        else:
            raise ValueError(
                'combined fade and envelope-release chokes are unsupported'
            )
        actions.append(
            VoiceRetirement(
                tick=batch.tick,
                ordinal=batch.ordinal,
                voice_id=voice.voice_id,
                cause=RetirementCause.choke,
                action=action,
                fade_seconds=fade,
            )
        )
        voices.remove(voice)

    def apply(policy: VoicePolicy, count: int, pool: Identifier | None = None) -> None:
        if count > policy.maximum_voices:
            if pool is not None:
                raise ValueError(f'trigger batch exceeds voice pool {pool} limit')
            raise ValueError('trigger batch exceeds maximum_voices')
        scoped = (
            voices.copy()
            if pool is None
            else [
                v
                for v in voices
                if v.part == batch.part and batch.pool_by_template[v.template] == pool
            ]
        )
        if batch.key is not None and policy.same_key != enums.SameKey.stack:
            action = 'release' if policy.same_key == enums.SameKey.release else 'stop'
            for voice in [
                v for v in scoped if v.part == batch.part and v.key == batch.key
            ]:
                actions.append(
                    VoiceRetirement(
                        tick=batch.tick,
                        ordinal=batch.ordinal,
                        voice_id=voice.voice_id,
                        cause=RetirementCause.same_key,
                        action=action,
                    )
                )
                scoped.remove(voice)
                voices.remove(voice)
        overflow = len(scoped) - (policy.maximum_voices - count)
        action = (
            'release'
            if policy.overflow == enums.VoiceOverflow.release_oldest
            else 'stop'
        )
        for voice in scoped[: max(0, overflow)]:
            actions.append(
                VoiceRetirement(
                    tick=batch.tick,
                    ordinal=batch.ordinal,
                    voice_id=voice.voice_id,
                    cause=RetirementCause.voice_limit,
                    action=action,
                )
            )
            voices.remove(voice)

    for pool, count in sorted(batch.pool_counts.items()):
        apply(batch.pools[pool], count, pool)
    if batch.policy is not None:
        apply(batch.policy, batch.count)
    return actions
