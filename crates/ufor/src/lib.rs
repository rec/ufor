//! Native uFor mathematics, independent of Python and host applications.

#![forbid(unsafe_code)]
#![doc = include_str!("../../../doc/rust.md")]

pub mod accidentals;
pub mod codec;
pub mod control;
pub mod effects;
pub mod envelfo;
pub mod error;
pub mod events;
pub mod expression;
pub mod fm;
pub mod identifier;
mod identifier_ranges;
pub mod modulation;
pub mod musical;
pub mod number;
pub mod oscillator;
pub mod performance_binding;
pub mod playback;
pub mod quantity;
pub mod samples;
pub mod scala;
pub mod scale;
pub mod score;
pub mod sequence;
pub mod synth_pitch;
pub mod time;
pub mod tuning;
pub mod units;
pub mod voice_admission;
pub mod voice_release;
pub mod voice_start;
