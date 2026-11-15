//! The portable pitch grammar, without Python syntax or evaluation.

use crate::error::Error;
use crate::number::Number;

pub const MAX_EXPRESSION_LENGTH: usize = 4096;
pub const MAX_EXPRESSION_DEPTH: usize = 64;
pub const MAX_POWER: i64 = 1024;

pub fn evaluate(text: &str) -> Result<Number, Error> {
    if text.chars().count() > MAX_EXPRESSION_LENGTH {
        return Err(Error::Limit("expression length"));
    }
    let mut parser = Parser {
        text,
        position: 0,
        parentheses: 0,
    };
    let tree = parser.division(0)?;
    parser.space();
    if parser.position != text.len() {
        return Err(Error::Invalid("unexpected pitch expression token".into()));
    }
    tree.evaluate(0)
}

enum Node {
    Literal(String),
    Sign(bool, Box<Node>),
    Division(Box<Node>, Box<Node>),
    Power(Box<Node>, Box<Node>),
}

impl Node {
    fn evaluate(&self, depth: usize) -> Result<Number, Error> {
        if depth > MAX_EXPRESSION_DEPTH {
            return Err(Error::Limit("expression depth"));
        }
        match self {
            Self::Literal(text) => decimal(text, false),
            Self::Sign(negative, inner) => {
                if let Self::Literal(text) = inner.as_ref() {
                    if depth + 1 > MAX_EXPRESSION_DEPTH {
                        return Err(Error::Limit("expression depth"));
                    }
                    return decimal(text, *negative);
                }
                let value = inner.evaluate(depth + 1)?;
                if *negative {
                    value.checked_neg()
                } else {
                    Ok(value)
                }
            }
            Self::Division(a, b) => a.evaluate(depth + 1)?.checked_div(b.evaluate(depth + 1)?),
            Self::Power(a, b) => {
                let base = a.evaluate(depth + 1)?;
                let exponent = b.evaluate(depth + 1)?;
                if exponent.as_f64().abs() > MAX_POWER as f64 {
                    return Err(Error::Limit("power"));
                }
                base.checked_pow(exponent)
            }
        }
    }
}

struct Parser<'a> {
    text: &'a str,
    position: usize,
    parentheses: usize,
}

impl Parser<'_> {
    fn space(&mut self) {
        while let Some(c) = self.text[self.position..].chars().next() {
            if !c.is_whitespace() {
                break;
            }
            self.position += c.len_utf8();
        }
    }

    fn take(&mut self, token: u8) -> bool {
        self.space();
        if self.text.as_bytes().get(self.position) == Some(&token) {
            self.position += 1;
            true
        } else {
            false
        }
    }

    fn division(&mut self, depth: usize) -> Result<Node, Error> {
        let mut value = self.signed(depth)?;
        while self.take(b'/') {
            value = Node::Division(Box::new(value), Box::new(self.signed(depth)?));
        }
        Ok(value)
    }

    fn signed(&mut self, depth: usize) -> Result<Node, Error> {
        if depth > MAX_EXPRESSION_DEPTH {
            return Err(Error::Limit("expression depth"));
        }
        if self.take(b'+') {
            return Ok(Node::Sign(false, Box::new(self.signed(depth + 1)?)));
        }
        if self.take(b'-') {
            return Ok(Node::Sign(true, Box::new(self.signed(depth + 1)?)));
        }
        let value = self.atom(depth)?;
        if self.take(b'^') {
            Ok(Node::Power(
                Box::new(value),
                Box::new(self.signed(depth + 1)?),
            ))
        } else {
            Ok(value)
        }
    }

    fn atom(&mut self, depth: usize) -> Result<Node, Error> {
        if self.take(b'(') {
            self.parentheses += 1;
            if self.parentheses > MAX_EXPRESSION_DEPTH {
                return Err(Error::Limit("parenthesis depth"));
            }
            let value = self.division(depth)?;
            if !self.take(b')') {
                return Err(Error::Invalid("missing closing parenthesis".into()));
            }
            self.parentheses -= 1;
            return Ok(value);
        }
        self.space();
        let start = self.position;
        let mut digits = 0;
        while self
            .text
            .as_bytes()
            .get(self.position)
            .is_some_and(u8::is_ascii_digit)
        {
            self.position += 1;
            digits += 1;
        }
        if self.text.as_bytes().get(self.position) == Some(&b'.') {
            self.position += 1;
            while self
                .text
                .as_bytes()
                .get(self.position)
                .is_some_and(u8::is_ascii_digit)
            {
                self.position += 1;
                digits += 1;
            }
        }
        if digits == 0 {
            return Err(Error::Invalid("expected a numeric literal".into()));
        }
        if matches!(self.text.as_bytes().get(self.position), Some(b'e' | b'E')) {
            self.position += 1;
            if matches!(self.text.as_bytes().get(self.position), Some(b'+' | b'-')) {
                self.position += 1;
            }
            let exponent_start = self.position;
            while self
                .text
                .as_bytes()
                .get(self.position)
                .is_some_and(u8::is_ascii_digit)
            {
                self.position += 1;
            }
            if self.position == exponent_start {
                return Err(Error::Invalid("expected a scientific exponent".into()));
            }
        }
        Ok(Node::Literal(self.text[start..self.position].to_owned()))
    }
}

fn decimal(text: &str, negative: bool) -> Result<Number, Error> {
    let (mantissa, exponent) = match text.split_once(['e', 'E']) {
        Some((mantissa, exponent)) => (
            mantissa,
            exponent
                .parse::<i64>()
                .map_err(|_| Error::ArithmeticRange)?,
        ),
        None => (text, 0),
    };
    if exponent.unsigned_abs() > 4096 {
        return Err(Error::Limit("scientific exponent"));
    }
    let fractional = mantissa.split_once('.').map_or(0, |(_, tail)| tail.len());
    let mut digits = mantissa.replace('.', "");
    let mut power = exponent - i64::try_from(fractional).map_err(|_| Error::ArithmeticRange)?;
    while digits.ends_with('0') && digits.len() > 1 {
        digits.pop();
        power += 1;
    }
    let mut numerator = digits.parse::<u64>().map_err(|_| Error::ArithmeticRange)?;
    if numerator == 0 {
        return Number::exact(0, 1);
    }
    let mut denominator = 1_u64;
    if power >= 0 {
        for _ in 0..power {
            numerator = numerator.checked_mul(10).ok_or(Error::ArithmeticRange)?;
        }
    } else {
        // Cancel factors before building a bounded decimal denominator.
        for factor in [2, 5] {
            for _ in 0..-power {
                if numerator % factor == 0 {
                    numerator /= factor;
                } else {
                    denominator = denominator
                        .checked_mul(factor)
                        .ok_or(Error::ArithmeticRange)?;
                }
            }
        }
    }
    let signed = if negative && numerator == 1_u64 << 63 {
        i64::MIN
    } else {
        let magnitude = i64::try_from(numerator).map_err(|_| Error::ArithmeticRange)?;
        if negative { -magnitude } else { magnitude }
    };
    Number::exact(
        signed,
        i64::try_from(denominator).map_err(|_| Error::ArithmeticRange)?,
    )
}
