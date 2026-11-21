//! Quantized command coordinates on an exact host tempo map.

use super::tempo::TempoMap;
use crate::{error::Error, number::Rational};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug)]
pub struct EventCoordinate {
    pub tick: i64,
    pub ordinal: u64,
    pub quantize_beats: Option<Rational>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ScheduledEvent {
    pub index: usize,
    pub tick: i64,
    pub ordinal: u64,
}

/// Schedule commands against all occupied coordinates, including ordinary events.
///
/// The returned indices address the input order. Pending commands cancelled by a
/// seek or never reached on a stopped clock are omitted.
pub fn schedule_commands(
    tempo_map: &TempoMap,
    sample_rate: i64,
    events: &[EventCoordinate],
) -> Result<Vec<ScheduledEvent>, Error> {
    if sample_rate <= 0 {
        return Err(Error::Invalid("sample rate must be positive".into()));
    }
    let mut ordered: Vec<_> = events.iter().enumerate().collect();
    ordered.sort_unstable_by_key(|(_, event)| (event.tick, event.ordinal));
    if ordered
        .windows(2)
        .any(|pair| (pair[0].1.tick, pair[0].1.ordinal) == (pair[1].1.tick, pair[1].1.ordinal))
    {
        return Err(Error::Invalid("duplicate event coordinate".into()));
    }
    // The highest authored ordinal is last in each tick of the sorted input.
    let mut occupied = BTreeMap::new();
    for (_, event) in &ordered {
        occupied.insert(event.tick, event.ordinal);
    }
    let mut scheduled = Vec::with_capacity(events.len());
    for (index, event) in ordered {
        let tick = if let Some(division) = event.quantize_beats {
            let at = Rational::new(event.tick, sample_rate)?;
            let target = tempo_map.quantized_beat(at, division)?;
            match tempo_map.time_for_beat(target, at) {
                Ok(Some(time)) => time.checked_mul(sample_rate.into())?.ceil(),
                Ok(None) | Err(Error::TransportSeek) => continue,
                Err(error) => return Err(error),
            }
        } else {
            event.tick
        };
        let ordinal = if tick == event.tick {
            event.ordinal
        } else if let Some(last) = occupied.get_mut(&tick) {
            *last = last.checked_add(1).ok_or(Error::ArithmeticRange)?;
            *last
        } else {
            occupied.insert(tick, 0);
            0
        };
        scheduled.push(ScheduledEvent {
            index,
            tick,
            ordinal,
        });
    }
    scheduled.sort_unstable_by_key(|event| (event.tick, event.ordinal));
    Ok(scheduled)
}
