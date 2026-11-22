//! Scala text interchange for repeating ratio tables.

use crate::codec::MAX_SCORE_CHARACTERS;
use crate::error::Error;
use crate::expression::evaluate;
use crate::musical::whitespace;
use crate::number::Rational;
use crate::tuning::{MAX_TABLE_ENTRIES, RatioTable};

/// Read a Scala scale and retain its description and the supplied name.
pub fn parse_scala(text: &str, name: &str) -> Result<RatioTable, Error> {
    if text.chars().take(MAX_SCORE_CHARACTERS + 1).count() > MAX_SCORE_CHARACTERS {
        return Err(Error::Limit("Scala scale characters"));
    }
    let mut records = text
        .split(line_break)
        .map(|line| line.trim_matches(whitespace))
        .filter(|line| !line.is_empty() && !line.starts_with('!'));
    let description = records.next().ok_or_else(missing_header)?;
    let count = records.next().ok_or_else(missing_header)?;
    let count = count
        .parse::<usize>()
        .ok()
        .filter(|count| *count > 0)
        .ok_or_else(count_mismatch)?;
    if count > MAX_TABLE_ENTRIES {
        return Err(Error::Limit("tuning table entries"));
    }
    let mut ratios = Vec::with_capacity(count);
    ratios.push("1".into());
    for line in records.by_ref().take(count - 1) {
        ratios.push(pitch_expression(line));
    }
    let period = records.next().ok_or_else(count_mismatch)?;
    if records.next().is_some() {
        return Err(count_mismatch());
    }
    RatioTable::new(
        ratios,
        Some(pitch_expression(period)),
        name.into(),
        description.into(),
    )
}

/// Write a repeating ratio table that starts at unison.
pub fn scala_text(table: &RatioTable) -> Result<String, Error> {
    let repeat = table.repeat_ratio().ok_or_else(export_error)?;
    let unison = evaluate(&table.ratios()[0])?;
    let is_unison = unison.rational().map_or_else(
        || unison.as_f64() == 1.0,
        |value| value == Rational::from(1),
    );
    if !is_unison {
        return Err(export_error());
    }
    let description = if table.description().is_empty() {
        "Untitled"
    } else {
        table.description()
    };
    let mut lines = vec![
        format!("! {}", table.name()),
        "!".into(),
        description.into(),
        table.ratios().len().to_string(),
        "!".into(),
    ];
    for expression in table
        .ratios()
        .iter()
        .skip(1)
        .map(String::as_str)
        .chain([repeat])
    {
        let value = evaluate(expression)?;
        lines.push(value.rational().map_or_else(
            || format!("{:.12}", value.as_f64().log2() * 1200.0),
            |ratio| ratio.to_string(),
        ));
    }
    lines.push(String::new());
    Ok(lines.join("\n"))
}

fn pitch_expression(line: &str) -> String {
    let pitch = line
        .split(whitespace)
        .next()
        .expect("nonempty pitch record");
    if pitch.contains('.') {
        format!("2^({pitch}/1200)")
    } else {
        pitch.into()
    }
}

fn line_break(character: char) -> bool {
    matches!(
        character,
        '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}'..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

fn missing_header() -> Error {
    Error::Invalid("Scala scale requires a description, count and pitches".into())
}

fn count_mismatch() -> Error {
    Error::Invalid("Scala pitch count does not match the entries".into())
}

fn export_error() -> Error {
    Error::Invalid("Scala export requires a repeating table beginning at unison".into())
}
