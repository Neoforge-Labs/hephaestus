//! Strict JSON reader shared by canonicalisation (spec 4.3) and the money wire
//! format (spec 3.1). The one place that sees duplicate member names, the
//! written form of numbers and lone surrogates, none of which `serde_json::Value`
//! preserves.
//!
//! Resource bounds: nesting is limited to [`MAX_DEPTH`] and the reader never
//! allocates from a length field, so memory is linear in the input.

use std::cmp::Ordering;

/// Maximum array/object nesting depth. Deeper documents are rejected, so the
/// recursive reader and writer cannot exhaust the stack.
pub(crate) const MAX_DEPTH: usize = 128;

/// Largest integer literal magnitude: 2^53 - 1.
const MAX_SAFE_INTEGER_DIGITS: usize = 16;

#[derive(Debug, Clone, PartialEq)]
pub(crate) enum Json {
    Null,
    Bool(bool),
    /// A number written as an integer literal, magnitude at most 2^53 - 1.
    Int(i64),
    /// A number written with a fraction or an exponent; finite.
    Float(f64),
    Str(String),
    Array(Vec<Json>),
    /// Members sorted by UTF-16 code units of the name; names are unique.
    Object(Vec<(String, Json)>),
}

/// Compares object member names by UTF-16 code units (RFC 8785 3.2.3).
pub(crate) fn utf16_cmp(a: &str, b: &str) -> Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}

/// Parses `text` as one JSON document. The error is a static description; the
/// caller picks the error code.
pub(crate) fn parse(text: &str) -> Result<Json, &'static str> {
    let mut p = Parser { src: text, pos: 0 };
    p.skip_ws();
    let value = p.value(0)?;
    p.skip_ws();
    if p.pos != p.src.len() {
        return Err("trailing characters after JSON value");
    }
    Ok(value)
}

struct Parser<'a> {
    src: &'a str,
    pos: usize,
}

impl Parser<'_> {
    fn peek(&self) -> Option<u8> {
        self.src.as_bytes().get(self.pos).copied()
    }

    fn skip_ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.pos += 1;
        }
    }

    fn eat(&mut self, byte: u8) -> bool {
        if self.peek() == Some(byte) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn literal(&mut self, word: &str, value: Json) -> Result<Json, &'static str> {
        if self
            .src
            .as_bytes()
            .get(self.pos..)
            .is_some_and(|rest| rest.starts_with(word.as_bytes()))
        {
            self.pos += word.len();
            Ok(value)
        } else {
            Err("invalid JSON literal")
        }
    }

    fn value(&mut self, depth: usize) -> Result<Json, &'static str> {
        match self.peek() {
            None => Err("unexpected end of JSON"),
            Some(b'n') => self.literal("null", Json::Null),
            Some(b't') => self.literal("true", Json::Bool(true)),
            Some(b'f') => self.literal("false", Json::Bool(false)),
            Some(b'"') => self.string().map(Json::Str),
            Some(b'[') => self.array(depth),
            Some(b'{') => self.object(depth),
            Some(b'-' | b'0'..=b'9') => self.number(),
            Some(_) => Err("unexpected character in JSON"),
        }
    }

    fn array(&mut self, depth: usize) -> Result<Json, &'static str> {
        if depth >= MAX_DEPTH {
            return Err("JSON nesting is too deep");
        }
        self.pos += 1; // '['
        let mut items = Vec::new();
        self.skip_ws();
        if self.eat(b']') {
            return Ok(Json::Array(items));
        }
        loop {
            self.skip_ws();
            items.push(self.value(depth + 1)?);
            self.skip_ws();
            if self.eat(b',') {
                continue;
            }
            if self.eat(b']') {
                return Ok(Json::Array(items));
            }
            return Err("expected ',' or ']' in array");
        }
    }

    fn object(&mut self, depth: usize) -> Result<Json, &'static str> {
        if depth >= MAX_DEPTH {
            return Err("JSON nesting is too deep");
        }
        self.pos += 1; // '{'
        let mut members: Vec<(String, Json)> = Vec::new();
        self.skip_ws();
        if self.eat(b'}') {
            return Ok(Json::Object(members));
        }
        loop {
            self.skip_ws();
            if self.peek() != Some(b'"') {
                return Err("expected string member name");
            }
            let name = self.string()?;
            self.skip_ws();
            if !self.eat(b':') {
                return Err("expected ':' after member name");
            }
            self.skip_ws();
            members.push((name, self.value(depth + 1)?));
            self.skip_ws();
            if self.eat(b',') {
                continue;
            }
            if self.eat(b'}') {
                break;
            }
            return Err("expected ',' or '}' in object");
        }
        members.sort_by(|a, b| utf16_cmp(&a.0, &b.0));
        if members.windows(2).any(|w| w[0].0 == w[1].0) {
            return Err("duplicate object member name");
        }
        Ok(Json::Object(members))
    }

    fn hex4(&mut self) -> Result<u32, &'static str> {
        let digits = self
            .src
            .as_bytes()
            .get(self.pos..self.pos + 4)
            .ok_or("truncated \\u escape")?;
        let mut v = 0u32;
        for &d in digits {
            let n = (d as char).to_digit(16).ok_or("invalid \\u escape")?;
            v = v * 16 + n;
        }
        self.pos += 4;
        Ok(v)
    }

    fn string(&mut self) -> Result<String, &'static str> {
        self.pos += 1; // opening quote
        let mut out = String::new();
        loop {
            // Copy the run of ordinary bytes up to the next quote, backslash or
            // control character in one step. Those delimiters are ASCII, so the
            // run always ends on a char boundary.
            let start = self.pos;
            while let Some(b) = self.peek() {
                if b == b'"' || b == b'\\' || b < 0x20 {
                    break;
                }
                self.pos += 1;
            }
            out.push_str(self.src.get(start..self.pos).ok_or("invalid UTF-8")?);
            match self.peek() {
                None => return Err("unterminated string"),
                Some(b'"') => {
                    self.pos += 1;
                    return Ok(out);
                }
                Some(b'\\') => {
                    self.pos += 1;
                    self.escape(&mut out)?;
                }
                Some(_) => return Err("unescaped control character in string"),
            }
        }
    }

    fn escape(&mut self, out: &mut String) -> Result<(), &'static str> {
        let c = self.peek().ok_or("unterminated escape")?;
        self.pos += 1;
        match c {
            b'"' => out.push('"'),
            b'\\' => out.push('\\'),
            b'/' => out.push('/'),
            b'b' => out.push('\u{8}'),
            b'f' => out.push('\u{c}'),
            b'n' => out.push('\n'),
            b'r' => out.push('\r'),
            b't' => out.push('\t'),
            b'u' => {
                let first = self.hex4()?;
                let code = match first {
                    0xD800..=0xDBFF => {
                        if !(self.eat(b'\\') && self.eat(b'u')) {
                            return Err("lone high surrogate");
                        }
                        let second = self.hex4()?;
                        if !(0xDC00..=0xDFFF).contains(&second) {
                            return Err("lone high surrogate");
                        }
                        0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
                    }
                    0xDC00..=0xDFFF => return Err("lone low surrogate"),
                    other => other,
                };
                out.push(char::from_u32(code).ok_or("invalid code point")?);
            }
            _ => return Err("invalid escape sequence"),
        }
        Ok(())
    }

    fn digits(&mut self) -> usize {
        let start = self.pos;
        while matches!(self.peek(), Some(b'0'..=b'9')) {
            self.pos += 1;
        }
        self.pos - start
    }

    /// Spec 4.3: how a number is written decides how it is read. An integer
    /// literal (no fraction, no exponent) must fit 2^53 - 1; anything else is an
    /// IEEE-754 double that must be finite.
    fn number(&mut self) -> Result<Json, &'static str> {
        let start = self.pos;
        let negative = self.eat(b'-');
        let int_start = self.pos;
        match self.peek() {
            Some(b'0') => self.pos += 1,
            Some(b'1'..=b'9') => {
                self.digits();
            }
            _ => return Err("invalid number"),
        }
        let int_len = self.pos - int_start;
        let mut is_integer = true;
        if self.eat(b'.') {
            is_integer = false;
            if self.digits() == 0 {
                return Err("invalid number: no digits after '.'");
            }
        }
        if matches!(self.peek(), Some(b'e' | b'E')) {
            is_integer = false;
            self.pos += 1;
            if matches!(self.peek(), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            if self.digits() == 0 {
                return Err("invalid number: no digits in exponent");
            }
        }
        let text = self.src.get(start..self.pos).ok_or("invalid UTF-8")?;
        if is_integer {
            // No leading zeros, so the digit count is exact.
            if int_len > MAX_SAFE_INTEGER_DIGITS {
                return Err("integer literal exceeds 2^53-1");
            }
            let magnitude: i64 = text
                .trim_start_matches('-')
                .parse()
                .map_err(|_| "invalid integer literal")?;
            if magnitude > 9_007_199_254_740_991 {
                return Err("integer literal exceeds 2^53-1");
            }
            Ok(Json::Int(if negative { -magnitude } else { magnitude }))
        } else {
            let f: f64 = text.parse().map_err(|_| "invalid number")?;
            if f.is_finite() {
                Ok(Json::Float(f))
            } else {
                Err("number is not a finite double")
            }
        }
    }
}
