//! Portable effect processors and their modulation targets.
use crate::envelfo::Waveform;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::modulation::math::{add_partial, sum_partials};
use crate::modulation::{Parameter, Unit};
use crate::quantity;
use crate::samples::processing::ResonantFilter;
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::BTreeSet;

/// A checked declaration for the supported effect processor families.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "Definition", into = "Definition")]
pub struct Processor(Definition);

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TargetFacts {
    pub unit: Unit,
    pub default_value: f64,
    domain: Domain,
}

impl Processor {
    pub fn name(&self) -> &Identifier {
        match &self.0 {
            Definition::Gain { name, .. }
            | Definition::Multiply { name, .. }
            | Definition::FrequencyShifter { name, .. }
            | Definition::Filter { name, .. }
            | Definition::Gate { name, .. }
            | Definition::Expander { name, .. }
            | Definition::Compressor { name, .. }
            | Definition::Follower { name, .. }
            | Definition::Limiter { name, .. }
            | Definition::TransientShaper { name, .. }
            | Definition::DynamicEq { name, .. }
            | Definition::MultibandCompressor { name, .. }
            | Definition::Reverb { name, .. }
            | Definition::TapDelay { name, .. }
            | Definition::MatrixDelay { name, .. }
            | Definition::ResonantDelay { name, .. }
            | Definition::ModulatedDelay { name, .. } => name,
        }
    }

    pub fn resolve_target(&self, field: &str) -> Option<TargetFacts> {
        let (unit, default_value, domain) = match &self.0 {
            Definition::Gain { gain_db, .. } if field == "gain_db" => {
                (Unit::Db, *gain_db, Domain::Finite)
            }
            Definition::FrequencyShifter { shift_hz, .. } if field == "shift_hz" => {
                (Unit::HzOffset, *shift_hz, Domain::Closed(-2000.0, 2000.0))
            }
            Definition::Gain { mix, .. }
            | Definition::Multiply { mix, .. }
            | Definition::FrequencyShifter { mix, .. }
            | Definition::Filter { mix, .. }
            | Definition::Gate { mix, .. }
            | Definition::Expander { mix, .. }
            | Definition::Compressor { mix, .. }
            | Definition::Limiter { mix, .. }
            | Definition::TransientShaper { mix, .. }
            | Definition::DynamicEq { mix, .. }
            | Definition::Reverb { mix, .. }
            | Definition::TapDelay { mix, .. }
            | Definition::MatrixDelay { mix, .. }
            | Definition::ResonantDelay { mix, .. }
            | Definition::ModulatedDelay { mix, .. }
                if field == "mix" =>
            {
                (Unit::Ratio, *mix, Domain::Closed(0.0, 1.0))
            }
            Definition::Filter { filters, .. } => {
                let (name, field) = field.rsplit_once('-')?;
                let filter = filters.iter().find(|f| f.name().as_str() == name)?;
                match field {
                    "cutoff_hz" => (Unit::Hz, filter.cutoff_hz(), Domain::Positive),
                    "q" => (Unit::Ratio, filter.q(), Domain::Positive),
                    _ => return None,
                }
            }
            Definition::Gate { threshold_db, .. }
            | Definition::Expander { threshold_db, .. }
            | Definition::Compressor { threshold_db, .. }
            | Definition::DynamicEq { threshold_db, .. }
                if field == "threshold_db" =>
            {
                (Unit::Db, *threshold_db, Domain::Finite)
            }
            Definition::Gate { attack_seconds, .. }
            | Definition::Expander { attack_seconds, .. }
            | Definition::Compressor { attack_seconds, .. }
            | Definition::Follower { attack_seconds, .. }
            | Definition::DynamicEq { attack_seconds, .. }
                if field == "attack_seconds" =>
            {
                (Unit::Seconds, *attack_seconds, Domain::AtLeast(0.0))
            }
            Definition::Gate {
                release_seconds, ..
            }
            | Definition::Expander {
                release_seconds, ..
            }
            | Definition::Compressor {
                release_seconds, ..
            }
            | Definition::Follower {
                release_seconds, ..
            }
            | Definition::Limiter {
                release_seconds, ..
            }
            | Definition::DynamicEq {
                release_seconds, ..
            } if field == "release_seconds" => {
                (Unit::Seconds, *release_seconds, Domain::AtLeast(0.0))
            }
            Definition::Expander { ratio, .. }
            | Definition::Compressor { ratio, .. }
            | Definition::DynamicEq { ratio, .. }
                if field == "ratio" =>
            {
                (Unit::Ratio, *ratio, Domain::AtLeast(1.0))
            }
            Definition::Gate { hysteresis_db, .. } if field == "hysteresis_db" => {
                (Unit::Db, *hysteresis_db, Domain::AtLeast(0.0))
            }
            Definition::Gate { hold_seconds, .. } if field == "hold_seconds" => {
                (Unit::Seconds, *hold_seconds, Domain::AtLeast(0.0))
            }
            Definition::Compressor { knee_db, .. } | Definition::DynamicEq { knee_db, .. }
                if field == "knee_db" =>
            {
                (Unit::Db, *knee_db, Domain::AtLeast(0.0))
            }
            Definition::Compressor { makeup_db, .. } if field == "makeup_db" => {
                (Unit::Db, *makeup_db, Domain::Finite)
            }
            Definition::Limiter { ceiling_db, .. } if field == "ceiling_db" => {
                (Unit::Db, *ceiling_db, Domain::AtMost(0.0))
            }
            Definition::TransientShaper { attack_gain_db, .. } if field == "attack_gain_db" => {
                (Unit::Db, *attack_gain_db, Domain::Closed(-24.0, 24.0))
            }
            Definition::TransientShaper {
                sustain_gain_db, ..
            } if field == "sustain_gain_db" => {
                (Unit::Db, *sustain_gain_db, Domain::Closed(-24.0, 24.0))
            }
            Definition::DynamicEq { center_hz, .. } if field == "center_hz" => {
                (Unit::Hz, *center_hz, Domain::Positive)
            }
            Definition::DynamicEq { q, .. } if field == "q" => (Unit::Ratio, *q, Domain::Positive),
            Definition::DynamicEq { maximum_cut_db, .. } if field == "maximum_cut_db" => {
                (Unit::Db, *maximum_cut_db, Domain::AtLeast(0.0))
            }
            Definition::MultibandCompressor { low, mid, high, .. } => {
                let (band, control) = field.split_once('-')?;
                let band = match band {
                    "low" => low,
                    "mid" => mid,
                    "high" => high,
                    _ => return None,
                };
                band.target(control)?
            }
            Definition::Reverb {
                predelay_seconds,
                maximum_predelay_seconds,
                decay_seconds,
                damping_hz,
                ..
            } => match field {
                "predelay_seconds" => (
                    Unit::Seconds,
                    *predelay_seconds,
                    Domain::Closed(0.0, *maximum_predelay_seconds),
                ),
                "decay_seconds" => (Unit::Seconds, *decay_seconds, Domain::Positive),
                "damping_hz" => (Unit::Hz, *damping_hz, Domain::Positive),
                _ => return None,
            },
            Definition::TapDelay {
                delay_seconds,
                maximum_delay_seconds,
                feedback,
                damping_hz,
                ..
            }
            | Definition::MatrixDelay {
                delay_seconds,
                maximum_delay_seconds,
                feedback,
                damping_hz,
                ..
            } => match field {
                "delay_seconds" => (
                    Unit::Seconds,
                    *delay_seconds,
                    Domain::OpenClosed(0.0, *maximum_delay_seconds),
                ),
                "feedback" => (Unit::Ratio, *feedback, Domain::Feedback),
                "damping_hz" => (Unit::Hz, (*damping_hz)?, Domain::Positive),
                _ => return None,
            },
            Definition::ResonantDelay { decay_seconds, .. } if field == "decay_seconds" => {
                (Unit::Seconds, *decay_seconds, Domain::Positive)
            }
            Definition::ModulatedDelay {
                base_delay_seconds,
                depth_seconds,
                maximum_delay_seconds,
                rate_hz,
                feedback,
                ..
            } => match field {
                "base_delay_seconds" => (
                    Unit::Seconds,
                    *base_delay_seconds,
                    Domain::OpenClosed(*depth_seconds, maximum_delay_seconds - depth_seconds),
                ),
                "depth_seconds" => (
                    Unit::Seconds,
                    *depth_seconds,
                    Domain::DelayDepth {
                        base: *base_delay_seconds,
                        maximum: *maximum_delay_seconds,
                    },
                ),
                "rate_hz" => (Unit::Hz, *rate_hz, Domain::AtLeast(0.0)),
                "feedback" => (Unit::Ratio, *feedback, Domain::Feedback),
                _ => return None,
            },
            _ => return None,
        };
        Some(TargetFacts {
            unit,
            default_value,
            domain,
        })
    }

    pub fn validate_parameter(&self, parameter: &Parameter) -> Result<(), Error> {
        let target = parameter.target();
        let facts = (target.name() == self.name())
            .then(|| self.resolve_target(target.parameter().as_str()))
            .flatten()
            .ok_or_else(|| Error::Invalid("unknown effect modulation target".into()))?;
        if parameter.unit() != facts.unit || parameter.default_value() != facts.default_value {
            return Err(Error::Invalid(
                "effect parameter unit and default must match the processor".into(),
            ));
        }
        facts.domain.check(parameter.minimum())?;
        facts.domain.check(parameter.maximum())
    }

    /// Validate the targets owned by this processor and any coupled range limits.
    pub fn validate_parameters<'a>(
        &self,
        parameters: impl IntoIterator<Item = &'a Parameter>,
    ) -> Result<(), Error> {
        let mut base = None;
        let mut depth = None;
        for parameter in parameters {
            self.validate_parameter(parameter)?;
            match parameter.target().parameter().as_str() {
                "base_delay_seconds" => base = Some((parameter.minimum(), parameter.maximum())),
                "depth_seconds" => depth = Some(parameter.maximum()),
                _ => (),
            }
        }
        if let Definition::ModulatedDelay {
            base_delay_seconds,
            depth_seconds,
            maximum_delay_seconds,
            ..
        } = &self.0
        {
            let (minimum, maximum) = base.unwrap_or((*base_delay_seconds, *base_delay_seconds));
            let depth = depth.unwrap_or(*depth_seconds);
            if minimum <= depth || maximum + depth > *maximum_delay_seconds {
                return Err(Error::Invalid(
                    "modulation domains exceed the prepared delay span".into(),
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Domain {
    Finite,
    Positive,
    AtLeast(f64),
    AtMost(f64),
    Closed(f64, f64),
    OpenClosed(f64, f64),
    Feedback,
    DelayDepth { base: f64, maximum: f64 },
}

impl Domain {
    fn check(self, value: f64) -> Result<(), Error> {
        quantity::finite(value)?;
        let valid = match self {
            Self::Finite => true,
            Self::Positive => value > 0.0,
            Self::AtLeast(minimum) => value >= minimum,
            Self::AtMost(maximum) => value <= maximum,
            Self::Closed(minimum, maximum) => (minimum..=maximum).contains(&value),
            Self::OpenClosed(minimum, maximum) => minimum < value && value <= maximum,
            Self::Feedback => (0.0..1.0).contains(&value),
            Self::DelayDepth { base, maximum } => {
                (0.0..base).contains(&value) && base + value <= maximum
            }
        };
        if valid {
            Ok(())
        } else {
            Err(Error::Invalid(
                "effect parameter is outside its domain".into(),
            ))
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Definition {
    Gain {
        name: Identifier,
        #[serde(default, deserialize_with = "decibels")]
        gain_db: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Multiply {
        name: Identifier,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    FrequencyShifter {
        name: Identifier,
        #[serde(default, deserialize_with = "hertz")]
        shift_hz: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Filter {
        name: Identifier,
        filters: Vec<ResonantFilter>,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    Gate {
        name: Identifier,
        #[serde(default = "gate_threshold", deserialize_with = "decibels")]
        threshold_db: f64,
        #[serde(default = "six", deserialize_with = "decibels")]
        hysteresis_db: f64,
        #[serde(default = "short_time", deserialize_with = "seconds")]
        hold_seconds: f64,
        #[serde(default = "fast_attack", deserialize_with = "seconds")]
        attack_seconds: f64,
        #[serde(default = "short_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Expander {
        name: Identifier,
        #[serde(default = "gate_threshold", deserialize_with = "decibels")]
        threshold_db: f64,
        #[serde(default = "two")]
        ratio: f64,
        #[serde(default = "fast_attack", deserialize_with = "seconds")]
        attack_seconds: f64,
        #[serde(default = "short_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Compressor {
        name: Identifier,
        #[serde(default = "compressor_threshold", deserialize_with = "decibels")]
        threshold_db: f64,
        #[serde(default = "four")]
        ratio: f64,
        #[serde(default = "six", deserialize_with = "decibels")]
        knee_db: f64,
        #[serde(default = "short_time", deserialize_with = "seconds")]
        attack_seconds: f64,
        #[serde(default = "long_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default, deserialize_with = "decibels")]
        makeup_db: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    Follower {
        name: Identifier,
        #[serde(default = "short_time", deserialize_with = "seconds")]
        attack_seconds: f64,
        #[serde(default = "long_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    Limiter {
        name: Identifier,
        #[serde(default = "limiter_ceiling", deserialize_with = "decibels")]
        ceiling_db: f64,
        #[serde(default = "lookahead", deserialize_with = "seconds")]
        lookahead_seconds: f64,
        #[serde(default = "short_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    TransientShaper {
        name: Identifier,
        #[serde(default, deserialize_with = "decibels")]
        attack_gain_db: f64,
        #[serde(default, deserialize_with = "decibels")]
        sustain_gain_db: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
    },
    DynamicEq {
        name: Identifier,
        #[serde(default = "eq_center", deserialize_with = "hertz")]
        center_hz: f64,
        #[serde(default = "one")]
        q: f64,
        #[serde(default = "compressor_threshold", deserialize_with = "decibels")]
        threshold_db: f64,
        #[serde(default = "one")]
        ratio: f64,
        #[serde(default = "six", deserialize_with = "decibels")]
        knee_db: f64,
        #[serde(default = "short_time", deserialize_with = "seconds")]
        attack_seconds: f64,
        #[serde(default = "long_release", deserialize_with = "seconds")]
        release_seconds: f64,
        #[serde(default = "eq_cut", deserialize_with = "decibels")]
        maximum_cut_db: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    MultibandCompressor {
        name: Identifier,
        #[serde(default = "lower_crossover", deserialize_with = "hertz")]
        lower_crossover_hz: f64,
        #[serde(default = "upper_crossover", deserialize_with = "hertz")]
        upper_crossover_hz: f64,
        #[serde(default)]
        low: CompressorBand,
        #[serde(default)]
        mid: CompressorBand,
        #[serde(default)]
        high: CompressorBand,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    Reverb {
        name: Identifier,
        #[serde(default, deserialize_with = "seconds")]
        predelay_seconds: f64,
        #[serde(default = "reverb_predelay", deserialize_with = "seconds")]
        maximum_predelay_seconds: f64,
        #[serde(default = "two", deserialize_with = "seconds")]
        decay_seconds: f64,
        #[serde(default = "delay_damping", deserialize_with = "hertz")]
        damping_hz: f64,
        #[serde(default = "fade")]
        retime_fade_frames: i64,
        #[serde(default = "reverb_mix")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    TapDelay {
        name: Identifier,
        #[serde(deserialize_with = "seconds")]
        delay_seconds: f64,
        #[serde(deserialize_with = "seconds")]
        maximum_delay_seconds: f64,
        #[serde(default)]
        feedback: f64,
        #[serde(
            default,
            deserialize_with = "optional_hertz",
            skip_serializing_if = "Option::is_none"
        )]
        damping_hz: Option<f64>,
        #[serde(default = "fade")]
        retime_fade_frames: i64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    MatrixDelay {
        name: Identifier,
        #[serde(deserialize_with = "seconds")]
        delay_seconds: f64,
        #[serde(deserialize_with = "seconds")]
        maximum_delay_seconds: f64,
        #[serde(default)]
        feedback: f64,
        #[serde(
            default,
            deserialize_with = "optional_hertz",
            skip_serializing_if = "Option::is_none"
        )]
        damping_hz: Option<f64>,
        #[serde(default = "fade")]
        retime_fade_frames: i64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
        feedback_matrix: Vec<Vec<f64>>,
    },
    ResonantDelay {
        name: Identifier,
        #[serde(deserialize_with = "hertz")]
        frequency_hz: f64,
        #[serde(default = "delay_damping", deserialize_with = "hertz")]
        damping_hz: f64,
        #[serde(default = "one", deserialize_with = "seconds")]
        decay_seconds: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
    ModulatedDelay {
        name: Identifier,
        #[serde(deserialize_with = "seconds")]
        base_delay_seconds: f64,
        #[serde(default, deserialize_with = "seconds")]
        depth_seconds: f64,
        #[serde(deserialize_with = "seconds")]
        maximum_delay_seconds: f64,
        #[serde(deserialize_with = "hertz")]
        rate_hz: f64,
        #[serde(default)]
        waveform: Waveform,
        #[serde(default)]
        channel_phase_offsets: Vec<f64>,
        #[serde(default)]
        feedback: f64,
        #[serde(default = "one")]
        mix: f64,
        #[serde(default = "fade")]
        bypass_fade_frames: i64,
        #[serde(default = "threshold")]
        tail_threshold: f64,
        #[serde(default = "floor")]
        state_floor: f64,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CompressorBand {
    #[serde(default = "compressor_threshold", deserialize_with = "decibels")]
    threshold_db: f64,
    #[serde(default = "one")]
    ratio: f64,
    #[serde(default = "six", deserialize_with = "decibels")]
    knee_db: f64,
    #[serde(default = "short_time", deserialize_with = "seconds")]
    attack_seconds: f64,
    #[serde(default = "long_release", deserialize_with = "seconds")]
    release_seconds: f64,
    #[serde(default, deserialize_with = "decibels")]
    makeup_db: f64,
}

impl Default for CompressorBand {
    fn default() -> Self {
        Self {
            threshold_db: compressor_threshold(),
            ratio: one(),
            knee_db: six(),
            attack_seconds: short_time(),
            release_seconds: long_release(),
            makeup_db: 0.0,
        }
    }
}

impl CompressorBand {
    fn target(&self, field: &str) -> Option<(Unit, f64, Domain)> {
        Some(match field {
            "threshold_db" => (Unit::Db, self.threshold_db, Domain::Finite),
            "ratio" => (Unit::Ratio, self.ratio, Domain::AtLeast(1.0)),
            "knee_db" => (Unit::Db, self.knee_db, Domain::AtLeast(0.0)),
            "attack_seconds" => (Unit::Seconds, self.attack_seconds, Domain::AtLeast(0.0)),
            "release_seconds" => (Unit::Seconds, self.release_seconds, Domain::AtLeast(0.0)),
            "makeup_db" => (Unit::Db, self.makeup_db, Domain::Finite),
            _ => return None,
        })
    }
}

impl TryFrom<Definition> for Processor {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        let bypass = match &value {
            Definition::Gain {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Multiply {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::FrequencyShifter {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Filter {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Gate {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Expander {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Compressor {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Limiter {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::TransientShaper {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::DynamicEq {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::Reverb {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::TapDelay {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::MatrixDelay {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::ResonantDelay {
                mix,
                bypass_fade_frames,
                ..
            }
            | Definition::ModulatedDelay {
                mix,
                bypass_fade_frames,
                ..
            } => Some((*mix, *bypass_fade_frames)),
            Definition::Follower { .. } | Definition::MultibandCompressor { .. } => None,
        };
        if let Some((mix, frames)) = bypass {
            Domain::Closed(0.0, 1.0).check(mix)?;
            if frames < 1 {
                return Err(Error::Invalid(
                    "effect bypass fade requires positive frames".into(),
                ));
            }
        }
        if let Definition::MatrixDelay {
            feedback_matrix, ..
        } = &value
        {
            check_feedback_matrix(feedback_matrix)?;
        }
        let fields: &[&str] = match &value {
            Definition::Gain { .. } => &["gain_db"],
            Definition::FrequencyShifter { .. } => &["shift_hz"],
            Definition::Filter {
                filters,
                tail_threshold,
                state_floor,
                ..
            } => {
                check_tail(*tail_threshold, *state_floor)?;
                if filters.is_empty()
                    || filters
                        .iter()
                        .map(ResonantFilter::name)
                        .collect::<BTreeSet<_>>()
                        .len()
                        != filters.len()
                {
                    return Err(Error::Invalid(
                        "effect filter requires unique named stages".into(),
                    ));
                }
                &[]
            }
            Definition::Multiply { .. } => &[],
            Definition::Gate { .. } => &[
                "threshold_db",
                "hysteresis_db",
                "hold_seconds",
                "attack_seconds",
                "release_seconds",
            ],
            Definition::Expander { .. } => {
                &["threshold_db", "ratio", "attack_seconds", "release_seconds"]
            }
            Definition::Compressor { .. } => &[
                "threshold_db",
                "ratio",
                "knee_db",
                "attack_seconds",
                "release_seconds",
                "makeup_db",
            ],
            Definition::Follower {
                tail_threshold,
                state_floor,
                ..
            } => {
                check_tail(*tail_threshold, *state_floor)?;
                &["attack_seconds", "release_seconds"]
            }
            Definition::Limiter {
                lookahead_seconds, ..
            } => {
                Domain::Positive.check(*lookahead_seconds)?;
                &["ceiling_db", "release_seconds"]
            }
            Definition::TransientShaper { .. } => &["attack_gain_db", "sustain_gain_db"],
            Definition::DynamicEq {
                tail_threshold,
                state_floor,
                ..
            } => {
                check_tail(*tail_threshold, *state_floor)?;
                &[
                    "center_hz",
                    "q",
                    "threshold_db",
                    "ratio",
                    "knee_db",
                    "attack_seconds",
                    "release_seconds",
                    "maximum_cut_db",
                ]
            }
            Definition::MultibandCompressor {
                lower_crossover_hz,
                upper_crossover_hz,
                low,
                mid,
                high,
                tail_threshold,
                state_floor,
                ..
            } => {
                Domain::Positive.check(*lower_crossover_hz)?;
                Domain::Positive.check(*upper_crossover_hz)?;
                if lower_crossover_hz >= upper_crossover_hz {
                    return Err(Error::Invalid(
                        "multiband crossover frequencies must strictly increase".into(),
                    ));
                }
                check_tail(*tail_threshold, *state_floor)?;
                for band in [low, mid, high] {
                    for field in [
                        "threshold_db",
                        "ratio",
                        "knee_db",
                        "attack_seconds",
                        "release_seconds",
                        "makeup_db",
                    ] {
                        let (_, value, domain) =
                            band.target(field).expect("declared compressor field");
                        domain.check(value)?;
                    }
                }
                &[]
            }
            Definition::Reverb {
                retime_fade_frames,
                tail_threshold,
                state_floor,
                ..
            } => {
                check_retime(*retime_fade_frames)?;
                check_tail(*tail_threshold, *state_floor)?;
                &["predelay_seconds", "decay_seconds", "damping_hz"]
            }
            Definition::TapDelay {
                retime_fade_frames,
                damping_hz,
                tail_threshold,
                state_floor,
                ..
            }
            | Definition::MatrixDelay {
                retime_fade_frames,
                damping_hz,
                tail_threshold,
                state_floor,
                ..
            } => {
                check_retime(*retime_fade_frames)?;
                check_tail(*tail_threshold, *state_floor)?;
                if damping_hz.is_some() {
                    &["delay_seconds", "feedback", "damping_hz"]
                } else {
                    &["delay_seconds", "feedback"]
                }
            }
            Definition::ResonantDelay {
                frequency_hz,
                damping_hz,
                tail_threshold,
                state_floor,
                ..
            } => {
                Domain::Positive.check(*frequency_hz)?;
                Domain::Positive.check(*damping_hz)?;
                check_tail(*tail_threshold, *state_floor)?;
                &["decay_seconds"]
            }
            Definition::ModulatedDelay {
                base_delay_seconds,
                rate_hz,
                channel_phase_offsets,
                tail_threshold,
                state_floor,
                ..
            } => {
                Domain::Positive.check(*base_delay_seconds)?;
                Domain::Positive.check(*rate_hz)?;
                check_tail(*tail_threshold, *state_floor)?;
                for &phase in channel_phase_offsets {
                    Domain::Closed(0.0, 1.0).check(phase)?;
                }
                &["depth_seconds", "feedback"]
            }
        };
        let processor = Self(value);
        for field in fields {
            let facts = processor
                .resolve_target(field)
                .expect("declared processor field");
            facts.domain.check(facts.default_value)?;
        }
        Ok(processor)
    }
}

impl From<Processor> for Definition {
    fn from(value: Processor) -> Self {
        value.0
    }
}

fn decibels<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "db")
}
fn check_tail(threshold: f64, floor: f64) -> Result<(), Error> {
    Domain::Positive.check(threshold)?;
    Domain::Positive.check(floor)?;
    if floor >= threshold {
        return Err(Error::Invalid(
            "effect state_floor must be below tail_threshold".into(),
        ));
    }
    Ok(())
}
fn check_retime(frames: i64) -> Result<(), Error> {
    if frames < 1 {
        return Err(Error::Invalid(
            "effect retime fade requires positive frames".into(),
        ));
    }
    Ok(())
}
fn check_feedback_matrix(rows: &[Vec<f64>]) -> Result<(), Error> {
    if rows.is_empty() || rows.iter().any(|row| row.len() != rows.len()) {
        return Err(Error::Invalid(
            "delay feedback matrix must be nonempty and square".into(),
        ));
    }
    let mut partials = vec![0.0; rows.len()];
    for row in rows {
        let mut count = 0;
        for value in row {
            Domain::Closed(-1.0, 1.0).check(*value)?;
            add_partial(&mut partials, &mut count, value.abs())
                .map_err(|error| Error::Invalid(error.to_string()))?;
        }
        let sum =
            sum_partials(&partials[..count]).map_err(|error| Error::Invalid(error.to_string()))?;
        if sum > 1.0 {
            return Err(Error::Invalid(
                "delay feedback matrix absolute row sums exceed one".into(),
            ));
        }
    }
    Ok(())
}
fn hertz<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "hz")
}
fn optional_hertz<'de, D: Deserializer<'de>>(d: D) -> Result<Option<f64>, D::Error> {
    #[derive(Deserialize)]
    struct Hertz(#[serde(deserialize_with = "hertz")] f64);
    Option::<Hertz>::deserialize(d).map(|value| value.map(|hertz| hertz.0))
}
fn seconds<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    quantity::deserialize_scalar(d, "seconds")
}
fn one() -> f64 {
    1.0
}
fn fade() -> i64 {
    64
}
fn threshold() -> f64 {
    1e-12
}
fn floor() -> f64 {
    1e-30
}
fn gate_threshold() -> f64 {
    -40.0
}
fn compressor_threshold() -> f64 {
    -18.0
}
fn limiter_ceiling() -> f64 {
    -1.0
}
fn two() -> f64 {
    2.0
}
fn four() -> f64 {
    4.0
}
fn six() -> f64 {
    6.0
}
fn fast_attack() -> f64 {
    0.001
}
fn lookahead() -> f64 {
    0.005
}
fn short_time() -> f64 {
    0.01
}
fn short_release() -> f64 {
    0.05
}
fn long_release() -> f64 {
    0.1
}
fn eq_center() -> f64 {
    1000.0
}
fn eq_cut() -> f64 {
    12.0
}
fn lower_crossover() -> f64 {
    200.0
}
fn upper_crossover() -> f64 {
    4000.0
}
fn reverb_predelay() -> f64 {
    0.25
}
fn reverb_mix() -> f64 {
    0.25
}
fn delay_damping() -> f64 {
    6000.0
}
