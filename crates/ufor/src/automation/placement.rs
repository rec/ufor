//! Place a resolved control output on an arrangement clock.

use super::{AutomationScore, Quantity};
use crate::control::Scope;
use crate::error::Error;
use crate::identifier::Identifier;
use crate::time::{Rate, TickRange, Timebase, convert_exact_distance};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OutputSelection {
    pub part: Identifier,
    pub output: Identifier,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Definition")]
pub struct ControlClip {
    name: Identifier,
    source: OutputSelection,
    source_start: i64,
    source_end: i64,
    timeline_start: i64,
}

impl ControlClip {
    pub fn new(
        name: Identifier,
        source: OutputSelection,
        source_interval: TickRange,
        timeline_start: i64,
    ) -> Result<Self, Error> {
        if timeline_start < 0 {
            return Err(Error::Invalid(
                "control clip timeline start must be nonnegative".into(),
            ));
        }
        Ok(Self {
            name,
            source,
            source_start: source_interval.start(),
            source_end: source_interval.end(),
            timeline_start,
        })
    }

    pub fn name(&self) -> &Identifier {
        &self.name
    }

    pub fn source(&self) -> &OutputSelection {
        &self.source
    }

    /// The caller resolves the selected part and supplies its score.
    pub fn prepare(
        &self,
        score: &AutomationScore,
        timeline: &Timebase,
    ) -> Result<Placement, Error> {
        if self.source.output != score.output().name {
            return Err(Error::Invalid(
                "control clip selects an unknown output".into(),
            ));
        }
        if score.body().scope() != Scope::Part || score.body().quantity() == Quantity::Gate {
            return Err(Error::Invalid(
                "control clips require part-scoped numeric automation".into(),
            ));
        }
        let source_rate = score.timebase().rate();
        let timeline_rate = timeline.rate();
        let duration = convert_exact_distance(
            self.source_end.abs_diff(self.source_start),
            source_rate,
            timeline_rate,
        )?;
        let timeline_end = i64::try_from(i128::from(self.timeline_start) + i128::from(duration))
            .map_err(|_| Error::ArithmeticRange)?;
        Ok(Placement {
            source_rate,
            timeline_rate,
            source_start: self.source_start,
            timeline: TickRange::new(self.timeline_start, timeline_end)?,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Placement {
    source_rate: Rate,
    timeline_rate: Rate,
    source_start: i64,
    timeline: TickRange,
}

impl Placement {
    pub fn timeline(&self) -> TickRange {
        self.timeline
    }

    /// Request from the clip's source start through the overlap's exact end.
    /// This includes the history needed to reconstruct the value at render start.
    pub fn source_request(&self, window: TickRange) -> Result<Option<TickRange>, Error> {
        let end = window.end().min(self.timeline.end());
        if window.start().max(self.timeline.start()) >= end {
            return Ok(None);
        }
        let elapsed = convert_exact_distance(
            end.abs_diff(self.timeline.start()),
            self.timeline_rate,
            self.source_rate,
        )?;
        let source_end = i64::try_from(i128::from(self.source_start) + i128::from(elapsed))
            .map_err(|_| Error::ArithmeticRange)?;
        Ok(Some(TickRange::new(self.source_start, source_end)?))
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    name: Identifier,
    source: OutputSelection,
    source_start: i64,
    source_end: i64,
    timeline_start: i64,
}

impl TryFrom<Definition> for ControlClip {
    type Error = Error;

    fn try_from(value: Definition) -> Result<Self, Error> {
        Self::new(
            value.name,
            value.source,
            TickRange::new(value.source_start, value.source_end)?,
            value.timeline_start,
        )
    }
}
