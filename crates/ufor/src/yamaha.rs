//! Lossless Yamaha edit buffers as stored in synth instrument declarations.

use crate::error::Error;
use serde::{Deserialize, Serialize};
use std::fmt::Write;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "PatchWire", into = "PatchWire")]
pub enum Patch {
    Dx7(Dx7Voice),
    Tx81z(Tx81zVoice),
    Wt11(Wt11Voice),
}

impl Patch {
    pub fn dx7(patch: &[u8]) -> Result<Self, Error> {
        let data = match patch.len() {
            128 => Dx7Data::Packed(buffer("DX7 packed voice", patch)?),
            155 => Dx7Data::Unpacked(buffer("DX7 unpacked voice", patch)?),
            _ => {
                return Err(Error::Invalid(
                    "DX7 voice data must contain 128 or 155 seven-bit bytes".into(),
                ));
            }
        };
        Ok(Self::Dx7(Dx7Voice(data)))
    }

    pub fn tx81z(patch: &[u8], additional: &[u8]) -> Result<Self, Error> {
        Ok(Self::Tx81z(Tx81zVoice(four_operator_data(
            ["TX81Z VCED", "TX81Z ACED"],
            patch,
            additional,
        )?)))
    }

    pub fn wt11(patch: &[u8], additional: &[u8], additional2: &[u8]) -> Result<Self, Error> {
        Ok(Self::Wt11(Wt11Voice {
            data: four_operator_data(["WT11 VCED", "WT11 ACED"], patch, additional)?,
            additional2: buffer("WT11 ACED2", additional2)?,
        }))
    }

    /// Return the first invalid decoded parameter, even when the dump can be stored.
    pub fn parameter_diagnostic(&self) -> Option<String> {
        match self {
            Self::Dx7(voice) => voice.parameter_diagnostic(),
            Self::Tx81z(voice) => voice.parameter_diagnostic(),
            Self::Wt11(voice) => voice.parameter_diagnostic(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Dx7Voice(Dx7Data);

#[derive(Clone, Debug, Eq, PartialEq)]
enum Dx7Data {
    Packed([u8; 128]),
    Unpacked([u8; 155]),
}

impl Dx7Voice {
    pub fn data(&self) -> &[u8] {
        match &self.0 {
            Dx7Data::Packed(data) => data,
            Dx7Data::Unpacked(data) => data,
        }
    }

    pub fn packed(&self) -> bool {
        matches!(&self.0, Dx7Data::Packed(_))
    }

    pub fn algorithm(&self) -> u8 {
        self.data()[if self.packed() { 110 } else { 134 }] + 1
    }

    pub fn feedback(&self) -> u8 {
        if self.packed() {
            self.data()[111] & 7
        } else {
            self.data()[135]
        }
    }

    pub fn title(&self) -> &str {
        let start = if self.packed() { 118 } else { 145 };
        ascii(&self.data()[start..start + 10])
    }

    fn parameter_diagnostic(&self) -> Option<String> {
        let algorithm = self.algorithm();
        if algorithm > 32 {
            return Some(format!("DX7 algorithm {algorithm} is outside 1 through 32"));
        }
        let feedback = self.feedback();
        if feedback > 7 {
            return Some(format!("DX7 feedback {feedback} is outside 0 through 7"));
        }
        let width = if self.packed() { 17 } else { 21 };
        let ranges = if self.packed() {
            DX7_PACKED
        } else {
            DX7_UNPACKED
        };
        (1..=6).find_map(|number| {
            let offset = (6 - number) * width;
            let data = &self.data()[offset..offset + width];
            let field = outside(data, ranges)
                .or_else(|| (self.packed() && data[12] >> 3 > 14).then_some("detune"))?;
            Some(format!("DX7 operator {number} has invalid {field}"))
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Tx81zVoice(FourOperatorData);

impl Tx81zVoice {
    pub fn data(&self) -> &[u8; 93] {
        &self.0.patch
    }

    pub fn additional(&self) -> &[u8; 23] {
        &self.0.additional
    }

    pub fn algorithm(&self) -> u8 {
        self.0.patch[52] + 1
    }

    pub fn feedback(&self) -> u8 {
        self.0.patch[53]
    }

    pub fn title(&self) -> &str {
        ascii(&self.0.patch[77..87])
    }

    fn parameter_diagnostic(&self) -> Option<String> {
        let algorithm = self.algorithm();
        if algorithm > 8 {
            return Some(format!(
                "TX81Z algorithm {algorithm} is outside 1 through 8"
            ));
        }
        let feedback = self.feedback();
        if feedback > 7 {
            return Some(format!("TX81Z feedback {feedback} is outside 0 through 7"));
        }
        self.0
            .voice_diagnostic("TX81Z", TX81Z_ORDER)
            .or_else(|| self.0.additional_diagnostic("TX81Z", TX81Z_ORDER))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wt11Voice {
    data: FourOperatorData,
    additional2: [u8; 10],
}

impl Wt11Voice {
    pub fn data(&self) -> &[u8; 93] {
        &self.data.patch
    }

    pub fn additional(&self) -> &[u8; 23] {
        &self.data.additional
    }

    pub fn additional2(&self) -> &[u8; 10] {
        &self.additional2
    }

    fn parameter_diagnostic(&self) -> Option<String> {
        let data = &self.data.patch;
        if data[52] > 7 || data[53] > 7 {
            return Some("WT11 algorithm or feedback is outside 0 through 7".into());
        }
        if let Some(diagnostic) = self.data.voice_diagnostic("WT11", WT11_ORDER) {
            return Some(diagnostic);
        }
        if data[75] > 100 {
            return Some("WT11 breath pitch bias is outside 0 through 100".into());
        }
        if data[87..93].iter().any(|&value| value > 99) {
            return Some("WT11 pitch envelope has a rate or level outside 0 through 99".into());
        }
        self.data
            .additional_diagnostic("WT11", WT11_ORDER)
            .or_else(|| {
                outside(&self.additional2, WT11_AFTERTOUCH)
                    .map(|field| format!("WT11 aftertouch has invalid {field}"))
            })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct FourOperatorData {
    patch: [u8; 93],
    additional: [u8; 23],
}

impl FourOperatorData {
    fn voice_diagnostic(&self, model: &str, order: [usize; 4]) -> Option<String> {
        order.into_iter().enumerate().find_map(|(index, block)| {
            let start = block * 13;
            let field = outside(&self.patch[start..start + 13], FOUR_OPERATOR)?;
            Some(format!(
                "{model} operator {} has invalid {field}",
                index + 1
            ))
        })
    }

    fn additional_diagnostic(&self, model: &str, order: [usize; 4]) -> Option<String> {
        order.into_iter().enumerate().find_map(|(index, block)| {
            let start = block * 5;
            let field = outside(&self.additional[start..start + 5], ADDITIONAL)?;
            Some(format!(
                "{model} additional operator {} has invalid {field}",
                index + 1
            ))
        })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "yamaha", rename_all = "lowercase", deny_unknown_fields)]
enum PatchWire {
    Dx7 {
        patch: String,
    },
    Tx81z {
        patch: String,
        additional: String,
    },
    Wt11 {
        patch: String,
        additional: String,
        additional2: String,
    },
}

impl TryFrom<PatchWire> for Patch {
    type Error = Error;

    fn try_from(value: PatchWire) -> Result<Self, Error> {
        match value {
            PatchWire::Dx7 { patch } => Self::dx7(&decode_hex(&patch)?),
            PatchWire::Tx81z { patch, additional } => {
                Self::tx81z(&decode_hex(&patch)?, &decode_hex(&additional)?)
            }
            PatchWire::Wt11 {
                patch,
                additional,
                additional2,
            } => Self::wt11(
                &decode_hex(&patch)?,
                &decode_hex(&additional)?,
                &decode_hex(&additional2)?,
            ),
        }
    }
}

impl From<Patch> for PatchWire {
    fn from(value: Patch) -> Self {
        match value {
            Patch::Dx7(voice) => Self::Dx7 {
                patch: hex(voice.data()),
            },
            Patch::Tx81z(voice) => Self::Tx81z {
                patch: hex(voice.data()),
                additional: hex(voice.additional()),
            },
            Patch::Wt11(voice) => Self::Wt11 {
                patch: hex(voice.data()),
                additional: hex(voice.additional()),
                additional2: hex(voice.additional2()),
            },
        }
    }
}

fn four_operator_data(
    [patch_name, additional_name]: [&str; 2],
    patch: &[u8],
    additional: &[u8],
) -> Result<FourOperatorData, Error> {
    Ok(FourOperatorData {
        patch: buffer(patch_name, patch)?,
        additional: buffer(additional_name, additional)?,
    })
}

fn buffer<const N: usize>(name: &str, data: &[u8]) -> Result<[u8; N], Error> {
    if let Ok(bytes) = data.try_into() {
        if seven_bit(data) {
            return Ok(bytes);
        }
    }
    Err(Error::Invalid(format!(
        "{name} data must contain {N} seven-bit bytes"
    )))
}

fn seven_bit(data: &[u8]) -> bool {
    data.iter().all(u8::is_ascii)
}

fn ascii(data: &[u8]) -> &str {
    std::str::from_utf8(data).expect("Yamaha bytes are seven-bit")
}

fn hex(data: &[u8]) -> String {
    let mut result = String::with_capacity(data.len() * 2);
    for byte in data {
        write!(&mut result, "{byte:02x}").expect("writing to a String succeeds");
    }
    result
}

fn decode_hex(text: &str) -> Result<Vec<u8>, Error> {
    let mut data = Vec::new();
    // Python bytes.fromhex accepts ASCII whitespace between complete bytes.
    // Vertical tab is whitespace for Python but not for u8::is_ascii_whitespace.
    for word in text.split(|c: char| c.is_ascii_whitespace() || c == '\u{b}') {
        for pair in word.as_bytes().chunks(2) {
            match pair {
                [high, low] if high.is_ascii_hexdigit() && low.is_ascii_hexdigit() => {
                    if data.len() == 155 {
                        return Err(Error::Limit("Yamaha edit buffer bytes"));
                    }
                    let high = char::from(*high).to_digit(16).expect("hex digit");
                    let low = char::from(*low).to_digit(16).expect("hex digit");
                    data.push((high * 16 + low) as u8);
                }
                _ => {
                    return Err(Error::Invalid(
                        "invalid hexadecimal Yamaha edit buffer".into(),
                    ));
                }
            }
        }
    }
    Ok(data)
}

type Bound = (usize, u8, &'static str);

fn outside(data: &[u8], ranges: &[Bound]) -> Option<&'static str> {
    ranges
        .iter()
        .find_map(|&(index, maximum, field)| (data[index] > maximum).then_some(field))
}

const DX7_PACKED: &[Bound] = &[
    (8, 99, "breakpoint"),
    (9, 99, "left_depth"),
    (10, 99, "right_depth"),
    (14, 99, "output_level"),
    (16, 99, "fine"),
];

const DX7_UNPACKED: &[Bound] = &[
    (8, 99, "breakpoint"),
    (9, 99, "left_depth"),
    (10, 99, "right_depth"),
    (11, 3, "left_curve"),
    (12, 3, "right_curve"),
    (13, 7, "rate_scaling"),
    (14, 3, "amplitude_modulation_sensitivity"),
    (15, 7, "key_velocity_sensitivity"),
    (16, 99, "output_level"),
    (18, 31, "coarse"),
    (19, 99, "fine"),
    (20, 14, "detune"),
];

const TX81Z_ORDER: [usize; 4] = [3, 2, 1, 0];
const WT11_ORDER: [usize; 4] = [3, 1, 2, 0];
const FOUR_OPERATOR: &[Bound] = &[
    (0, 31, "attack_rate"),
    (1, 31, "decay_1_rate"),
    (2, 31, "decay_2_rate"),
    (3, 15, "release_rate"),
    (4, 15, "decay_1_level"),
    (5, 99, "level_scaling"),
    (6, 3, "rate_scaling"),
    (7, 7, "eg_bias_sensitivity"),
    (9, 7, "key_velocity_sensitivity"),
    (10, 99, "output_level"),
    (11, 63, "coarse"),
    (12, 6, "detune"),
];

const ADDITIONAL: &[Bound] = &[
    (1, 7, "fixed_frequency_range"),
    (2, 15, "fine"),
    (3, 7, "waveform"),
    (4, 3, "eg_shift"),
];

const WT11_AFTERTOUCH: &[Bound] = &[
    (0, 99, "pitch"),
    (1, 99, "amplitude"),
    (2, 100, "pitch_bias"),
    (3, 99, "eg_bias"),
];
