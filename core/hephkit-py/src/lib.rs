//! PyO3 glue for `hephkit-core`, exposed to Python as `hephkit._core`.
//!
//! This crate converts types and maps errors and nothing else: every parse
//! rule, rounding decision and signature comparison lives in the core
//! (CLAUDE.md rule 3). Nothing here panics on input; every fallible step
//! returns a Python exception.
//!
//! Error mapping follows the rule documented on `CoreError`: the variant
//! selects the exception class and the registry code is exposed verbatim as
//! `.code`.

use hephkit_core::{CoreError, Currency, Money, Rounding};
use pyo3::create_exception;
use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;

create_exception!(hephkit.money, MoneyError, PyValueError);
create_exception!(hephkit.signatures, SignatureError, PyValueError);
create_exception!(hephkit.hashing, HashingError, PyValueError);

/// Registry code for an integer the Python layer cannot even hand to the core
/// (outside the core's 64-bit range). Same code the core uses for every other
/// malformed money input.
const MONEY_INVALID: &str = "HEPH-MONEY-422";

fn with_code(py: Python<'_>, err: PyErr, code: &str) -> PyErr {
    // `setattr` on a plain exception instance cannot realistically fail; if it
    // does, the exception is still raised, only without `.code`.
    let _ = err.value(py).setattr("code", code);
    err
}

fn map_err(py: Python<'_>, err: CoreError) -> PyErr {
    let text = err.to_string();
    match err {
        CoreError::Money { code, .. } => with_code(py, MoneyError::new_err(text), code),
        CoreError::Signature { code, .. } => with_code(py, SignatureError::new_err(text), code),
        CoreError::Hashing { code, .. } => with_code(py, HashingError::new_err(text), code),
    }
}

fn money_invalid(py: Python<'_>, message: &str) -> PyErr {
    with_code(
        py,
        MoneyError::new_err(format!("{MONEY_INVALID}: {message}")),
        MONEY_INVALID,
    )
}

fn parse_rounding(name: &str) -> PyResult<Rounding> {
    match name {
        "reject" => Ok(Rounding::Reject),
        "half_up" => Ok(Rounding::HalfUp),
        "half_even" => Ok(Rounding::HalfEven),
        "down" => Ok(Rounding::Down),
        _ => Err(PyValueError::new_err(
            "rounding must be one of 'reject', 'half_up', 'half_even', 'down'",
        )),
    }
}

/// `minor` as i64. A Python int outside i64 is a money error, not an
/// `OverflowError`; any other type problem stays a `TypeError`.
fn minor_arg(py: Python<'_>, minor: &Bound<'_, PyAny>) -> PyResult<i64> {
    minor.extract::<i64>().map_err(|e| {
        if e.is_instance_of::<PyOverflowError>(py) {
            money_invalid(py, "minor units outside the signed 64-bit range")
        } else {
            e
        }
    })
}

fn money(py: Python<'_>, minor: &Bound<'_, PyAny>, currency: &str) -> PyResult<Money> {
    let minor = minor_arg(py, minor)?;
    let currency = Currency::from_code(currency).map_err(|e| map_err(py, e))?;
    Ok(Money::new(minor, currency))
}

fn out(m: &Money) -> (i64, String) {
    (
        m.minor,
        String::from_utf8_lossy(&m.currency.code).into_owned(),
    )
}

#[pyfunction]
fn money_check(
    py: Python<'_>,
    minor: &Bound<'_, PyAny>,
    currency: &str,
) -> PyResult<(i64, String)> {
    Ok(out(&money(py, minor, currency)?))
}

#[pyfunction]
fn money_parse(
    py: Python<'_>,
    amount: &str,
    currency: &str,
    rounding: &str,
) -> PyResult<(i64, String)> {
    let rounding = parse_rounding(rounding)?;
    let currency = Currency::from_code(currency).map_err(|e| map_err(py, e))?;
    let m = Money::parse(amount, currency, rounding).map_err(|e| map_err(py, e))?;
    Ok(out(&m))
}

#[pyfunction]
fn money_to_decimal(py: Python<'_>, minor: &Bound<'_, PyAny>, currency: &str) -> PyResult<String> {
    Ok(money(py, minor, currency)?.to_decimal_string())
}

#[pyfunction]
fn money_add(
    py: Python<'_>,
    a_minor: &Bound<'_, PyAny>,
    a_currency: &str,
    b_minor: &Bound<'_, PyAny>,
    b_currency: &str,
) -> PyResult<(i64, String)> {
    let a = money(py, a_minor, a_currency)?;
    let b = money(py, b_minor, b_currency)?;
    Ok(out(&a.checked_add(&b).map_err(|e| map_err(py, e))?))
}

#[pyfunction]
fn money_sub(
    py: Python<'_>,
    a_minor: &Bound<'_, PyAny>,
    a_currency: &str,
    b_minor: &Bound<'_, PyAny>,
    b_currency: &str,
) -> PyResult<(i64, String)> {
    let a = money(py, a_minor, a_currency)?;
    let b = money(py, b_minor, b_currency)?;
    Ok(out(&a.checked_sub(&b).map_err(|e| map_err(py, e))?))
}

#[pyfunction]
fn money_neg(py: Python<'_>, minor: &Bound<'_, PyAny>, currency: &str) -> PyResult<(i64, String)> {
    let m = money(py, minor, currency)?;
    Ok(out(&m.checked_neg().map_err(|e| map_err(py, e))?))
}

#[pyfunction]
fn money_allocate(
    py: Python<'_>,
    minor: &Bound<'_, PyAny>,
    currency: &str,
    ratios: Vec<Bound<'_, PyAny>>,
) -> PyResult<Vec<(i64, String)>> {
    let m = money(py, minor, currency)?;
    let mut parsed = Vec::with_capacity(ratios.len());
    for ratio in &ratios {
        let value = ratio.extract::<u64>().map_err(|e| {
            if e.is_instance_of::<PyOverflowError>(py) {
                money_invalid(py, "ratio outside the unsigned 64-bit range")
            } else {
                e
            }
        })?;
        parsed.push(value);
    }
    let parts = m.allocate(&parsed).map_err(|e| map_err(py, e))?;
    Ok(parts.iter().map(out).collect())
}

#[pyfunction]
fn money_from_wire(py: Python<'_>, json: &str) -> PyResult<(i64, String)> {
    Ok(out(
        &Money::from_wire_json(json).map_err(|e| map_err(py, e))?
    ))
}

#[pyfunction]
fn money_to_wire(py: Python<'_>, minor: &Bound<'_, PyAny>, currency: &str) -> PyResult<String> {
    Ok(money(py, minor, currency)?.to_wire_json())
}

#[pyfunction]
fn canonical_json(py: Python<'_>, json: &str) -> PyResult<String> {
    hephkit_core::canonical_json(json).map_err(|e| map_err(py, e))
}

#[pyfunction]
fn content_hash_json(py: Python<'_>, json: &str) -> PyResult<String> {
    hephkit_core::content_hash_json(json).map_err(|e| map_err(py, e))
}

#[pyfunction]
fn content_hash_bytes(data: &[u8]) -> String {
    hephkit_core::content_hash_bytes(data)
}

#[pyfunction]
fn new_uuid7() -> String {
    hephkit_core::new_uuid7()
}

#[pyfunction]
fn sign(
    py: Python<'_>,
    secret: &str,
    msg_id: &str,
    timestamp: i64,
    payload: &[u8],
) -> PyResult<String> {
    hephkit_core::sign(secret, msg_id, timestamp, payload).map_err(|e| map_err(py, e))
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn verify(
    py: Python<'_>,
    secret: &str,
    msg_id: &str,
    timestamp_header: &str,
    signature_header: &str,
    payload: &[u8],
    now: i64,
    tolerance: i64,
) -> PyResult<()> {
    hephkit_core::verify(
        secret,
        msg_id,
        timestamp_header,
        signature_header,
        payload,
        now,
        tolerance,
    )
    .map_err(|e| map_err(py, e))
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("MoneyError", py.get_type::<MoneyError>())?;
    m.add("SignatureError", py.get_type::<SignatureError>())?;
    m.add("HashingError", py.get_type::<HashingError>())?;
    m.add(
        "DEFAULT_TOLERANCE_SECS",
        hephkit_core::DEFAULT_TOLERANCE_SECS,
    )?;
    m.add_function(wrap_pyfunction!(money_check, m)?)?;
    m.add_function(wrap_pyfunction!(money_parse, m)?)?;
    m.add_function(wrap_pyfunction!(money_to_decimal, m)?)?;
    m.add_function(wrap_pyfunction!(money_add, m)?)?;
    m.add_function(wrap_pyfunction!(money_sub, m)?)?;
    m.add_function(wrap_pyfunction!(money_neg, m)?)?;
    m.add_function(wrap_pyfunction!(money_allocate, m)?)?;
    m.add_function(wrap_pyfunction!(money_from_wire, m)?)?;
    m.add_function(wrap_pyfunction!(money_to_wire, m)?)?;
    m.add_function(wrap_pyfunction!(canonical_json, m)?)?;
    m.add_function(wrap_pyfunction!(content_hash_json, m)?)?;
    m.add_function(wrap_pyfunction!(content_hash_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(new_uuid7, m)?)?;
    m.add_function(wrap_pyfunction!(sign, m)?)?;
    m.add_function(wrap_pyfunction!(verify, m)?)?;
    Ok(())
}
