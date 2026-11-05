use super::{invalid, Money};
use crate::CoreError;

/// Largest-remainder allocation (spec 3.7). Intermediates are `u128`: the
/// product of an `i64` magnitude and a `u64` ratio always fits.
pub(super) fn allocate(money: &Money, ratios: &[u64]) -> Result<Vec<Money>, CoreError> {
    let total = ratios
        .iter()
        .try_fold(0u128, |acc, &r| acc.checked_add(u128::from(r)))
        .ok_or_else(|| invalid("ratios sum too large"))?;
    if ratios.is_empty() || total == 0 {
        return Err(invalid(
            "ratios must be non-empty with at least one non-zero",
        ));
    }

    let amount = u128::from(money.minor.unsigned_abs());
    let mut shares: Vec<u128> = Vec::with_capacity(ratios.len());
    let mut remainders: Vec<(u128, usize)> = Vec::with_capacity(ratios.len());
    for (i, &r) in ratios.iter().enumerate() {
        let exact = amount * u128::from(r);
        shares.push(exact / total);
        remainders.push((exact % total, i));
    }

    let allocated: u128 = shares.iter().sum();
    let leftover = usize::try_from(amount - allocated)
        .map_err(|_| invalid("allocation leftover too large"))?;
    // Largest remainder first; ties go to the lower index.
    remainders.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    for &(_, i) in remainders.iter().take(leftover) {
        shares[i] += 1;
    }

    shares
        .into_iter()
        .map(|share| {
            let signed = i128::try_from(share).map_err(|_| invalid("part too large"))?;
            let signed = if money.minor < 0 { -signed } else { signed };
            let minor = i64::try_from(signed).map_err(|_| invalid("part too large"))?;
            Ok(Money::new(minor, money.currency))
        })
        .collect()
}
