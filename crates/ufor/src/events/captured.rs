//! Captured transport events. Raw payloads are preserved without dispatching them.

use crate::error::Error;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::value::RawValue;
use std::fmt;

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "Capture", into = "Capture")]
pub struct CapturedPayload(Capture);

impl CapturedPayload {
    pub fn capture(&self) -> &Capture {
        &self.0
    }

    pub(crate) fn check_toml(&self) -> Result<(), Error> {
        if let Capture::Osc { decoded, .. } = &self.0 {
            for record in decoded {
                if let OscRecord::Message { args, .. } = record {
                    if args.contains(&OscArgument::Null) {
                        return Err(Error::Invalid(
                            "TOML cannot represent null array arguments; use JSON to preserve them"
                                .into(),
                        ));
                    }
                }
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Capture {
    Midi {
        data: Vec<u8>,
    },
    Ump {
        words: Vec<u32>,
    },
    Osc {
        data_b64: String,
        direction: OscDirection,
        source_time: Option<String>,
        endpoint: Option<Endpoint>,
        #[serde(default)]
        decoded: Vec<OscRecord>,
        reason: Option<String>,
    },
    Key {
        key: String,
        action: KeyAction,
        text: Option<String>,
        #[serde(default)]
        modifiers: Vec<String>,
        #[serde(default)]
        repeat: bool,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OscDirection {
    In,
    Out,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum KeyAction {
    Press,
    Release,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Endpoint {
    pub host: String,
    pub port: u16,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(untagged, deny_unknown_fields)]
pub enum OscRecord {
    Message {
        path: String,
        types: String,
        args: Vec<OscArgument>,
    },
    DecodeError {
        error: String,
    },
}

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(untagged)]
pub enum OscArgument {
    Text(String),
    Integer(i64),
    Float(f64),
    Boolean(bool),
    Null,
}

impl<'de> Deserialize<'de> for OscArgument {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct ArgumentVisitor;

        impl serde::de::Visitor<'_> for ArgumentVisitor {
            type Value = OscArgument;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str("a scalar OSC argument")
            }

            fn visit_bool<E: serde::de::Error>(self, value: bool) -> Result<OscArgument, E> {
                Ok(OscArgument::Boolean(value))
            }

            fn visit_i64<E: serde::de::Error>(self, value: i64) -> Result<OscArgument, E> {
                Ok(OscArgument::Integer(value))
            }

            fn visit_u64<E: serde::de::Error>(self, value: u64) -> Result<OscArgument, E> {
                i64::try_from(value)
                    .map(OscArgument::Integer)
                    .map_err(|_| E::custom("OSC integer argument exceeds the signed 64-bit domain"))
            }

            fn visit_f64<E: serde::de::Error>(self, value: f64) -> Result<OscArgument, E> {
                Ok(OscArgument::Float(value))
            }

            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<OscArgument, E> {
                Ok(OscArgument::Text(value.to_owned()))
            }

            fn visit_string<E: serde::de::Error>(self, value: String) -> Result<OscArgument, E> {
                Ok(OscArgument::Text(value))
            }

            fn visit_unit<E: serde::de::Error>(self) -> Result<OscArgument, E> {
                Ok(OscArgument::Null)
            }
        }

        deserializer.deserialize_any(ArgumentVisitor)
    }
}

impl TryFrom<Capture> for CapturedPayload {
    type Error = Error;

    fn try_from(record: Capture) -> Result<Self, Error> {
        let error = match &record {
            Capture::Midi { data } if data.is_empty() => "MIDI capture requires bytes",
            Capture::Ump { words }
                if words
                    .first()
                    .is_none_or(|word| words.len() != UMP_WORD_COUNTS[(word >> 28) as usize]) =>
            {
                "UMP word count does not match message type"
            }
            Capture::Osc { data_b64, .. } if !valid_base64(data_b64) => {
                "OSC packet must be valid base64"
            }
            Capture::Osc { decoded, .. }
                if decoded.iter().any(|record| {
                    matches!(record, OscRecord::Message { args, .. }
                        if args.iter().any(|arg| matches!(arg, OscArgument::Float(v) if !v.is_finite())))
                }) =>
            {
                "OSC floating-point argument must be finite"
            }
            Capture::Key { key, .. } if key.is_empty() => "key capture requires a nonempty key",
            _ => return Ok(Self(record)),
        };
        Err(Error::Invalid(error.into()))
    }
}

impl From<CapturedPayload> for Capture {
    fn from(payload: CapturedPayload) -> Self {
        payload.0
    }
}

fn valid_base64(text: &str) -> bool {
    let data = text.trim_end_matches('=');
    text.len() % 4 == 0
        && text.len() - data.len() <= 2
        && data
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'/'))
}

// JSON numbers above u64 or below i64 may already be binary64 when a
// deserializer visits them. Check the original OSC argument spelling.
#[derive(Deserialize)]
pub(crate) struct JsonCapture<'a> {
    #[serde(default, borrow)]
    decoded: Vec<JsonOscRecord<'a>>,
}

#[derive(Deserialize)]
struct JsonOscRecord<'a> {
    #[serde(default, borrow)]
    args: Vec<&'a RawValue>,
}

impl JsonCapture<'_> {
    pub(crate) fn check_integers(&self) -> Result<(), Error> {
        for argument in self.decoded.iter().flat_map(|record| &record.args) {
            let text = argument.get();
            if text.starts_with(|c: char| c == '-' || c.is_ascii_digit())
                && !text.contains(['.', 'e', 'E'])
                && text.parse::<i64>().is_err()
            {
                return Err(Error::Invalid(
                    "OSC integer argument exceeds the signed 64-bit domain".into(),
                ));
            }
        }
        Ok(())
    }
}

const UMP_WORD_COUNTS: [usize; 16] = [1, 1, 1, 2, 2, 4, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4];
