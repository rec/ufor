//! Deterministic sampler take selection and partition advancement.

use super::eligibility::Trigger;
use super::random::{hash_field, uniform_integer};
use crate::envelfo::PreparationLimits;
use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::num::NonZeroU64;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    Cycle,
    Random,
    Shuffle,
}

/// One preparation's take choices and their state, independent of voice lifetime.
pub struct TakeSelector {
    seed: u64,
    selections: Vec<Selection>,
    slots: BTreeMap<Identifier, Slot>,
    partitions: BTreeMap<Partition, (u64, Sequence)>,
    use_count: u64,
}

impl TakeSelector {
    pub(crate) fn decode(
        value: serde_json::Value,
        seed: u64,
        limits: PreparationLimits,
    ) -> Result<Self, Error> {
        let definition: Definition =
            serde_json::from_value(value).map_err(|error| invalid(error.to_string()))?;
        if 1 + definition.selections.len() + definition.slots.len() > limits.max_records() {
            return Err(Error::Limit("sample take selector records"));
        }
        let mut selections = BTreeMap::new();
        for (index, selection) in definition.selections.iter().enumerate() {
            if selections.insert(selection.name.clone(), index).is_some() {
                return Err(invalid("duplicate selection ID"));
            }
        }
        let mut slots = BTreeMap::new();
        for slot in definition.slots {
            let group = slot
                .selection
                .as_ref()
                .map(|name| {
                    selections.get(name).copied().ok_or_else(|| {
                        invalid(format!(
                            "Slot {}: unknown selection {}",
                            slot.name.as_str(),
                            name.as_str()
                        ))
                    })
                })
                .transpose()?;
            if group.is_none() && slot.take.is_some() {
                return Err(invalid("linked take requires a selection"));
            }
            if slots
                .insert(
                    slot.name,
                    Slot {
                        group,
                        take: slot.take,
                    },
                )
                .is_some()
            {
                return Err(invalid("duplicate sample slot name"));
            }
        }
        Ok(Self {
            seed,
            selections: definition.selections,
            slots,
            partitions: BTreeMap::new(),
            use_count: 0,
        })
    }

    /// Keep ungrouped slots, then the chosen take of each group in declaration order.
    pub fn select(
        &mut self,
        eligible: &[Identifier],
        part: &Identifier,
        trigger: Trigger,
        key: Option<i64>,
    ) -> Result<Vec<Identifier>, Error> {
        let mut selected = Vec::new();
        let mut groups = BTreeMap::<usize, Vec<_>>::new();
        let mut seen = BTreeSet::new();
        for name in eligible {
            if !seen.insert(name) {
                return Err(invalid("duplicate eligible slot"));
            }
            let slot = self
                .slots
                .get(name)
                .ok_or_else(|| invalid(format!("Unknown eligible slot: {}", name.as_str())))?;
            if let Some(group) = slot.group {
                groups
                    .entry(group)
                    .or_default()
                    .push((name, slot.take.as_ref().unwrap_or(name)));
            } else {
                selected.push(name.clone());
            }
        }

        // Commit all group choices together, including the snapshot order.
        let mut pending = Vec::with_capacity(groups.len());
        let mut use_count = self.use_count;
        for (group, slots) in groups {
            let selection = &self.selections[group];
            let key = key.ok_or_else(|| invalid("a take selection requires an event key"))?;
            let candidates: BTreeSet<_> = slots.iter().map(|(_, take)| *take).collect();
            let partition = Partition {
                part: part.clone(),
                selection: selection.name.clone(),
                trigger,
                key,
                candidates: candidates.into_iter().cloned().collect(),
            };
            let sequence = self
                .partitions
                .get(&partition)
                .map_or_else(|| partition.sequence(), |(_, state)| state.clone());
            let (choice, next) = sequence.advance(selection.mode, self.seed)?;
            selected.extend(
                slots
                    .into_iter()
                    .filter(|(_, take)| **take == choice)
                    .map(|(name, _)| name.clone()),
            );
            pending.push((partition, (use_count, next)));
            use_count = use_count
                .checked_add(1)
                .ok_or(Error::Limit("sample take selection order"))?;
        }
        self.partitions.extend(pending);
        self.use_count = use_count;
        Ok(selected)
    }

    /// Snapshot partitions in the order of their latest successful choice.
    pub fn sequences(&self) -> impl Iterator<Item = &Sequence> {
        let mut entries: Vec<_> = self.partitions.values().collect();
        entries.sort_unstable_by_key(|(index, _)| *index);
        entries.into_iter().map(|(_, state)| state)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Definition {
    selections: Vec<Selection>,
    slots: Vec<SlotSelection>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Selection {
    pub(super) name: Identifier,
    mode: Mode,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SlotSelection {
    name: Identifier,
    selection: Option<Identifier>,
    take: Option<Identifier>,
}

struct Slot {
    group: Option<usize>,
    take: Option<Identifier>,
}

#[derive(PartialEq, Eq, PartialOrd, Ord)]
struct Partition {
    part: Identifier,
    selection: Identifier,
    trigger: Trigger,
    key: i64,
    candidates: Vec<Identifier>,
}

impl Partition {
    fn sequence(&self) -> Sequence {
        Sequence {
            part: self.part.clone(),
            selection: self.selection.clone(),
            trigger: self.trigger,
            key: self.key,
            candidates: self.candidates.clone(),
            counter: 0,
            remaining: Vec::new(),
            previous: None,
        }
    }
}

/// One partition of the sampler's serializable take-selection state.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Sequence {
    pub part: Identifier,
    pub selection: Identifier,
    pub trigger: Trigger,
    pub key: i64,
    pub candidates: Vec<Identifier>,
    #[serde(default)]
    pub counter: u64,
    #[serde(default)]
    pub remaining: Vec<Identifier>,
    pub previous: Option<Identifier>,
}

impl Sequence {
    /// Return the chosen take and the next state for this partition.
    pub fn advance(mut self, mode: Mode, seed: u64) -> Result<(Identifier, Self), Error> {
        if self.candidates.is_empty() || self.candidates.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(Error::Invalid(
                "sample candidates must be sorted and unique".into(),
            ));
        }
        let mut seen = BTreeSet::new();
        if self
            .remaining
            .iter()
            .any(|id| self.candidates.binary_search(id).is_err() || !seen.insert(id))
            || self
                .previous
                .as_ref()
                .is_some_and(|id| self.candidates.binary_search(id).is_err())
        {
            return Err(Error::Invalid(
                "invalid sample selection partition state".into(),
            ));
        }
        let len = self.candidates.len();
        let choice = match mode {
            Mode::Cycle | Mode::Random => {
                let index = match mode {
                    Mode::Cycle => (self.counter % len as u64) as usize,
                    _ => self.draw(seed, len, None)?,
                };
                self.increment_counter()?;
                self.candidates[index].clone()
            }
            Mode::Shuffle => {
                if self.remaining.is_empty() {
                    self.refill(seed)?;
                }
                let choice = self.remaining.remove(0);
                self.previous = Some(choice.clone());
                choice
            }
        };
        Ok((choice, self))
    }

    fn increment_counter(&mut self) -> Result<(), Error> {
        self.counter = self
            .counter
            .checked_add(1)
            .ok_or(Error::Limit("sample selection counter"))?;
        Ok(())
    }

    fn refill(&mut self, seed: u64) -> Result<(), Error> {
        let mut remaining = self.candidates.clone();
        let start = if let Some(previous) = self.previous.as_ref().filter(|_| remaining.len() > 1) {
            let excluded = self
                .candidates
                .binary_search(previous)
                .expect("validated take");
            let index = self.draw(seed, remaining.len() - 1, Some(previous))?;
            let first = remaining.remove(index + usize::from(index >= excluded));
            remaining.insert(0, first);
            self.increment_counter()?;
            1
        } else {
            0
        };
        for index in (start + 1..remaining.len()).rev() {
            let swap = start + self.draw(seed, index - start + 1, None)?;
            remaining.swap(index, swap);
            self.increment_counter()?;
        }
        self.remaining = remaining;
        Ok(())
    }

    fn draw(&self, seed: u64, bound: usize, excluded: Option<&Identifier>) -> Result<usize, Error> {
        let mut digest = Sha256::new();
        for field in [
            &seed.to_string(),
            self.part.as_str(),
            self.selection.as_str(),
            self.trigger.as_str(),
            &self.key.to_string(),
        ]
        .into_iter()
        .chain(self.candidates.iter().map(Identifier::as_str))
        .chain([
            self.counter.to_string().as_str(),
            excluded.map_or("", Identifier::as_str),
        ]) {
            hash_field(&mut digest, field);
        }
        let bound = NonZeroU64::new(bound as u64).expect("positive take count");
        Ok(uniform_integer(digest, bound)? as usize)
    }
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
