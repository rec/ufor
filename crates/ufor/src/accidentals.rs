//! Note-name glyphs for whole-step and half-step accidentals.

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Accidentals {
    None,
    #[default]
    Whole,
    Half,
}

impl Accidentals {
    pub fn symbols(self) -> &'static str {
        match self {
            Self::None => "",
            Self::Whole => "♭♯",
            Self::Half => "♭♯v^",
        }
    }

    /// Return the canonical note name and the remaining suffix.
    pub fn split_note<'a>(self, text: &'a str, names: &str) -> Option<(String, &'a str)> {
        let head = text.chars().next().filter(|head| names.contains(*head))?;
        Some(self.split_after_head(text, head))
    }

    pub(crate) fn split_after_head(self, text: &str, head: char) -> (String, &str) {
        let mut name = head.to_string();
        let mut end = head.len_utf8();
        for glyph in text[end..].chars() {
            let canonical = canonical(glyph);
            if !self.symbols().contains(canonical) {
                break;
            }
            name.push(canonical);
            end += glyph.len_utf8();
        }
        (name, &text[end..])
    }

    pub(crate) fn spellings(
        self,
        note: char,
        next_note: char,
        interval: usize,
        offset: usize,
    ) -> [String; 2] {
        let flat = self.spelling(next_note, interval - offset, '♭', 'v');
        let sharp = self.spelling(note, offset, '♯', '^');
        if self == Self::Half && offset > interval / 2 {
            [sharp, flat]
        } else {
            [flat, sharp]
        }
    }

    fn spelling(self, note: char, offset: usize, whole: char, half: char) -> String {
        let mut name = note.to_string();
        match self {
            Self::None => {}
            Self::Whole => name.extend(std::iter::repeat_n(whole, offset)),
            Self::Half => {
                name.extend(std::iter::repeat_n(whole, offset / 2));
                if offset % 2 == 1 {
                    name.push(half);
                }
            }
        }
        name
    }
}

pub(crate) fn canonical(glyph: char) -> char {
    match glyph {
        '#' => '♯',
        'b' => '♭',
        _ => glyph,
    }
}
