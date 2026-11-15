# Rust implementation

The Cargo workspace currently implements checked pitch numbers and expression
evaluation in `crates/ufor-core`. Tuning models and document interchange are still
planned in [the tuning port plan](../plan/rust-tuning.md).

The crate uses Rust 2024 with a minimum compiler version of 1.85. Import symbols
from their defining modules:

```rust
use ufor_core::expression::evaluate;
use ufor_core::number::Rational;

let value = evaluate("5/4")?;
assert_eq!(value.rational(), Some(Rational::new(5, 4)?));
let step = evaluate("2^(1/12)")?;
assert!(step.rational().is_none());
# Ok::<(), ufor_core::error::Error>(())
```

`Number` distinguishes exact `Rational` values from approximate finite `f64`
values. Rational components are reduced signed 64-bit integers with positive
denominators. Arithmetic cross-cancels where possible, checks overflow, and
returns `Error::ArithmeticRange` rather than silently converting an exact result
to float. Fractional powers produce approximate values even when their numerical
result is an integer. `Rational::from_f64` recovers the exact binary fraction only
when its components fit the same bounds.

The expression parser accepts decimal/scientific literals, parentheses, unary
signs, division, and `^` powers. It implements the documented grammar directly,
including leading zeroes and whitespace between tokens. Limits are 4096
characters, 64 levels of parentheses or syntax depth, and exponent magnitude
1024 for powers. Scientific exponents have a separate magnitude limit of 4096;
exact literal construction and intermediate arithmetic must still fit 64 bits.
Signed and zero expressions are permitted; `Number::positive` supplies the
additional pitch constraint.

`limit_denominator` approximates the exact input, including the binary fraction
of an approximate value. Ties favor the smaller denominator, then the value
closer to zero. Numeric display uses Rust's formatting and is not a canonical
cross-language serialization of approximate values.

Python installation remains independent of Rust. The Rust core has no runtime
dependencies; its tests use `serde_json` to read shared conformance cases.

Run the native checks from the repository root:

```sh
cargo test --workspace --locked
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
```

The release workflow runs these checks on Linux, Windows, and macOS with the
minimum compiler and current stable Rust. A local macOS result does not establish
that those hosted jobs have passed.
