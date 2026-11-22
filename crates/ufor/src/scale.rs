//! Generalized periodic note naming and mapping to tuning coordinates.

use crate::accidentals::{Accidentals, canonical};
use crate::codec::MAX_SCORE_CHARACTERS;
use crate::error::Error;
use crate::expression::evaluate_unit;
use crate::musical::whitespace;
use crate::number::Number;
use crate::tuning::MAX_TABLE_ENTRIES;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(try_from = "ScaleDefinition")]
pub struct Scale {
    definition: ScaleDefinition,
    names: String,
    octave_length: i64,
    spellings: Vec<[String; 2]>,
    note_numbers: Vec<i64>,
}

impl Scale {
    pub fn names(&self) -> &str {
        &self.names
    }

    pub fn octave_length(&self) -> i64 {
        self.octave_length
    }

    pub fn note_count(&self) -> usize {
        self.note_numbers.len()
    }

    pub fn note_numbers(&self) -> &[i64] {
        &self.note_numbers
    }

    pub fn to_name(&self, note_number: i64, use_sharp: bool) -> Result<String, Error> {
        let (octave, position) = self.position(note_number)?;
        Ok(format!(
            "{}{octave}",
            self.spellings[position][usize::from(use_sharp)]
        ))
    }

    pub fn to_number(&self, text: &str) -> Result<i64, Error> {
        let (name, octave) = self
            .definition
            .accidentals
            .split_note(text, &self.names)
            .ok_or_else(|| invalid("invalid scale note name"))?;
        let position = self
            .spellings
            .iter()
            .position(|pair| pair.contains(&name))
            .ok_or_else(|| invalid("invalid scale note name"))?;
        let index = self
            .note_numbers
            .binary_search(&(position as i64))
            .map_err(|_| invalid("note is outside the selected scale"))?;
        let octave = octave
            .trim_matches(whitespace)
            .parse::<i128>()
            .map_err(|_| invalid("invalid scale octave"))?;
        self.absolute(octave, self.note_count() as i64, index as i64)
    }

    pub fn tuning_number(&self, note_number: i64) -> Result<i64, Error> {
        let (octave, position) = self.position(note_number)?;
        self.absolute(octave, self.octave_length, position as i64)
    }

    pub fn frequency(
        &self,
        tuning: impl FnOnce(i64) -> Result<Number, Error>,
        note_number: i64,
    ) -> Result<f64, Error> {
        Ok(tuning(self.tuning_number(note_number)?)?.as_f64())
    }

    fn position(&self, note_number: i64) -> Result<(i128, usize), Error> {
        let count = self.note_count() as i128;
        if count == 0 {
            return Err(invalid("scale has no playable positions"));
        }
        let relative = i128::from(note_number) - i128::from(self.definition.offset);
        Ok((
            relative.div_euclid(count),
            self.note_numbers[relative.rem_euclid(count) as usize] as usize,
        ))
    }

    fn absolute(&self, octave: i128, period: i64, position: i64) -> Result<i64, Error> {
        let relative = octave
            .checked_mul(i128::from(period))
            .ok_or(Error::ArithmeticRange)?;
        let offset = i128::from(position) + i128::from(self.definition.offset);
        i64::try_from(relative.checked_add(offset).ok_or(Error::ArithmeticRange)?)
            .map_err(|_| Error::ArithmeticRange)
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(default, deny_unknown_fields)]
struct ScaleDefinition {
    note_names: String,
    root: String,
    begin: String,
    end: String,
    notes: Option<String>,
    #[serde(deserialize_with = "intervals")]
    intervals: Vec<i64>,
    accidentals: Accidentals,
    #[serde(deserialize_with = "offset")]
    offset: i64,
}

impl Default for ScaleDefinition {
    fn default() -> Self {
        Self {
            note_names: "ABCDEFGHIJKLMNOPQRSTUVWXYZ".into(),
            root: "C".into(),
            begin: "A".into(),
            end: "G".into(),
            notes: None,
            intervals: vec![2, 2, 1, 2, 2, 2, 1],
            accidentals: Accidentals::Whole,
            offset: 0,
        }
    }
}

impl TryFrom<ScaleDefinition> for Scale {
    type Error = Error;

    fn try_from(definition: ScaleDefinition) -> Result<Self, Error> {
        let find = |name| {
            definition
                .note_names
                .find(name)
                .ok_or_else(|| invalid("begin, root and end must be present in note_names"))
        };
        let (begin, root, end) = (
            find(&definition.begin)?,
            find(&definition.root)?,
            find(&definition.end)?,
        );
        if !(begin <= root && root <= end) {
            return Err(invalid(
                "begin, root, and end must be ordered in note_names",
            ));
        }
        let end = end
            + definition.note_names[end..]
                .chars()
                .next()
                .map_or(0, char::len_utf8);
        let names = format!(
            "{}{}",
            &definition.note_names[root..end],
            &definition.note_names[begin..root]
        );
        let glyphs: Vec<_> = names.chars().collect();
        let steps = definition
            .intervals
            .iter()
            .copied()
            .cycle()
            .take(glyphs.len());
        let mut octave_length = 0;
        let mut spellings = Vec::new();
        let mut characters = 0;
        for (index, interval) in steps.enumerate() {
            let interval =
                usize::try_from(interval).map_err(|_| Error::Limit("scale positions"))?;
            if interval.max(1) > MAX_TABLE_ENTRIES - spellings.len() {
                return Err(Error::Limit("scale positions"));
            }
            octave_length += interval as i64;
            let note = glyphs[index];
            let next_note = glyphs[(index + 1) % glyphs.len()];
            spellings.push([note.to_string(), note.to_string()]);
            characters += 2;
            for position in 1..interval {
                let pair = definition
                    .accidentals
                    .spellings(note, next_note, interval, position);
                characters += pair.iter().map(|name| name.chars().count()).sum::<usize>();
                if characters > MAX_SCORE_CHARACTERS {
                    return Err(Error::Limit("scale spelling characters"));
                }
                spellings.push(pair);
            }
        }
        let note_numbers = match &definition.notes {
            None => (0..octave_length).collect(),
            Some(notes) => {
                let allowed = selected_names(notes, &names, definition.accidentals);
                spellings
                    .iter()
                    .enumerate()
                    .filter(|(_, names)| names.iter().any(|name| allowed.contains(name)))
                    .map(|(index, _)| index as i64)
                    .collect()
            }
        };
        Ok(Self {
            definition,
            names,
            octave_length,
            spellings,
            note_numbers,
        })
    }
}

impl Serialize for Scale {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.definition.serialize(serializer)
    }
}

fn selected_names(text: &str, names: &str, accidentals: Accidentals) -> BTreeSet<String> {
    let text: String = text.chars().map(canonical).collect();
    let heads: BTreeSet<_> = names.chars().collect();
    let mut remaining = text.as_str();
    let mut allowed = BTreeSet::new();
    while let Some(head) = remaining.chars().next() {
        if heads.contains(&head) {
            let (note, tail) = accidentals.split_after_head(remaining, head);
            allowed.insert(note);
            remaining = tail;
        } else {
            remaining = &remaining[head.len_utf8()..];
        }
    }
    if allowed.is_empty() {
        allowed.extend(names.chars().map(|name| name.to_string()));
    }
    allowed
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Step {
    Integer(i64),
    Text(String),
}

impl Step {
    fn value(self) -> Result<i64, Error> {
        match self {
            Self::Integer(value) => Ok(value),
            Self::Text(text) => {
                let (value, _) = evaluate_unit(&text, SEMITONE_UNITS)?;
                value
                    .rational()
                    .filter(|ratio| ratio.denominator() == 1)
                    .map(|ratio| ratio.numerator())
                    .ok_or_else(|| invalid("scale steps must be integers"))
            }
        }
    }
}

fn intervals<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<i64>, D::Error> {
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Intervals {
        Compact(String),
        Steps(Vec<Step>),
    }
    let steps: Vec<_> = match Intervals::deserialize(d)? {
        Intervals::Compact(text) => text.chars().filter(|character| !whitespace(*character))
            .map(|character| Step::Text(character.to_string())).collect(),
        Intervals::Steps(values) => values.into_iter().filter(|step| !matches!(step, Step::Text(text) if !text.is_empty() && text.chars().all(whitespace))).collect(),
    };
    let values: Vec<i64> = steps
        .into_iter()
        .map(Step::value)
        .collect::<Result<_, _>>()
        .map_err(serde::de::Error::custom)?;
    if values.is_empty() || values.iter().any(|value| *value < 0) {
        return Err(serde::de::Error::custom(
            "scale needs nonnegative integer intervals",
        ));
    }
    Ok(values)
}

fn offset<'de, D: Deserializer<'de>>(d: D) -> Result<i64, D::Error> {
    Step::deserialize(d)?
        .value()
        .map_err(serde::de::Error::custom)
}

fn invalid(message: &str) -> Error {
    Error::Invalid(message.into())
}

const SEMITONE_UNITS: &[(&str, i64, i64)] = &[
    ("semitones", 1, 1),
    ("semitone", 1, 1),
    ("musical_cent", 1, 100),
    ("cents", 1, 100),
    ("cent", 1, 100),
    ("octave", 12, 1),
    ("oct", 12, 1),
];
