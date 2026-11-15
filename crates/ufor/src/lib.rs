//! Native uFor mathematics, independent of Python and host applications.

#![forbid(unsafe_code)]
#![doc = include_str!("../../../doc/rust.md")]

pub mod codec;
pub mod error;
pub mod expression;
pub mod musical;
pub mod number;
pub mod tuning;
pub mod units;
