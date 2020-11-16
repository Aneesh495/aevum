//! Double-precision period life-table arithmetic. Each row uses seven f64 columns:
//! q, l, d, L, T, e, a. A NaN e denotes a structurally extinct synthetic cohort.

#[derive(Debug, PartialEq)]
pub enum TableError {
    Shape = 1,
    InvalidInput = 2,
    InvalidTail = 3,
    ImpossibleProbability = 4,
    Overflow = 5,
}

pub const COLUMNS: usize = 7;
const MAX_AGES: usize = 151;

/// Width zero identifies the final open interval. A negative a in closed intervals
/// selects a constant force of mortality for that interval.
pub fn calculate(
    widths: &[u16],
    rates: &[f64],
    assumptions: &[f64],
    radix: f64,
    output: &mut [[f64; COLUMNS]],
) -> Result<(), TableError> {
    let size = widths.len();
    if !(1..=MAX_AGES).contains(&size)
        || rates.len() != size
        || assumptions.len() != size
        || output.len() != size
        || widths[size - 1] != 0
        || widths[..size - 1].contains(&0)
    {
        return Err(TableError::Shape);
    }
    if !radix.is_finite() || radix <= 0.0 || widths.iter().map(|&n| u32::from(n)).sum::<u32>() > 150
    {
        return Err(TableError::InvalidInput);
    }

    let mut alive = radix;
    for (((&width, &rate), &ax), row) in widths
        .iter()
        .zip(rates)
        .zip(assumptions)
        .zip(output.iter_mut())
    {
        let n = f64::from(width);
        if !rate.is_finite()
            || rate < 0.0
            || !ax.is_finite()
            || (width != 0 && ax != -1.0 && !(0.0..=n).contains(&ax))
        {
            return Err(TableError::InvalidInput);
        }

        let (q, survived, lived, ax) = if width == 0 {
            if rate == 0.0 || !rate.recip().is_finite() {
                return Err(TableError::InvalidTail);
            }
            (1.0, 0.0, alive / rate, rate.recip())
        } else if ax == -1.0 {
            let force = n * rate;
            let q = -(-force).exp_m1();
            let mean_lifetime = if force == 0.0 { n } else { q / rate };
            let mean_age_at_death = if force < 1e-4 {
                n * (0.5 - force / 12.0)
            } else {
                rate.recip() - n / force.exp_m1()
            };
            (
                q,
                alive * (-force).exp(),
                alive * mean_lifetime,
                mean_age_at_death,
            )
        } else {
            // This rearrangement keeps the probability finite for extreme rates.
            let q = if rate <= 1.0 {
                n * rate / (1.0 + (n - ax) * rate)
            } else {
                n / (rate.recip() + n - ax)
            };
            if !(0.0..=1.0).contains(&q) {
                return Err(TableError::ImpossibleProbability);
            }
            let survived = alive * (1.0 - q);
            (q, survived, n * survived + ax * (alive * q), ax)
        };

        if !lived.is_finite() {
            return Err(TableError::Overflow);
        }
        *row = [q, alive, alive * q, lived, 0.0, 0.0, ax];
        alive = survived;
    }

    let mut remaining = 0.0;
    for row in output.iter_mut().rev() {
        remaining += row[3];
        if !remaining.is_finite() {
            return Err(TableError::Overflow);
        }
        row[4] = remaining;
        row[5] = if row[1] == 0.0 {
            f64::NAN
        } else {
            remaining / row[1]
        };
        if row[5].is_infinite() {
            return Err(TableError::Overflow);
        }
    }
    Ok(())
}

/// # Safety
/// Inputs must point to initialized arrays of size n. Output must be writable for
/// n * COLUMNS values and must not alias any input. The caller owns all buffers.
#[no_mangle]
pub unsafe extern "C" fn aevum_table(
    n: usize,
    widths: *const u16,
    rates: *const f64,
    assumptions: *const f64,
    radix: f64,
    output: *mut [f64; COLUMNS],
) -> i32 {
    if !(1..=MAX_AGES).contains(&n)
        || widths.is_null()
        || rates.is_null()
        || assumptions.is_null()
        || output.is_null()
    {
        return TableError::Shape as i32;
    }
    let result = calculate(
        unsafe { std::slice::from_raw_parts(widths, n) },
        unsafe { std::slice::from_raw_parts(rates, n) },
        unsafe { std::slice::from_raw_parts(assumptions, n) },
        radix,
        unsafe { std::slice::from_raw_parts_mut(output, n) },
    );
    result.map_or_else(|error| error as i32, |()| 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn constant_force_reproduces_inverse_hazard() {
        let mut rows = [[0.0; COLUMNS]; 3];
        calculate(&[1, 4, 0], &[0.04; 3], &[-1.0; 3], 100_000.0, &mut rows).unwrap();
        for row in rows {
            assert!((row[5] - 25.0).abs() < 1e-12);
        }
    }

    #[test]
    fn rejects_inconsistent_ax() {
        let mut rows = [[0.0; COLUMNS]; 2];
        assert_eq!(
            calculate(&[5, 0], &[0.6, 0.1], &[2.5, 0.0], 1.0, &mut rows),
            Err(TableError::ImpossibleProbability)
        );
    }
}
