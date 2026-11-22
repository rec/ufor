//! The tuning-only score envelope, using the common uFor header rules.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};

use crate::error::Error;
use crate::tuning::Tuning;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(try_from = "TuningScoreDefinition", into = "TuningScoreDefinition")]
pub struct TuningScore {
    name: String,
    title: String,
    tags: Vec<String>,
    body: Tuning,
}

impl TuningScore {
    pub fn new(
        name: String,
        title: String,
        tags: Vec<String>,
        body: Tuning,
    ) -> Result<Self, Error> {
        let normalized = header(&name, &title, tags)?;
        Ok(Self {
            name,
            title,
            tags: normalized,
            body,
        })
    }

    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn title(&self) -> &str {
        &self.title
    }
    pub fn tags(&self) -> &[String] {
        &self.tags
    }
    pub fn body(&self) -> &Tuning {
        &self.body
    }
}

pub(crate) fn header(name: &str, title: &str, tags: Vec<String>) -> Result<Vec<String>, Error> {
    if name.is_empty()
        || name.trim_matches(whitespace) != name
        || name.contains([':', '#', '/'])
        || name.contains(".*")
    {
        return Err(Error::Invalid("invalid score name".into()));
    }
    if title.is_empty() {
        return Err(Error::Invalid("score title must not be empty".into()));
    }
    let mut distinct = HashSet::new();
    let mut normalized = Vec::new();
    for tag in tags {
        if !tag.starts_with('#')
            || tag.len() == 1
            || tag[1..]
                .chars()
                .any(|c| whitespace(c) || matches!(c, ':' | '#' | '/'))
        {
            return Err(Error::Invalid("invalid score tag".into()));
        }
        if distinct.insert(tag.clone()) {
            normalized.push(tag);
        }
    }
    Ok(normalized)
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct TuningScoreDefinition {
    #[serde(default = "format")]
    format: String,
    #[serde(default = "version")]
    version: i64,
    #[serde(default = "kind")]
    kind: String,
    name: String,
    title: String,
    #[serde(default)]
    tags: Vec<String>,
    body: Tuning,
}

impl TryFrom<TuningScoreDefinition> for TuningScore {
    type Error = Error;
    fn try_from(value: TuningScoreDefinition) -> Result<Self, Error> {
        if value.format != "recs" || value.version != 4 || value.kind != "tuning" {
            return Err(Error::Invalid(
                "expected a recs version 4 tuning score".into(),
            ));
        }
        Self::new(value.name, value.title, value.tags, value.body)
    }
}
impl From<TuningScore> for TuningScoreDefinition {
    fn from(value: TuningScore) -> Self {
        Self {
            format: format(),
            version: version(),
            kind: kind(),
            name: value.name,
            title: value.title,
            tags: value.tags,
            body: value.body,
        }
    }
}

fn format() -> String {
    "recs".into()
}
fn version() -> i64 {
    4
}
fn kind() -> String {
    "tuning".into()
}

pub(crate) fn whitespace(value: char) -> bool {
    // Python's selector validators also treat these C0 separators as whitespace.
    value.is_whitespace() || matches!(value, '\u{1c}'..='\u{1f}')
}
