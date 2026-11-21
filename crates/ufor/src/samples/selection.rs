//! Deterministic advancement of one sampler take-selection partition.

use super::eligibility::Trigger;
use super::random::{hash_field, uniform_integer};
use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::num::NonZeroU64;

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    Cycle,
    Random,
    Shuffle,
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
