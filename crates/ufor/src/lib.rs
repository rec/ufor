//! Native uFor mathematics, independent of Python and host applications.

#![forbid(unsafe_code)]
#![doc = include_str!("../../../doc/rust.md")]

pub mod codec;
pub mod control;
pub mod envelfo;
pub mod error;
pub mod expression;
pub mod identifier;
mod identifier_ranges;
pub mod modulation;
pub mod musical;
pub mod number;
pub mod quantity;
pub mod samples;
pub mod score;
pub mod tuning;
pub mod units;
