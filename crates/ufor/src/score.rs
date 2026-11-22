//! The implemented score kinds, sharing the existing version 4 envelope.
use crate::envelfo::{self, EnvelfoScore, PreparationLimits};
use crate::musical::TuningScore;
use crate::sequence::SequenceScore;
use serde::{Deserialize, Deserializer, Serialize, Serializer};

#[derive(Clone, Debug, PartialEq)]
pub enum Score {
    Tuning(TuningScore),
    Envelfo(EnvelfoScore),
    Sequence(SequenceScore),
}
impl Score {
    pub fn name(&self) -> &str {
        match self {
            Self::Tuning(v) => v.name(),
            Self::Envelfo(v) => v.name(),
            Self::Sequence(v) => v.name(),
        }
    }
    pub fn title(&self) -> &str {
        match self {
            Self::Tuning(v) => v.title(),
            Self::Envelfo(v) => v.title(),
            Self::Sequence(v) => v.title(),
        }
    }
    pub fn tags(&self) -> &[String] {
        match self {
            Self::Tuning(v) => v.tags(),
            Self::Envelfo(v) => v.tags(),
            Self::Sequence(v) => v.tags(),
        }
    }
    pub(crate) fn decode<'de, D: Deserializer<'de>>(
        d: D,
        limits: PreparationLimits,
    ) -> Result<Self, D::Error> {
        match ScoreDefinition::deserialize(d)? {
            ScoreDefinition::Tuning(v) => Ok(Self::Tuning(v)),
            ScoreDefinition::Envelfo(v) => v
                .prepare(limits)
                .map(Self::Envelfo)
                .map_err(serde::de::Error::custom),
            ScoreDefinition::Sequence(v) => {
                v.check_records(limits).map_err(serde::de::Error::custom)?;
                Ok(Self::Sequence(v))
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
            Self::Envelfo(v) => v.serialize(s),
            Self::Sequence(v) => v.serialize(s),
        }
    }
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum ScoreDefinition {
    Tuning(TuningScore),
    Envelfo(envelfo::wire::ScoreWire),
    Sequence(SequenceScore),
}
