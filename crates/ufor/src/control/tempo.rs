//! Exact host transport positions and running musical time.

use crate::{envelfo::PreparationLimits, error::Error, number::Rational, quantity};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TempoMap {
    points: Vec<TempoPoint>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TempoPoint {
    #[serde(serialize_with = "write_ratio", deserialize_with = "seconds")]
    at_seconds: Rational,
    #[serde(serialize_with = "write_ratio", deserialize_with = "beats")]
    beat: Rational,
    #[serde(serialize_with = "write_ratio", deserialize_with = "bpm")]
    bpm: Rational,
    #[serde(default = "running")]
    running: bool,
}

/// One prepared generator-clock point in exact frame and beat units.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BeatClockPoint {
    pub frame: Rational,
    pub elapsed_beat: Rational,
    pub transport_beat: Rational,
    pub beats_per_frame: Rational,
}

impl TempoMap {
    pub fn decode(value: Value, limits: PreparationLimits) -> Result<Self, Error> {
        let definition: Definition =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        let points = definition.points;
        limits.check_records(points.len())?;
        if points
            .first()
            .is_none_or(|point| point.at_seconds != 0.into())
            || points
                .windows(2)
                .any(|pair| pair[0].at_seconds >= pair[1].at_seconds)
        {
            return Err(invalid(
                "tempo points must start at zero and increase in time",
            ));
        }
        if points.iter().any(|point| point.bpm <= 0.into()) {
            return Err(invalid("tempo must be positive"));
        }
        Ok(Self { points })
    }

    pub fn beat_at(&self, seconds: Rational) -> Result<Rational, Error> {
        let index = self.index_at(seconds)?;
        self.points[index].beat_at(seconds)
    }

    /// Integrate running beats across the interval, ignoring transport seeks.
    pub fn elapsed_beats(&self, start: Rational, end: Rational) -> Result<Rational, Error> {
        if end < start || start < 0.into() {
            return Err(invalid("clock interval must be ordered and nonnegative"));
        }
        let mut elapsed = Rational::from(0);
        for (index, point) in self.points.iter().enumerate().skip(self.index_at(start)?) {
            let left = start.max(point.at_seconds);
            let right = self
                .points
                .get(index + 1)
                .map_or(end, |p| end.min(p.at_seconds));
            if point.running && right > left {
                elapsed = elapsed.checked_add(point.elapsed(right.checked_sub(left)?)?)?;
            }
            if right == end {
                break;
            }
        }
        Ok(elapsed)
    }

    pub fn time_for_elapsed_beat(&self, beat: Rational) -> Result<Option<Rational>, Error> {
        if beat < 0.into() {
            return Err(invalid("elapsed beat must be nonnegative"));
        }
        let mut elapsed = Rational::from(0);
        for (index, point) in self.points.iter().enumerate() {
            if beat == elapsed {
                return Ok(Some(point.at_seconds));
            }
            if !point.running {
                continue;
            }
            let offset = point.duration(beat.checked_sub(elapsed)?)?;
            let Some(next) = self.points.get(index + 1) else {
                return Ok(Some(point.at_seconds.checked_add(offset)?));
            };
            let span = next.at_seconds.checked_sub(point.at_seconds)?;
            if offset <= span {
                return Ok(Some(point.at_seconds.checked_add(offset)?));
            }
            elapsed = elapsed.checked_add(point.elapsed(span)?)?;
        }
        Ok(None)
    }

    pub fn quantized_beat(&self, seconds: Rational, division: Rational) -> Result<Rational, Error> {
        if division <= 0.into() {
            return Err(invalid("beat division must be positive"));
        }
        let steps = self.beat_at(seconds)?.checked_div(division)?.ceil();
        division.checked_mul(steps.into())
    }

    /// Resolve a pending transport beat, or return a seek error at a discontinuity.
    pub fn time_for_beat(
        &self,
        beat: Rational,
        after: Rational,
    ) -> Result<Option<Rational>, Error> {
        for (index, point) in self.points.iter().enumerate().skip(self.index_at(after)?) {
            let start = after.max(point.at_seconds);
            if beat < point.beat_at(start)? {
                return Err(invalid("pending beat precedes the clock position"));
            }
            let reached = if point.running {
                Some(
                    point
                        .at_seconds
                        .checked_add(point.duration(beat.checked_sub(point.beat)?)?)?,
                )
            } else {
                None
            };
            let next = self.points.get(index + 1);
            if let Some(time) =
                reached.filter(|&time| time >= start && next.is_none_or(|p| time < p.at_seconds))
            {
                return Ok(Some(time));
            }
            let Some(next) = next else {
                return Ok(None);
            };
            if next.beat != point.beat_at(next.at_seconds)? {
                return Err(Error::TransportSeek);
            }
            if reached == Some(next.at_seconds) {
                return Ok(reached);
            }
        }
        Ok(None)
    }

    /// Prepare callback clock points without counting transport discontinuities as elapsed beats.
    pub fn frame_points(&self, sample_rate: i64) -> Result<Vec<BeatClockPoint>, Error> {
        if sample_rate <= 0 {
            return Err(invalid("sample rate must be positive"));
        }
        let mut elapsed_beat = Rational::from(0);
        let mut result = Vec::with_capacity(self.points.len());
        for (index, point) in self.points.iter().enumerate() {
            result.push(BeatClockPoint {
                frame: point.at_seconds.checked_mul(sample_rate.into())?,
                elapsed_beat,
                transport_beat: point.beat,
                beats_per_frame: if point.running {
                    point
                        .bpm
                        .checked_div(60.into())?
                        .checked_div(sample_rate.into())?
                } else {
                    0.into()
                },
            });
            if let Some(next) = self.points.get(index + 1).filter(|_| point.running) {
                elapsed_beat = elapsed_beat
                    .checked_add(point.elapsed(next.at_seconds.checked_sub(point.at_seconds)?)?)?;
            }
        }
        Ok(result)
    }

    fn index_at(&self, seconds: Rational) -> Result<usize, Error> {
        if seconds < 0.into() {
            return Err(invalid("clock time must be nonnegative"));
        }
        Ok(self
            .points
            .partition_point(|point| point.at_seconds <= seconds)
            - 1)
    }
}

impl TempoPoint {
    fn elapsed(self, seconds: Rational) -> Result<Rational, Error> {
        if self.running {
            seconds.checked_mul(self.bpm)?.checked_div(60.into())
        } else {
            Ok(0.into())
        }
    }

    fn beat_at(self, seconds: Rational) -> Result<Rational, Error> {
        if self.running {
            self.beat
                .checked_add(self.elapsed(seconds.checked_sub(self.at_seconds)?)?)
        } else {
            Ok(self.beat)
        }
    }

    fn duration(self, beats: Rational) -> Result<Rational, Error> {
        beats.checked_mul(60.into())?.checked_div(self.bpm)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    points: Vec<TempoPoint>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Ratio {
    Integer(i64),
    Text(String),
}

fn seconds<'de, D: Deserializer<'de>>(d: D) -> Result<Rational, D::Error> {
    read_ratio(d, "seconds")
}

fn beats<'de, D: Deserializer<'de>>(d: D) -> Result<Rational, D::Error> {
    read_ratio(d, "beats")
}

fn bpm<'de, D: Deserializer<'de>>(d: D) -> Result<Rational, D::Error> {
    read_ratio(d, "bpm")
}

fn read_ratio<'de, D: Deserializer<'de>>(d: D, unit: &str) -> Result<Rational, D::Error> {
    match Ratio::deserialize(d)? {
        Ratio::Integer(value) => Ok(value.into()),
        Ratio::Text(text) => {
            let text = text.trim();
            let (text, unit) = if unit == "bpm" {
                (
                    text.strip_suffix("beats_per_minute")
                        .or_else(|| text.strip_suffix("bpm"))
                        .unwrap_or(text)
                        .trim_end(),
                    "ratio",
                )
            } else {
                (text, unit)
            };
            quantity::exact(text, unit).map_err(serde::de::Error::custom)
        }
    }
}

fn write_ratio<S: Serializer>(value: &Rational, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.collect_str(value)
}

fn running() -> bool {
    true
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
