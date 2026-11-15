//! UTF-8 JSON/TOML interchange for tuning bodies and tuning scores.

use serde::Serialize;
use serde_json::Value;

use crate::error::Error;
use crate::musical::TuningScore;
use crate::tuning::Tuning;

pub const MAX_SCORE_CHARACTERS: usize = 16 * 1024 * 1024;
pub const MAX_DOCUMENT_VALUES: usize = 100_000;
pub const MAX_DOCUMENT_DEPTH: usize = 64;

#[derive(Clone, Copy, Debug)]
pub enum Format {
    Json,
    Toml,
}

pub fn parse_tuning(text: &str, format: Format) -> Result<Tuning, Error> {
    serde_json::from_value(read(text, format)?).map_err(|e| Error::Invalid(e.to_string()))
}

pub fn tuning_text(value: &Tuning, format: Format) -> Result<String, Error> {
    write(value, format)
}

pub fn parse_score(text: &str, format: Format) -> Result<TuningScore, Error> {
    let document = read(text, format)?;
    if document.get("kind").and_then(Value::as_str) != Some("tuning") {
        return Err(Error::Invalid("expected kind tuning".into()));
    }
    serde_json::from_value(document).map_err(|e| Error::Invalid(e.to_string()))
}

pub fn score_text(value: &TuningScore, format: Format) -> Result<String, Error> {
    write(value, format)
}

fn read(text: &str, format: Format) -> Result<Value, Error> {
    if text.chars().take(MAX_SCORE_CHARACTERS + 1).count() > MAX_SCORE_CHARACTERS {
        return Err(Error::Limit("score characters"));
    }
    let value = match format {
        Format::Json => serde_json::from_str(text).map_err(|e| Error::Invalid(e.to_string()))?,
        Format::Toml => {
            let value: toml::Value =
                toml::from_str(text).map_err(|e| Error::Invalid(e.to_string()))?;
            serde_json::to_value(value).map_err(|e| Error::Invalid(e.to_string()))?
        }
    };
    let mut pending = vec![(&value, 0)];
    let mut count = 0;
    while let Some((item, depth)) = pending.pop() {
        count += 1;
        if count > MAX_DOCUMENT_VALUES || depth > MAX_DOCUMENT_DEPTH {
            return Err(Error::Limit("document values or depth"));
        }
        match item {
            Value::Array(values) => pending.extend(values.iter().map(|v| (v, depth + 1))),
            Value::Object(values) => pending.extend(values.values().map(|v| (v, depth + 1))),
            _ => (),
        }
    }
    Ok(value)
}

fn write<T: Serialize>(value: &T, format: Format) -> Result<String, Error> {
    match format {
        Format::Json => {
            serde_json::to_string_pretty(value).map_err(|e| Error::Invalid(e.to_string()))
        }
        Format::Toml => toml::to_string_pretty(value).map_err(|e| Error::Invalid(e.to_string())),
    }
}
