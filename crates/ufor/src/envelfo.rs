//! Preparation bounds for generator definitions. This preflight counts records;
//! it does not establish structural validity or execute a generator.

use crate::error::Error;
use serde_json::Value;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PreparationLimits {
    max_records: usize,
}

impl Default for PreparationLimits {
    fn default() -> Self {
        Self {
            max_records: 10_000,
        }
    }
}

impl PreparationLimits {
    pub fn new(max_records: usize) -> Result<Self, Error> {
        if u64::try_from(max_records).map_err(|_| Error::ArithmeticRange)? > i64::MAX as u64 {
            return Err(Error::Invalid(
                "max_records exceeds the signed 64-bit domain".into(),
            ));
        }
        Ok(Self { max_records })
    }

    pub fn max_records(self) -> usize {
        self.max_records
    }

    pub fn check_records(self, count: usize) -> Result<(), Error> {
        if count > self.max_records {
            Err(Error::Limit("generator preparation records"))
        } else {
            Ok(())
        }
    }
}

/// Count declarations and references once per occurrence, without expanding
/// shared nodes. Text, parsed-value and nesting budgets are separate checks.
pub fn preparation_records(value: &Value, limits: PreparationLimits) -> Result<usize, Error> {
    let mut pending = vec![value];
    let mut count = usize::from(value.is_object());
    limits.check_records(count)?;
    while let Some(item) = pending.pop() {
        let Some(item) = item.as_object() else {
            continue;
        };
        for (key, child) in item {
            match key.as_str() {
                "envelfos" | "parameters" | "controls" if child.is_object() => {
                    count = count
                        .checked_add(child.as_object().map_or(0, |v| v.len()))
                        .ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.extend(child.as_object().into_iter().flat_map(|v| v.values()));
                }
                "segments" | "release" | "markers" | "stages" | "transitions" | "events"
                | "event_connections" | "bindings" | "sources" | "routes" | "points"
                | "parameters"
                    if child.is_array() =>
                {
                    count = count
                        .checked_add(child.as_array().map_or(0, Vec::len))
                        .ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.extend(child.as_array().into_iter().flatten());
                }
                "inputs" | "from" | "from_stages" if child.is_array() => {
                    count = count
                        .checked_add(child.as_array().map_or(0, Vec::len))
                        .ok_or(Error::ArithmeticRange)?;
                }
                "outputs" | "event_outputs" if child.is_object() => {
                    count = count
                        .checked_add(child.as_object().map_or(0, |v| v.len()))
                        .ok_or(Error::ArithmeticRange)?;
                }
                "body" | "envelfo" | "modulation" if child.is_object() => {
                    count = count.checked_add(1).ok_or(Error::ArithmeticRange)?;
                    limits.check_records(count)?;
                    pending.push(child);
                }
                _ => (),
            }
            limits.check_records(count)?;
        }
    }
    Ok(count)
}
