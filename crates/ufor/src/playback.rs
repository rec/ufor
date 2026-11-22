//! Pure seeking and replay plans over stored event sequences.

use crate::error::Error;
use crate::events::{
    Action, ControlScope, PerformanceEvent, PerformancePayload, StoredEvent, StoredPayload,
};
use crate::identifier::Identifier;
use crate::sequence::EventSequence;
use crate::time::TickRange;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::num::NonZeroU64;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SequenceSelection {
    pub name: Identifier,
    pub interval: TickRange,
    #[serde(default)]
    pub start: i64,
    #[serde(default = "one")]
    pub repetitions: NonZeroU64,
    #[serde(default)]
    pub active_notes: ActiveNotes,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActiveNotes {
    #[default]
    RetriggerActive,
    OmitActive,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SequenceState {
    pub triggers: Vec<PerformanceEvent>,
    pub controls: Vec<PerformanceEvent>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct PlaybackIteration {
    pub name: Identifier,
    pub iteration: u64,
    pub timebase: Identifier,
    pub start: i64,
    pub end: i64,
    pub controls: Vec<PerformanceEvent>,
    pub events: Vec<PerformanceEvent>,
    pub captured: Vec<StoredEvent>,
    pub cleanup: Vec<PerformanceEvent>,
}

/// Reconstruct semantic state strictly before the selected tick.
pub fn state_at(sequence: &EventSequence, tick: i64) -> Result<SequenceState, Error> {
    if !(sequence.start()..=sequence.end()).contains(&tick) {
        return Err(invalid("seek tick must be within the sequence extent"));
    }
    let before = sequence.events().partition_point(|event| event.tick < tick);
    let mut ledger = Ledger::default();
    ledger.observe(sequence.events(), 0, before)?;
    Ok(ledger.snapshot())
}

/// Validate the selection and ownership, then prepare a lazy loop iterator.
pub fn plan_playback<'a>(
    sequence: &'a EventSequence,
    selection: SequenceSelection,
) -> Result<PlaybackPlan<'a>, Error> {
    let left = selection.interval.start();
    let right = selection.interval.end();
    if left < sequence.start() || right > sequence.end() {
        return Err(invalid("selection must lie within the sequence extent"));
    }
    let duration = i128::from(right) - i128::from(left);
    let destination_span = (i128::from(i64::MAX) - i128::from(selection.start)) as u128;
    if duration as u128 * u128::from(selection.repetitions.get()) > destination_span {
        return Err(Error::ArithmeticRange);
    }
    let events = sequence.events();
    let first = events.partition_point(|event| event.tick < left);
    let end = events.partition_point(|event| event.tick < right);
    let mut ledger = Ledger::default();
    ledger.observe(events, 0, first)?;
    let initial = ledger.snapshot();
    ledger.observe(events, first, end)?;
    Ok(PlaybackPlan {
        next_start: selection.start,
        selection,
        duration,
        next_iteration: 0,
        timebase: sequence.timebase(),
        initial,
        selected: &events[first..end],
    })
}

pub struct PlaybackPlan<'a> {
    selection: SequenceSelection,
    duration: i128,
    next_start: i64,
    next_iteration: u64,
    timebase: &'a Identifier,
    initial: SequenceState,
    selected: &'a [StoredEvent],
}

impl Iterator for PlaybackPlan<'_> {
    type Item = Result<PlaybackIteration, Error>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next_iteration == self.selection.repetitions.get() {
            return None;
        }
        let start = self.next_start;
        // The entire destination extent was checked when the plan was built.
        let end = (i128::from(start) + self.duration) as i64;
        let iteration = self.next_iteration;
        let result = self.iteration(iteration, start, end);
        self.next_start = end;
        self.next_iteration = if result.is_ok() {
            iteration + 1
        } else {
            self.selection.repetitions.get()
        };
        Some(result)
    }
}

impl std::iter::FusedIterator for PlaybackPlan<'_> {}

impl PlaybackPlan<'_> {
    fn iteration(&self, iteration: u64, start: i64, end: i64) -> Result<PlaybackIteration, Error> {
        let name = self.selection.name.as_str();
        let prefix = format!("clip-{}-{name}-{iteration}-", name.chars().count());
        let mut active = BTreeMap::new();
        let mut events = Vec::new();
        let mut captured = Vec::new();
        let controls = self
            .initial
            .controls
            .iter()
            .enumerate()
            .filter(|(_, event)| !is_trigger_control(event.payload.action()))
            .map(|(index, event)| PerformanceEvent {
                tick: start,
                ordinal: index as u64,
                payload: event.payload.clone(),
            })
            .collect();

        if self.selection.active_notes == ActiveNotes::RetriggerActive {
            for event in &self.initial.triggers {
                let action = event.payload.action();
                if let Action::Trigger {
                    part, trigger_id, ..
                } = action
                {
                    active.insert((part, trigger_id), events.len());
                    append(&mut events, action, start, &prefix)?;
                }
            }
            for event in &self.initial.controls {
                let action = event.payload.action();
                if is_trigger_control(action) {
                    append(&mut events, action, start, &prefix)?;
                }
            }
        }

        for event in self.selected {
            let tick = (i128::from(start) + i128::from(event.tick)
                - i128::from(self.selection.interval.start())) as i64;
            if let StoredPayload::Performance(payload) = &event.payload {
                let action = payload.action();
                match action {
                    Action::Trigger {
                        part, trigger_id, ..
                    } => {
                        active.insert((part, trigger_id), events.len());
                    }
                    Action::Release { part, trigger_id } => {
                        if active.remove(&(part, trigger_id)).is_none() {
                            continue;
                        }
                    }
                    Action::ControlChange {
                        part, trigger_id, ..
                    } => {
                        if let (Some(part), Some(id)) = (part, trigger_id) {
                            if !active.contains_key(&(part, id)) {
                                continue;
                            }
                        }
                    }
                    _ => {
                        captured.push(StoredEvent {
                            tick,
                            ..event.clone()
                        });
                        continue;
                    }
                }
                append(&mut events, action, tick, &prefix)?;
            } else {
                captured.push(StoredEvent {
                    tick,
                    ..event.clone()
                });
            }
        }

        let mut remaining: Vec<_> = active.into_iter().collect();
        remaining.sort_unstable_by_key(|(_, index)| *index);
        let cleanup = remaining
            .into_iter()
            .enumerate()
            .map(|(index, ((part, id), _))| {
                Ok(PerformanceEvent {
                    tick: end,
                    ordinal: (events.len() + index) as u64,
                    payload: Action::Release {
                        part: part.clone(),
                        trigger_id: scoped(&prefix, id)?,
                    }
                    .try_into()?,
                })
            })
            .collect::<Result<Vec<_>, Error>>()?;

        Ok(PlaybackIteration {
            name: self.selection.name.clone(),
            iteration,
            timebase: self.timebase.clone(),
            start,
            end,
            controls,
            events,
            captured,
            cleanup,
        })
    }
}

type Note<'a> = (&'a Identifier, &'a Identifier);
type Control<'a> = (Option<&'a Identifier>, &'a Identifier);

#[derive(Clone, Copy)]
struct OrderedEvent<'a> {
    index: usize,
    tick: i64,
    ordinal: u64,
    payload: &'a PerformancePayload,
}

struct HeldNote<'a> {
    onset: OrderedEvent<'a>,
    controls: BTreeMap<&'a Identifier, OrderedEvent<'a>>,
}

#[derive(Default)]
struct Ledger<'a> {
    held: BTreeMap<Note<'a>, HeldNote<'a>>,
    controls: BTreeMap<Control<'a>, OrderedEvent<'a>>,
}

impl<'a> Ledger<'a> {
    fn observe(
        &mut self,
        events: &'a [StoredEvent],
        first: usize,
        end: usize,
    ) -> Result<(), Error> {
        for (index, event) in (first..end).zip(&events[first..end]) {
            let StoredPayload::Performance(payload) = &event.payload else {
                continue;
            };
            let mut observed = OrderedEvent {
                index,
                tick: event.tick,
                ordinal: event.ordinal,
                payload,
            };
            match payload.action() {
                Action::Trigger {
                    part, trigger_id, ..
                } => {
                    let entry = self.held.entry((part, trigger_id));
                    if let std::collections::btree_map::Entry::Vacant(entry) = entry {
                        entry.insert(HeldNote {
                            onset: observed,
                            controls: BTreeMap::new(),
                        });
                    } else {
                        return Err(invalid("trigger ID is already active in this part"));
                    }
                }
                Action::Release { part, trigger_id } => {
                    if self.held.remove(&(part, trigger_id)).is_none() {
                        return Err(invalid("release has no active trigger"));
                    }
                }
                Action::ControlChange {
                    control,
                    part,
                    trigger_id,
                    ..
                } => {
                    let current = if let (Some(part), Some(id)) = (part, trigger_id) {
                        self.held
                            .get_mut(&(part, id))
                            .ok_or_else(|| invalid("control change has no active trigger"))?
                            .controls
                            .entry(control)
                            .or_insert(observed)
                    } else {
                        self.controls
                            .entry((part.as_ref(), control))
                            .or_insert(observed)
                    };
                    observed.index = current.index;
                    *current = observed;
                }
                _ => {}
            }
        }
        Ok(())
    }

    fn snapshot(&self) -> SequenceState {
        let triggers = self.held.values().map(|note| note.onset).collect();
        let controls = self
            .controls
            .values()
            .copied()
            .chain(
                self.held
                    .values()
                    .flat_map(|note| note.controls.values().copied()),
            )
            .collect();
        SequenceState {
            triggers: ordered(triggers),
            controls: ordered(controls),
        }
    }
}

fn ordered(mut events: Vec<OrderedEvent<'_>>) -> Vec<PerformanceEvent> {
    events.sort_unstable_by_key(|event| event.index);
    events
        .into_iter()
        .map(|event| PerformanceEvent {
            tick: event.tick,
            ordinal: event.ordinal,
            payload: event.payload.clone(),
        })
        .collect()
}

fn append(
    events: &mut Vec<PerformanceEvent>,
    action: &Action,
    tick: i64,
    prefix: &str,
) -> Result<(), Error> {
    let mut action = action.clone();
    match &mut action {
        Action::Trigger { trigger_id, .. }
        | Action::Release { trigger_id, .. }
        | Action::ControlChange {
            trigger_id: Some(trigger_id),
            ..
        } => {
            *trigger_id = scoped(prefix, trigger_id)?;
        }
        _ => {}
    }
    events.push(PerformanceEvent {
        tick,
        ordinal: events.len() as u64,
        payload: action.try_into()?,
    });
    Ok(())
}

fn is_trigger_control(action: &Action) -> bool {
    matches!(
        action,
        Action::ControlChange {
            scope: ControlScope::Trigger,
            ..
        }
    )
}

fn scoped(prefix: &str, id: &Identifier) -> Result<Identifier, Error> {
    Identifier::new(format!("{prefix}{}", id.as_str()))
}

fn one() -> NonZeroU64 {
    NonZeroU64::MIN
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}
