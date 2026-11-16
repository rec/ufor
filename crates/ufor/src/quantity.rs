//! The finite scalar quantity grammar and exact second quantities for bindings.
use crate::error::Error;
use crate::expression::evaluate;
use crate::number::Rational;

pub const MAX_RECORDS: usize = 10_000;
pub const MAX_TEXT: usize = 4096;

pub fn finite(value: f64) -> Result<f64, Error> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(Error::ArithmeticRange)
    }
}

pub fn records(count: usize) -> Result<(), Error> {
    if count > MAX_RECORDS {
        Err(Error::Limit("modulation records"))
    } else {
        Ok(())
    }
}

pub fn scalar(text: &str, unit: &str) -> Result<f64, Error> {
    let unit = if unit == "hz_offset" { "hz" } else { unit };
    if !matches!(
        unit,
        "logical"
            | "ratio"
            | "normalized"
            | "hz"
            | "cents"
            | "db"
            | "volts"
            | "seconds"
            | "beats"
            | "radians"
    ) {
        return Err(invalid());
    }
    let (tokens, scale, _) = quantity(text, unit)?;
    scalar_tokens(tokens, scale)
}

/// Finite scalar reciprocal-second rate, not an exact time quantity.
pub fn rate(text: &str) -> Result<f64, Error> {
    let (numeric, unit, reciprocal) = generator_text(text, "per_second")?;
    let (tokens, scale, _) = quantity(&numeric, unit)?;
    scalar_tokens(tokens, scale.checked_mul(reciprocal)?)
}

fn scalar_tokens(tokens: Vec<&str>, scale: Rational) -> Result<f64, Error> {
    let mut value = finite(tokens[0].parse::<f64>().map_err(|_| invalid())?)?;
    for token in &tokens[1..] {
        let divisor = finite(token.parse::<f64>().map_err(|_| invalid())?)?;
        if divisor == 0.0 {
            return Err(Error::DivisionByZero);
        }
        value = finite(value / divisor)?;
    }
    finite(value * (scale.numerator() as f64 / scale.denominator() as f64))
}

pub fn exact_seconds(text: &str) -> Result<Rational, Error> {
    let value = exact(text, "seconds")?;
    if value.numerator() < 0 {
        return Err(Error::Invalid("smoothing must be nonnegative".into()));
    }
    Ok(value)
}

/// Portable exact generator quantity. Signed results are permitted; the field
/// consuming this value applies its own domain restrictions.
pub fn exact(text: &str, unit: &str) -> Result<Rational, Error> {
    if !matches!(
        unit,
        "seconds" | "beats" | "hz" | "phase" | "ratio" | "per_second" | "per_beat"
    ) {
        return Err(invalid());
    }
    let (numeric, numeric_unit, reciprocal) = generator_text(text, unit)?;
    let (tokens, scale, _) = quantity(&numeric, numeric_unit)?;
    let mut value = evaluate(tokens[0])?
        .rational()
        .ok_or(Error::ArithmeticRange)?;
    for token in &tokens[1..] {
        value = value.checked_div(evaluate(token)?.rational().ok_or(Error::ArithmeticRange)?)?;
    }
    value = value.checked_mul(scale)?;
    value.checked_mul(reciprocal)
}

/// Parse a segment duration with an explicit compatible suffix.
pub fn duration(text: &str) -> Result<(Rational, &'static str), Error> {
    for unit in ["seconds", "beats"] {
        if let Ok((_, _, Some(_))) = quantity(text, unit) {
            return Ok((exact(text, unit)?, unit));
        }
    }
    Err(invalid())
}

fn generator_text<'a>(text: &str, unit: &'a str) -> Result<(String, &'a str, Rational), Error> {
    if text.chars().take(MAX_TEXT + 1).count() > MAX_TEXT {
        return Err(Error::Limit("quantity characters"));
    }
    let mut numeric = text.to_owned();
    let mut numeric_unit = if unit == "per_second" { "hz" } else { unit };
    let mut reciprocal = Rational::new(1, 1)?;
    if matches!(unit, "hz" | "per_second" | "per_beat") {
        for (index, character) in text.char_indices() {
            if character != '/' {
                continue;
            }
            let tail = text[index + 1..].trim_start();
            let length = tail
                .bytes()
                .take_while(|c| c.is_ascii_alphabetic() || *c == b'_')
                .count();
            if length != 0 {
                if tail[length..]
                    .chars()
                    .next()
                    .is_some_and(|c| !c.is_whitespace() && c != '/')
                {
                    return Err(invalid());
                }
                reciprocal = Rational::new(1, 1)?.checked_div(factor(
                    if unit == "per_beat" {
                        "beats"
                    } else {
                        "seconds"
                    },
                    &tail[..length],
                )?)?;
                numeric = format!("{}{}", &text[..index], &tail[length..]);
                numeric_unit = "ratio";
                break;
            }
        }
    }
    Ok((numeric, numeric_unit, reciprocal))
}

fn quantity<'a>(
    text: &'a str,
    unit: &str,
) -> Result<(Vec<&'a str>, Rational, Option<&'a str>), Error> {
    if text.chars().take(MAX_TEXT + 1).count() > MAX_TEXT {
        return Err(Error::Limit("quantity characters"));
    }
    let bytes = text.as_bytes();
    let mut position = 0;
    let mut alias = None;
    let mut leading_alias = false;
    let mut tokens = Vec::new();
    while position < bytes.len() {
        let c = text[position..].chars().next().ok_or_else(invalid)?;
        if c.is_whitespace() {
            position += c.len_utf8();
            continue;
        }
        let start = position;
        if bytes[position].is_ascii_alphabetic() || bytes[position] == b'_' {
            while position < bytes.len()
                && (bytes[position].is_ascii_alphabetic() || bytes[position] == b'_')
            {
                position += 1;
            }
            if alias.replace(&text[start..position]).is_some() {
                return Err(invalid());
            }
            leading_alias = tokens.is_empty();
            if tokens.last() == Some(&"/") {
                return Err(invalid());
            }
        } else if bytes[position] == b'/' {
            position += 1;
            tokens.push(&text[start..position]);
        } else {
            if matches!(bytes[position], b'+' | b'-') {
                position += 1;
            }
            let mut digits = 0;
            while position < bytes.len() && bytes[position].is_ascii_digit() {
                position += 1;
                digits += 1;
            }
            if bytes.get(position) == Some(&b'.') {
                position += 1;
                while position < bytes.len() && bytes[position].is_ascii_digit() {
                    position += 1;
                    digits += 1;
                }
            }
            if digits == 0 {
                return Err(invalid());
            }
            if matches!(bytes.get(position), Some(b'e' | b'E')) {
                position += 1;
                if matches!(bytes.get(position), Some(b'+' | b'-')) {
                    position += 1;
                }
                let exponent = position;
                while position < bytes.len() && bytes[position].is_ascii_digit() {
                    position += 1;
                }
                if position == exponent {
                    return Err(invalid());
                }
            }
            tokens.push(&text[start..position]);
        }
    }
    if leading_alias && !tokens.is_empty() {
        return Err(invalid());
    }
    if tokens.is_empty() && alias.is_some() {
        tokens.push("1");
    }
    if tokens.is_empty()
        || tokens.len() % 2 == 0
        || tokens
            .iter()
            .enumerate()
            .any(|(i, t)| if i % 2 == 1 { *t != "/" } else { *t == "/" })
    {
        return Err(invalid());
    }
    let scale = if let Some(alias) = alias {
        factor(unit, alias)?
    } else {
        Rational::new(1, 1)?
    };
    Ok((tokens.into_iter().step_by(2).collect(), scale, alias))
}

fn invalid() -> Error {
    Error::Invalid(
        "expected scalar literals, rational quotients and one compatible unit factor".into(),
    )
}

fn factor(unit: &str, alias: &str) -> Result<Rational, Error> {
    let pair = match (unit, alias) {
        ("hz", "Hz" | "hertz")
        | ("cents", "cent" | "cents" | "musical_cent")
        | ("db", "dB" | "decibel" | "decibels")
        | ("volts", "V" | "volt" | "volts")
        | ("seconds", "s" | "second" | "seconds")
        | ("beats", "beat" | "beats")
        | ("radians", "rad" | "radian" | "radians") => (1, 1),
        ("phase", "turn" | "turns" | "cycle" | "cycles") => (1, 1),
        ("phase", "deg" | "degree" | "degrees") => (1, 360),
        ("hz", "kHz" | "kilohertz") => (1000, 1),
        ("hz", "MHz" | "megahertz") => (1000000, 1),
        ("hz", "mHz" | "millihertz")
        | ("volts", "mV" | "millivolt" | "millivolts")
        | ("seconds", "ms" | "millisecond" | "milliseconds") => (1, 1000),
        ("cents", "semitone") => (100, 1),
        ("cents", "octave" | "oct") => (1200, 1),
        _ => return Err(invalid()),
    };
    Rational::new(pair.0, pair.1)
}
