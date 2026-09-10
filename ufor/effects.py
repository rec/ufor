"""Portable RGB effect settings extracted from Lyte; no rendering dependencies."""

from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

from .base import Model

RGB = Annotated[
    list[Annotated[int, Field(ge=0, le=255, strict=True)]],
    Field(min_length=3, max_length=3),
]
FloatRGB = Annotated[list[float], Field(min_length=3, max_length=3)]


class Effect(Model):
    family: ClassVar[str]


class ColorChase(Effect):
    effect: Literal['color_chase'] = 'color_chase'
    family: ClassVar[str] = 'events'
    color: RGB = [255, 0, 0]
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_color_chase(self) -> Self:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        validate_start(self.start)
        return self


class ConfettiWithDecay(Effect):
    effect: Literal['confetti_with_decay'] = 'confetti_with_decay'
    family: ClassVar[str] = 'events'
    palette: list[RGB] = [[255, 40, 80], [255, 220, 40], [30, 220, 180], [80, 100, 255]]
    spawn_rate: float = Field(default=8.0, ge=0)
    decay: float = Field(default=2.5, gt=0)
    width: int = Field(default=1, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_confetti_with_decay(self) -> Self:
        validate_palette(self.palette)
        return self


class ExpandingRipples(Effect):
    effect: Literal['expanding_ripples'] = 'expanding_ripples'
    family: ClassVar[str] = 'events'
    palette: list[RGB] = [[40, 120, 255], [20, 255, 180], [220, 80, 255]]
    origins: list[float] = Field(default_factory=lambda: [0.5])
    event_rate: float = Field(default=0.35, ge=0)
    propagation_speed: float = Field(default=12.0, gt=0)
    width: float = Field(default=1.8, gt=0)
    decay: float = Field(default=0.7, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_expanding_ripples(self) -> Self:
        validate_palette(self.palette)
        if not self.origins:
            raise ValueError('origins must not be empty')
        if any(v < 0 or v > 1 for v in self.origins):
            raise ValueError('origins must be between zero and one')
        return self


class FireFlies(Effect):
    effect: Literal['fire_flies'] = 'fire_flies'
    family: ClassVar[str] = 'events'
    colors: list[RGB] = [[255, 0, 0]]
    width: int = 1
    count: int = 1
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode='after')
    def validate_fire_flies(self) -> Self:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        if self.count < 1:
            raise ValueError('count must be at least 1')
        validate_start(self.start)
        return self


class LarsonScanner(Effect):
    effect: Literal['larson_scanner'] = 'larson_scanner'
    family: ClassVar[str] = 'events'
    color: RGB = [255, 0, 0]
    tail: int = 2
    start: int = 0
    end: int | None = None
    step: int = 1
    rainbow: bool = False

    @model_validator(mode='after')
    def validate_larson_scanner(self) -> Self:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.tail < 0:
            raise ValueError('tail must not be negative')
        validate_start(self.start)
        return self


class LightningStorm(Effect):
    effect: Literal['lightning_storm'] = 'lightning_storm'
    family: ClassVar[str] = 'events'
    color: RGB = [200, 220, 255]
    flash_rate: float = Field(default=0.35, gt=0)
    maximum_burst: int = Field(default=4, gt=0)
    branch_width: float = Field(default=5.0, gt=0)
    afterglow: float = Field(default=8.0, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_lightning_storm(self) -> Self:
        validate_rgb(self.color)
        return self


class PacketTraffic(Effect):
    effect: Literal['packet_traffic'] = 'packet_traffic'
    family: ClassVar[str] = 'events'
    palette: list[RGB] = [[50, 220, 255], [255, 70, 130], [255, 210, 50]]
    direction: Literal['forward', 'reverse', 'both'] = 'both'
    packet_rate: float = Field(default=1.2, ge=0)
    minimum_length: int = Field(default=4, gt=1)
    maximum_length: int = Field(default=12, gt=1)
    error_rate: float = Field(default=0.15, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_packet_traffic(self) -> Self:
        validate_palette(self.palette)
        if self.maximum_length < self.minimum_length:
            raise ValueError('maximum_length must be at least minimum_length')
        return self


class PixelPingPong(Effect):
    effect: Literal['pixel_ping_pong'] = 'pixel_ping_pong'
    family: ClassVar[str] = 'events'
    color: RGB = [255, 255, 255]
    max_led: int | None = None
    total_pixels: int = 1
    fade_delay: int = 1

    @model_validator(mode='after')
    def validate_pixel_ping_pong(self) -> Self:
        validate_rgb(self.color)
        if self.total_pixels < 1:
            raise ValueError('total_pixels must be at least 1')
        if self.fade_delay < 1:
            raise ValueError('fade_delay must be at least 1')
        return self


class Pulse(Effect):
    effect: Literal['pulse'] = 'pulse'
    family: ClassVar[str] = 'events'
    colors: list[RGB] = [[255, 0, 0]]
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    seed: int | None = None

    @model_validator(mode='after')
    def validate_pulse(self) -> Self:
        validate_palette(self.colors)
        if self.tail < 0:
            raise ValueError('tail must not be negative')
        if self.chance < 0 or self.chance > 100:
            raise ValueError('chance must be between 0 and 100')
        if self.min_speed < 1 or self.max_speed <= self.min_speed:
            raise ValueError('min_speed and max_speed must define a non-empty range')
        return self


class Rain(Effect):
    effect: Literal['rain'] = 'rain'
    family: ClassVar[str] = 'events'
    colors: list[RGB] = [[70, 70, 70], [35, 35, 35], [80, 20, 20], [20, 80, 20]]
    rate: float = 10
    seed: int | None = None

    @model_validator(mode='after')
    def validate_rain(self) -> Self:
        validate_palette(self.colors)
        if self.rate <= 0:
            raise ValueError('rate must be greater than zero')
        return self


class Searchlights(Effect):
    effect: Literal['searchlights'] = 'searchlights'
    family: ClassVar[str] = 'events'
    colors: list[RGB] = [[60, 179, 113], [147, 112, 219], [199, 21, 133]]
    tail: int = 5
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode='after')
    def validate_searchlights(self) -> Self:
        validate_palette(self.colors)
        if len(self.colors) < 3:
            raise ValueError('colors must contain at least three colors')
        if self.tail < 0:
            raise ValueError('tail must not be negative')
        validate_start(self.start)
        return self


class TwinkleSettings(Effect):
    family: ClassVar[str] = 'events'
    colors: list[RGB] = [[255, 0, 0], [0, 255, 0], [0, 0, 255]]
    density: int = 20
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    @model_validator(mode='after')
    def validate_twinkle(self) -> Self:
        validate_palette(self.colors)
        return self


class Aurora(Effect):
    effect: Literal['aurora'] = 'aurora'
    family: ClassVar[str] = 'fields'
    palette: list[RGB] = [
        [20, 220, 120],
        [30, 100, 255],
        [180, 40, 255],
        [10, 255, 210],
    ]
    band_count: int = Field(default=4, gt=0)
    softness: float = Field(default=0.16, gt=0)
    intensity: float = Field(default=0.8, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_aurora(self) -> Self:
        validate_palette(self.palette)
        return self


class CandleBank(Effect):
    effect: Literal['candle_bank'] = 'candle_bank'
    family: ClassVar[str] = 'fields'
    color: RGB = [255, 120, 30]
    zone_size: int = Field(default=8, gt=0)
    base_level: float = Field(default=0.55, ge=0, le=1)
    flicker: float = Field(default=0.18, ge=0, le=1)
    flare_rate: float = Field(default=0.3, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_candle_bank(self) -> Self:
        validate_rgb(self.color)
        return self


class ColorFade(Effect):
    effect: Literal['color_fade'] = 'color_fade'
    family: ClassVar[str] = 'fields'
    colors: list[RGB] = [[255, 0, 0]]
    level_step: int = 5
    start: int = 0
    end: int | None = None

    @model_validator(mode='after')
    def validate_color_fade(self) -> Self:
        validate_palette(self.colors)
        if self.level_step < 1:
            raise ValueError('level_step must be at least 1')
        validate_start(self.start)
        return self


class ExponentialFade(Effect):
    effect: Literal['exponential_fade'] = 'exponential_fade'
    family: ClassVar[str] = 'fields'
    ratio: float = 0.98
    color: RGB = [255, 0, 0]

    @model_validator(mode='after')
    def validate_exponential_fade(self) -> Self:
        if not 0 <= self.ratio < 1:
            raise ValueError('ratio must be between zero and one')
        validate_rgb(self.color)
        return self


class HalvesRainbow(Effect):
    effect: Literal['halves_rainbow'] = 'halves_rainbow'
    family: ClassVar[str] = 'fields'
    max_led: int | None = None
    center_out: bool = True
    rainbow_inc: int = 4
    step: int = 1

    @model_validator(mode='after')
    def validate_halves_rainbow(self) -> Self:
        validate_step(self.step)
        if self.rainbow_inc < 0:
            raise ValueError('rainbow_inc must not be negative')
        return self


class Interference(Effect):
    effect: Literal['interference'] = 'interference'
    family: ClassVar[str] = 'fields'
    palette: list[RGB] = [[5, 0, 20], [200, 20, 120], [30, 220, 255]]
    wavelengths: list[float] = Field(default_factory=lambda: [13.0, 23.0, 37.0])
    rates: list[float] = Field(default_factory=lambda: [1.0, -0.63, 0.37])
    phase_offsets: list[float] = Field(default_factory=lambda: [0.0, 1.7, 3.1])
    contrast: float = Field(default=1.4, gt=0)
    speed: float = Field(default=1.0, ge=0)

    @model_validator(mode='after')
    def validate_interference(self) -> Self:
        validate_palette(self.palette)
        if not self.wavelengths:
            raise ValueError('wavelengths must not be empty')
        if len(self.wavelengths) != len(self.rates) or len(self.rates) != len(
            self.phase_offsets
        ):
            raise ValueError(
                'wavelengths, rates, and phase_offsets must have equal size'
            )
        if any(v <= 0 for v in self.wavelengths):
            raise ValueError('wavelengths must be greater than zero')
        return self


class LinearGradient(Effect):
    effect: Literal['linear_gradient'] = 'linear_gradient'
    family: ClassVar[str] = 'fields'
    start: float = 1
    end: float = 0
    mask: FloatRGB = [1, 1, 1]


class LinearRainbow(Effect):
    effect: Literal['linear_rainbow'] = 'linear_rainbow'
    family: ClassVar[str] = 'fields'
    max_led: int | None = None
    individual_pixel: bool = False
    step: int = 1

    @model_validator(mode='after')
    def validate_linear_rainbow(self) -> Self:
        validate_step(self.step)
        return self


class LogGradient(Effect):
    effect: Literal['log_gradient'] = 'log_gradient'
    family: ClassVar[str] = 'fields'
    start: float = 1
    end: float = 0
    base: float = 10
    mask: FloatRGB = [1, 1, 1]


class OceanCurrent(Effect):
    effect: Literal['ocean_current'] = 'ocean_current'
    family: ClassVar[str] = 'fields'
    palette: list[RGB] = [[0, 5, 20], [0, 50, 120], [0, 170, 210], [180, 255, 255]]
    wave_count: int = Field(default=3, gt=0)
    crest_rate: float = Field(default=0.8, ge=0)
    turbulence: float = Field(default=0.2, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_ocean_current(self) -> Self:
        validate_palette(self.palette)
        return self


class PaletteConveyor(Effect):
    effect: Literal['palette_conveyor'] = 'palette_conveyor'
    family: ClassVar[str] = 'fields'
    palette: list[RGB] = [[255, 0, 80], [255, 180, 0], [0, 220, 140], [30, 80, 255]]
    stop_spacing: float = Field(default=8.0, gt=0)
    speed: float = Field(default=1.0, ge=0)
    reverse: bool = False
    interpolation: Literal['linear', 'smooth'] = 'smooth'

    @model_validator(mode='after')
    def validate_palette_conveyor(self) -> Self:
        validate_palette(self.palette)
        return self


class RainbowSettings(Effect):
    family: ClassVar[str] = 'fields'
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_rainbow(self) -> Self:
        validate_step(self.step)
        validate_start(self.start)
        return self


class Wave(Effect):
    effect: Literal['wave'] = 'wave'
    family: ClassVar[str] = 'fields'
    color: RGB = [255, 0, 0]
    cycles: int = 2
    start: int = 0
    end: int | None = None
    moving: bool = False

    @model_validator(mode='after')
    def validate_wave(self) -> Self:
        validate_rgb(self.color)
        if self.cycles < 1:
            raise ValueError('cycles must be at least 1')
        validate_start(self.start)
        return self


class Alternates(Effect):
    effect: Literal['alternates'] = 'alternates'
    family: ClassVar[str] = 'patterns'
    color1: RGB = [255, 255, 255]
    color2: RGB = [0, 0, 0]
    max_led: int | None = None

    @model_validator(mode='after')
    def validate_alternates(self) -> Self:
        validate_rgb(self.color1)
        validate_rgb(self.color2)
        return self


class ColorFill(Effect):
    effect: Literal['color_fill'] = 'color_fill'
    family: ClassVar[str] = 'patterns'
    color: RGB = [255, 0, 0]

    @model_validator(mode='after')
    def validate_color_fill(self) -> Self:
        validate_rgb(self.color)
        return self


class ColorPattern(Effect):
    effect: Literal['color_pattern'] = 'color_pattern'
    family: ClassVar[str] = 'patterns'
    colors: list[RGB] = [[255, 0, 0], [0, 255, 0], [0, 0, 255]]
    width: int = 1
    reverse: bool = False

    @model_validator(mode='after')
    def validate_color_pattern(self) -> Self:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        return self


class ColorWipe(Effect):
    effect: Literal['color_wipe'] = 'color_wipe'
    family: ClassVar[str] = 'patterns'
    color: RGB = [255, 0, 0]
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_color_wipe(self) -> Self:
        validate_rgb(self.color)
        validate_step(self.step)
        validate_start(self.start)
        return self


class GreyCode(Effect):
    effect: Literal['grey_code'] = 'grey_code'
    family: ClassVar[str] = 'patterns'
    offsets: FloatRGB = [0, 100, 200]
    speeds: FloatRGB = [-0.01, 0.023, 0.014]


class Hamiltonian(Effect):
    effect: Literal['hamiltonian'] = 'hamiltonian'
    family: ClassVar[str] = 'patterns'
    speed: float = 25
    n: int = 8
    order: str | int = 'rgb'
    inverted: str = ''
    pre_fill: bool = False

    @model_validator(mode='after')
    def validate_hamiltonian(self) -> Self:
        if self.speed < 0:
            raise ValueError('speed must not be negative')
        validate_hamiltonian(self.n, self.order, self.inverted)
        return self


class SaberBlade(Effect):
    effect: Literal['saber_blade'] = 'saber_blade'
    family: ClassVar[str] = 'patterns'
    colors: list[RGB] = [[255, 0, 0]]
    speed: int = 1

    @model_validator(mode='after')
    def validate_saber_blade(self) -> Self:
        validate_palette(self.colors)
        if self.speed == 0:
            raise ValueError('speed must not be zero')
        return self


class CellularAutomaton(Effect):
    effect: Literal['cellular_automaton'] = 'cellular_automaton'
    family: ClassVar[str] = 'simulations'
    palette: list[RGB] = [[0, 0, 0], [20, 40, 120], [40, 220, 180], [255, 240, 120]]
    rule: int = Field(default=110, ge=0, le=255)
    initial_density: float = Field(default=0.25, ge=0, le=1)
    generation_rate: float = Field(default=10.0, gt=0)
    history_decay: float = Field(default=1.8, gt=0)
    boundary_mode: Literal['bounded', 'ring'] = 'ring'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_cellular_automaton(self) -> Self:
        validate_palette(self.palette)
        return self


class CollidingParticles(Effect):
    effect: Literal['colliding_particles'] = 'colliding_particles'
    family: ClassVar[str] = 'simulations'
    palette: list[RGB] = [
        [255, 50, 30],
        [255, 220, 40],
        [30, 220, 180],
        [80, 100, 255],
        [220, 50, 255],
    ]
    particle_count: int = Field(default=5, gt=0)
    radius: float = Field(default=1.5, gt=0)
    trail_decay: float = Field(default=4.0, gt=0)
    collision_flash: float = Field(default=0.7, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_colliding_particles(self) -> Self:
        validate_palette(self.palette)
        return self


class FireAndEmbers(Effect):
    effect: Literal['fire_and_embers'] = 'fire_and_embers'
    family: ClassVar[str] = 'simulations'
    palette: list[RGB] = [
        [0, 0, 0],
        [120, 0, 0],
        [255, 50, 0],
        [255, 190, 20],
        [255, 255, 220],
    ]
    cooling: float = Field(default=1.4, gt=0)
    diffusion: float = Field(default=4.0, ge=0)
    spark_rate: float = Field(default=12.0, ge=0)
    wind: float = 3.0
    origin: Literal['start', 'end'] = 'start'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_fire_and_embers(self) -> Self:
        validate_palette(self.palette)
        return self


class PartyMode(Effect):
    effect: Literal['party_mode'] = 'party_mode'
    family: ClassVar[str] = 'simulations'
    colors: list[RGB] = [[255, 0, 0], [0, 255, 0], [0, 0, 255]]

    @model_validator(mode='after')
    def validate_party_mode(self) -> Self:
        validate_palette(self.colors)
        return self


class RandomWalk(Effect):
    effect: Literal['random_walk'] = 'random_walk'
    family: ClassVar[str] = 'simulations'
    speed: float = 10
    variance: float = 1
    bounds: Annotated[list[float], Field(min_length=2, max_length=2)] = [0, 180]
    color: FloatRGB | None = None
    period: float = 0
    pre_fill: bool = False
    seed: int | None = None

    @model_validator(mode='after')
    def validate_random_walk(self) -> Self:
        if self.speed < 0:
            raise ValueError('speed must not be negative')
        if self.variance < 0:
            raise ValueError('variance must not be negative')
        low, high = self.bounds
        if low >= high:
            raise ValueError('bounds must be ordered low, high')
        if self.period * self.speed == 1:
            raise ValueError('period * speed must not equal 1')
        return self


class Randomize(Effect):
    effect: Literal['randomize'] = 'randomize'
    family: ClassVar[str] = 'simulations'
    seed: int | None = None


class ReactionDiffusionStrip(Effect):
    effect: Literal['reaction_diffusion_strip'] = 'reaction_diffusion_strip'
    family: ClassVar[str] = 'simulations'
    palette: list[RGB] = [[5, 0, 20], [40, 20, 130], [20, 190, 190], [240, 230, 120]]
    activator_diffusion: float = Field(default=0.16, gt=0)
    inhibitor_diffusion: float = Field(default=0.08, gt=0)
    feed_rate: float = Field(default=0.035, gt=0)
    kill_rate: float = Field(default=0.06, gt=0)
    steps_per_second: float = Field(default=80.0, gt=0)
    boundary_mode: Literal['bounded', 'ring'] = 'ring'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_reaction_diffusion_strip(self) -> Self:
        validate_palette(self.palette)
        return self


class Rainbow(RainbowSettings):
    effect: Literal['rainbow'] = 'rainbow'


class Twinkle(TwinkleSettings):
    effect: Literal['twinkle'] = 'twinkle'


class RainbowCycle(RainbowSettings):
    effect: Literal['rainbow_cycle'] = 'rainbow_cycle'


class WhiteTwinkle(TwinkleSettings):
    effect: Literal['white_twinkle'] = 'white_twinkle'
    colors: list[RGB] = [[255, 255, 255]]
    density: int = 80


def validate_rgb(color: list[int]) -> None:
    if len(color) != 3 or any(c < 0 or c > 255 for c in color):
        raise ValueError('RGB requires three values between 0 and 255')


def validate_palette(colors: list[RGB]) -> None:
    if not colors:
        raise ValueError('palette must not be empty')
    for color in colors:
        validate_rgb(color)


def validate_start(start: int) -> None:
    if start < 0:
        raise ValueError('start must not be negative')


def validate_step(step: int) -> None:
    if step < 1:
        raise ValueError('step must be at least 1')


def validate_hamiltonian(n: int, order: str | int, inverted: str) -> None:
    if n <= 2 or n % 2:
        raise ValueError('n must be even and greater than 2')
    if (isinstance(order, int) and order != 0) or (
        isinstance(order, str) and sorted(order.lower()) != ['b', 'g', 'r']
    ):
        raise ValueError('order must be a permutation of rgb or integer zero')
    if set(inverted.lower()) - set('rgb'):
        raise ValueError('unknown inverted channels')


EffectValue = Annotated[
    ColorChase
    | ConfettiWithDecay
    | ExpandingRipples
    | FireFlies
    | LarsonScanner
    | LightningStorm
    | PacketTraffic
    | PixelPingPong
    | Pulse
    | Rain
    | Searchlights
    | Twinkle
    | Aurora
    | CandleBank
    | ColorFade
    | ExponentialFade
    | HalvesRainbow
    | Interference
    | LinearGradient
    | LinearRainbow
    | LogGradient
    | OceanCurrent
    | PaletteConveyor
    | Rainbow
    | Wave
    | Alternates
    | ColorFill
    | ColorPattern
    | ColorWipe
    | GreyCode
    | Hamiltonian
    | SaberBlade
    | CellularAutomaton
    | CollidingParticles
    | FireAndEmbers
    | PartyMode
    | RandomWalk
    | Randomize
    | ReactionDiffusionStrip
    | RainbowCycle
    | WhiteTwinkle,
    Field(discriminator='effect'),
]
