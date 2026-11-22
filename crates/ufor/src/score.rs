//! The implemented score kinds, sharing the existing version 4 envelope.
use crate::automation::AutomationScore;
use crate::envelfo::{self, EnvelfoScore, PreparationLimits};
use crate::musical::{OscillatorScore, ScaleScore, TuningScore};
use crate::sequence::SequenceScore;
use serde::{Deserialize, Deserializer, Serialize, Serializer};

#[derive(Clone, Debug, PartialEq)]
pub enum Score {
    Tuning(TuningScore),
    Scale(ScaleScore),
    Oscillator(OscillatorScore),
    Envelfo(EnvelfoScore),
    Sequence(SequenceScore),
    Automation(AutomationScore),
}
impl Score {
    pub fn name(&self) -> &str {
        match self {
            Self::Tuning(v) => v.name(),
            Self::Scale(v) => v.name(),
            Self::Oscillator(v) => v.name(),
            Self::Envelfo(v) => v.name(),
            Self::Sequence(v) => v.name(),
            Self::Automation(v) => v.name(),
        }
    }
    pub fn title(&self) -> &str {
        match self {
            Self::Tuning(v) => v.title(),
            Self::Scale(v) => v.title(),
            Self::Oscillator(v) => v.title(),
            Self::Envelfo(v) => v.title(),
            Self::Sequence(v) => v.title(),
            Self::Automation(v) => v.title(),
        }
    }
    pub fn tags(&self) -> &[String] {
        match self {
            Self::Tuning(v) => v.tags(),
            Self::Scale(v) => v.tags(),
            Self::Oscillator(v) => v.tags(),
            Self::Envelfo(v) => v.tags(),
            Self::Sequence(v) => v.tags(),
            Self::Automation(v) => v.tags(),
        }
    }
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        d: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        match ScoreDefinition::deserialize(d)? {
            ScoreDefinition::Tuning(v) => Ok(Self::Tuning(v)),
            ScoreDefinition::Scale(v) => Ok(Self::Scale(v)),
            ScoreDefinition::Oscillator(v) => Ok(Self::Oscillator(v)),
            ScoreDefinition::Envelfo(v) => v
                .prepare(limits)
                .map(Self::Envelfo)
                .map_err(serde::de::Error::custom),
            ScoreDefinition::Sequence(v) => {
                v.check_records(limits).map_err(serde::de::Error::custom)?;
                Ok(Self::Sequence(v))
            }
            ScoreDefinition::Automation(v) => {
                // Count the score, timebase and control output with the body.
                v.body()
                    .check_records(limits, 3)
                    .map_err(serde::de::Error::custom)?;
                Ok(Self::Automation(v))
            }
        }
    }
}
impl<'de> Deserialize<'de> for Score {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        Self::decode(d, PreparationLimits::default())
    }
}
impl Serialize for Score {
    fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::Tuning(v) => v.serialize(s),
            Self::Scale(v) => v.serialize(s),
            Self::Oscillator(v) => v.serialize(s),
            Self::Envelfo(v) => v.serialize(s),
            Self::Sequence(v) => v.serialize(s),
            Self::Automation(v) => v.serialize(s),
        }
    }
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ScoreDefinition {
    Tuning(TuningScore),
    Scale(ScaleScore),
    Oscillator(OscillatorScore),
    Envelfo(envelfo::wire::ScoreWire),
    Sequence(SequenceScore),
    Automation(AutomationScore),
}
