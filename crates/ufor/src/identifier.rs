//! Portable identifiers pinned by the tracked Python 3.13 Unicode generator.

use crate::error::Error;
use crate::identifier_ranges::{DIGITS, LOWERCASE};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct Identifier(String);

impl Identifier {
    pub fn new(value: String) -> Result<Self, Error> {
        if value.chars().take(4097).count() > 4096 {
            return Err(Error::Limit("identifier characters"));
        }
        let mut chars = value.chars();
        if !chars.next().is_some_and(|c| contains(LOWERCASE, c))
            || !value
                .chars()
                .all(|c| contains(LOWERCASE, c) || contains(DIGITS, c) || matches!(c, '-' | '_'))
        {
            return Err(Error::Invalid("invalid portable identifier".into()));
        }
        Ok(Self(value))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}
impl TryFrom<String> for Identifier {
    type Error = Error;
    fn try_from(value: String) -> Result<Self, Error> {
        Self::new(value)
    }
}
impl From<Identifier> for String {
    fn from(value: Identifier) -> Self {
        value.0
    }
}

fn contains(ranges: &[[u32; 2]], value: char) -> bool {
    let value = value as u32;
    let index = ranges.partition_point(|r| r[0] <= value);
    index != 0 && value <= ranges[index - 1][1]
}
