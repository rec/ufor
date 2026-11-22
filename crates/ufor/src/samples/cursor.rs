//! Sample traversal in native asset frames, independent of decoded audio.

use super::playback::{Direction, LoopMode, Playback, Slice};
use crate::error::Error;
use crate::number::{Rational, round_binary_ratio};

type Selection = (i64, i64, bool, Option<(i64, i64, i64, bool)>);

/// Return the advances on either side of a release inside an output frame.
///
/// Each part is rounded once, from the exact binary64 step times its fraction.
pub fn split_step(step: f64, fraction: Rational) -> Result<(f64, f64), Error> {
    let numerator = fraction.numerator();
    let denominator = fraction.denominator();
    if !step.is_finite() || step <= 0.0 || numerator <= 0 || numerator >= denominator {
        return Err(Error::ArithmeticRange);
    }
    let bits = step.to_bits();
    let encoded_exponent = ((bits >> 52) & 0x7ff) as i32;
    let mut significand = (bits & ((1 << 52) - 1)) as u128;
    let exponent = if encoded_exponent == 0 {
        -1074
    } else {
        significand |= 1 << 52;
        encoded_exponent - 1023 - 52
    };
    let scaled =
        |part| round_binary_ratio(significand * part as u128, denominator as u128, exponent);
    Ok((scaled(numerator), scaled(denominator - numerator)))
}

/// Copyable continuation state in native asset frames and output-frame time.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CursorState {
    pub index: i64,
    pub position: f64,
    pub error: f64,
    pub direction: i64,
    pub looping: bool,
    pub overlap: bool,
    pub released: bool,
    pub exhausted: Option<i64>,
    pub repeats_remaining: Option<u64>,
    pub plays_remaining: u64,
    pub end_fade_at: Option<i64>,
}

/// Prepared cursor configuration and its current state.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Cursor {
    selection: Selection,
    rate: f64,
    end_fade_frames: f64,
    state: CursorState,
}

/// One settled cursor observation, reusable across all source channels.
#[derive(Clone, Copy, Debug)]
pub struct SampleRead {
    first: Tap,
    interpolation: Option<(Option<Tap>, f64)>,
}

impl SampleRead {
    /// Fetch decoded values by native frame index and apply the read weights.
    #[inline]
    pub fn sample(&self, mut at: impl FnMut(i64) -> f64) -> f64 {
        let first = self.first.sample(&mut at);
        if let Some((following, fraction)) = self.interpolation {
            let last = following.map_or(first, |tap| tap.sample(&mut at));
            first + fraction * (last - first)
        } else {
            first
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct Tap {
    index: i64,
    overlap: Option<(i64, f64)>,
}

impl Tap {
    fn sample(self, at: &mut impl FnMut(i64) -> f64) -> f64 {
        let first = at(self.index);
        self.overlap.map_or(first, |(incoming, weight)| {
            (1.0 - weight) * first + weight * at(incoming)
        })
    }
}

impl Cursor {
    pub fn new(
        slice: &Slice,
        playback: Playback,
        available_frames: i64,
        rate: f64,
        additional_plays: u64,
        end_fade_seconds: f64,
    ) -> Result<Self, Error> {
        slice.validate_playback(playback, available_frames, additional_plays)?;
        let end_fade_frames = end_fade_seconds * rate;
        if !rate.is_finite() || rate <= 0.0 || !end_fade_frames.is_finite() || end_fade_frames < 0.0
        {
            return Err(Error::Invalid("Invalid sample rate or end fade".into()));
        }
        let backward = playback.direction == Direction::Backward;
        let loop_settings = slice.loop_settings();
        Ok(Self {
            selection: (
                slice.start_frame(),
                slice.end_frame(),
                playback.direction == Direction::Mirror,
                loop_settings.map(|settings| {
                    (
                        settings.start_frame(),
                        settings.end_frame(),
                        settings.crossfade_frames(),
                        settings.mode() == LoopMode::UntilRelease,
                    )
                }),
            ),
            rate,
            end_fade_frames,
            state: CursorState {
                index: if backward {
                    slice.end_frame() - 1
                } else {
                    slice.start_frame()
                },
                position: 0.0,
                error: 0.0,
                direction: if backward { -1 } else { 1 },
                looping: loop_settings.is_some(),
                overlap: false,
                released: false,
                exhausted: None,
                repeats_remaining: loop_settings.and_then(|settings| settings.repeat_count()),
                plays_remaining: additional_plays,
                end_fade_at: None,
            },
        })
    }

    #[inline]
    pub fn rate(&self) -> f64 {
        self.rate
    }

    #[inline]
    pub fn state(&self) -> &CursorState {
        &self.state
    }

    /// Restore a continuation, retaining any pending decision at a loop boundary.
    pub fn resume(mut self, state: CursorState, frame: i64) -> Result<Self, Error> {
        let (start, end, mirror, loop_) = self.selection;
        let valid_overlap = loop_.is_some_and(|(a, b, width, _)| {
            width >= 2
                && !mirror
                && if state.direction == 1 {
                    (b - width..=b).contains(&state.index)
                } else {
                    (a - 1..a + width).contains(&state.index)
                }
        });
        if frame < 0
            || state.end_fade_at.is_some_and(|at| at < 0 || at > frame)
            || (state.looping && loop_.is_none())
            || (state.overlap && !valid_overlap)
            || ![-1, 1].contains(&state.direction)
            || !(start - 1..=end).contains(&state.index)
            || !(0.0..self.rate).contains(&state.position)
            || !state.error.is_finite()
            || (state.plays_remaining > 0 && loop_.is_some())
        {
            return Err(Error::Invalid(
                "Invalid native sample settings, state, or buffers".into(),
            ));
        }
        self.state = state;
        let mut settled = self;
        settled.settle(frame);
        if settled.state.exhausted.is_none()
            && settled.state.direction * (settled.boundary().0 - settled.state.index) < 0
        {
            return Err(Error::Invalid(
                "Invalid native sample cursor direction".into(),
            ));
        }
        Ok(self)
    }

    /// Apply a native-frame start offset and mark exhaustion when it leaves the slice.
    pub fn offset_start(&mut self, offset: i64, frame: i64) -> Result<bool, Error> {
        self.state.index = self
            .state
            .index
            .checked_add(offset)
            .ok_or(Error::ArithmeticRange)?;
        let inside = (self.selection.0..self.selection.1).contains(&self.state.index);
        if !inside {
            self.state.exhausted = Some(frame);
        }
        Ok(inside)
    }

    /// The next interpolation cursor, with no change to pending state on this cursor.
    pub fn following(mut self, frame: i64) -> Self {
        if self.state.position != 0.0 {
            self.state.index += self.state.direction;
            self.state.position = 0.0;
            self.settle(frame);
        }
        self
    }

    /// Plan a read after settling the current frame.
    ///
    /// Lookahead uses a copy, so a pending release can still cancel the next
    /// wrap or turn. If lookahead exhausts the source, hold the current value.
    pub fn read_plan(&self, frame: i64) -> Option<SampleRead> {
        let first = self.tap()?;
        let interpolation = (self.state.position != 0.0).then(|| {
            let following = self.following(frame).tap();
            (following, self.state.position / self.rate)
        });
        Some(SampleRead {
            first,
            interpolation,
        })
    }

    fn tap(&self) -> Option<Tap> {
        if self.state.exhausted.is_some()
            || !(self.selection.0..self.selection.1).contains(&self.state.index)
        {
            return None;
        }
        Some(Tap {
            index: self.state.index,
            overlap: self.overlap_tap(),
        })
    }

    /// Bound a control batch before a predicted exhaustion or end fade.
    ///
    /// The caller limits the request to the next release and supplies an upper
    /// bound on the cursor step. A zero result means the current frame is
    /// already silent. An uncertain final frame is processed by itself.
    pub fn active_prefix(
        mut self,
        frame: i64,
        release_now: bool,
        maximum_step: f64,
        requested: usize,
    ) -> usize {
        if release_now {
            self.release();
        }
        self.settle(frame);
        if self.state.exhausted.is_some() {
            return 0;
        }
        let mut frames = requested;
        if self.end_fade_frames > 0.0 {
            if let Some(at) = self.state.end_fade_at {
                let elapsed = (frame - at) as f64;
                let remaining = (self.end_fade_frames.ceil() - elapsed).max(0.0);
                frames = frames.min(remaining as usize);
            }
        }
        if let Some(distance) = self.remaining() {
            if !maximum_step.is_finite() || maximum_step <= 0.0 {
                return frames.min(1);
            }
            let remaining = distance * self.rate + self.state.error.min(0.0);
            let horizon = remaining / maximum_step;
            // A whole-frame endpoint belongs to the next batch.
            let known = if horizon > 0.0 {
                f64::from_bits(horizon.to_bits() - 1) as usize
            } else {
                0
            };
            frames = frames.min(known.max(1));
        }
        frames
    }

    fn remaining(&self) -> Option<f64> {
        let (start, end, mirror, loop_) = self.selection;
        let mut distance = if self.state.direction == 1 {
            end - self.state.index
        } else {
            self.state.index - start + 1
        } as f64;
        if let Some((a, b, overlap, _)) = loop_.filter(|_| self.state.looping || self.state.overlap)
        {
            let repeats = if self.state.looping {
                self.state.repeats_remaining?
            } else {
                0
            };
            let length = b - a;
            if mirror && repeats > 0 {
                let boundary = if self.state.direction == 1 { b - 1 } else { a };
                let direction = self.state.direction * if repeats % 2 == 0 { 1 } else { -1 };
                let last = if direction == -1 { b - 1 } else { a };
                let tail = if direction == 1 {
                    end - last
                } else {
                    last - start + 1
                };
                distance = (self.state.direction * (boundary - self.state.index)) as f64
                    + (repeats - 1) as f64 * (length - 1) as f64
                    + tail as f64;
            } else if !mirror {
                distance +=
                    (repeats as f64 + f64::from(self.state.overlap)) * (length - overlap) as f64;
            }
        } else if mirror && loop_.is_none() && self.state.direction == 1 {
            distance += (end - start - 1) as f64;
        }
        let length = end - start;
        distance += self.state.plays_remaining as f64
            * if mirror {
                2.0 * length as f64 - 1.0
            } else {
                length as f64
            };
        Some(distance - self.state.position / self.rate)
    }

    pub fn end_gain(&mut self, frame: i64, step: f64) -> f64 {
        if self.end_fade_frames == 0.0 {
            return 1.0;
        }
        if self.state.end_fade_at.is_none()
            && self
                .remaining()
                .is_some_and(|d| d * self.rate / step <= self.end_fade_frames)
        {
            self.state.end_fade_at = Some(frame);
        }
        let gain = self.state.end_fade_at.map_or(1.0, |at| {
            (1.0 - (frame - at) as f64 / self.end_fade_frames).max(0.0)
        });
        if gain == 0.0 {
            self.state.exhausted = Some(frame);
        }
        gain
    }

    pub fn release(&mut self) {
        self.state.released = true;
        if self.selection.3.is_some_and(|l| l.3) {
            self.state.looping = false;
        }
    }

    fn take_repeat(&mut self) -> bool {
        if let Some(remaining) = &mut self.state.repeats_remaining {
            if *remaining == 0 {
                self.state.looping = false;
                return false;
            }
            *remaining -= 1;
        }
        true
    }

    pub fn settle(&mut self, frame: i64) {
        if self.state.exhausted.is_some() {
            return;
        }
        let (start, end, mirror, loop_) = self.selection;
        if let Some((a, b, overlap, _)) = loop_ {
            if self.state.overlap {
                if self.state.direction == 1 && self.state.index == b {
                    self.state.index = a + overlap;
                    self.state.overlap = false;
                } else if self.state.direction == -1 && self.state.index == a - 1 {
                    self.state.index = b - 1 - overlap;
                    self.state.overlap = false;
                }
            } else if self.state.looping {
                if mirror {
                    if self.state.direction == 1 && self.state.index == b - 1 && self.take_repeat()
                    {
                        self.state.direction = -1;
                    } else if self.state.direction == -1
                        && self.state.index == a
                        && self.take_repeat()
                    {
                        self.state.direction = 1;
                    }
                } else if overlap != 0 {
                    self.state.overlap = self.state.index
                        == if self.state.direction == 1 {
                            b - overlap
                        } else {
                            a + overlap - 1
                        }
                        && self.take_repeat();
                } else if self.state.direction == 1 && self.state.index == b && self.take_repeat() {
                    self.state.index = a;
                } else if self.state.direction == -1
                    && self.state.index == a - 1
                    && self.take_repeat()
                {
                    self.state.index = b - 1;
                }
            }
        } else if mirror
            && self.state.direction == 1
            && self.state.index == end - 1
            && end - start > 1
        {
            self.state.direction = -1;
        }
        if !(start..end).contains(&self.state.index) {
            if self.state.plays_remaining > 0 {
                self.state.plays_remaining -= 1;
                self.state.index = if !mirror && self.state.direction == -1 {
                    end - 1
                } else {
                    start
                };
                if mirror {
                    self.state.direction = 1;
                }
                return;
            }
            self.state.exhausted = Some(frame);
            self.state.position = 0.0;
            self.state.error = 0.0;
        }
    }

    /// The second tap and its linear weight when crossfading a loop.
    pub fn overlap_tap(&self) -> Option<(i64, f64)> {
        if !self.state.overlap {
            return None;
        }
        let (a, b, overlap, _) = self.selection.3.expect("validated overlap");
        let offset = if self.state.direction == 1 {
            self.state.index - (b - overlap)
        } else {
            a + overlap - 1 - self.state.index
        };
        let incoming = if self.state.direction == 1 {
            a + offset
        } else {
            b - 1 - offset
        };
        Some((incoming, offset as f64 / (overlap - 1) as f64))
    }

    fn boundary(&self) -> (i64, u64) {
        let (start, end, mirror, loop_) = self.selection;
        if let Some((a, b, overlap, _)) = loop_.filter(|_| self.state.looping || self.state.overlap)
        {
            let length = b - a;
            if mirror {
                return (
                    if self.state.direction == 1 { b - 1 } else { a },
                    if (a..b).contains(&self.state.index) {
                        2 * (length - 1) as u64
                    } else {
                        0
                    },
                );
            }
            if self.state.direction == 1 {
                return (
                    b - if self.state.overlap { 0 } else { overlap },
                    if self.state.looping && (a + overlap..b).contains(&self.state.index) {
                        (length - overlap) as u64
                    } else {
                        0
                    },
                );
            }
            return (
                a - 1 + if self.state.overlap { 0 } else { overlap },
                if self.state.looping && (a..b - overlap).contains(&self.state.index) {
                    (length - overlap) as u64
                } else {
                    0
                },
            );
        }
        if mirror && loop_.is_none() && self.state.direction == 1 && end - start > 1 {
            return (end - 1, 0);
        }
        (
            if self.state.direction == 1 {
                end
            } else {
                start - 1
            },
            0,
        )
    }

    /// Advance by `step / rate` native frames, leaving an exact final boundary pending.
    pub fn advance(&mut self, step: f64, frame: i64) -> Result<(), Error> {
        if self.state.exhausted.is_some() {
            return Ok(());
        }
        let increment = step - self.state.error;
        let total = self.state.position + increment;
        if step < 0.0 || !total.is_finite() {
            return Err(Error::ArithmeticRange);
        }
        // Python float divmod snaps the quotient after computing the remainder.
        // floor(total / rate) alone can disagree at a rounded integer boundary.
        let mut remainder = total % self.rate;
        let mut quotient = (total - remainder) / self.rate;
        if !quotient.is_finite() {
            return Err(Error::ArithmeticRange);
        }
        if remainder < 0.0 {
            remainder += self.rate;
            quotient -= 1.0;
        }
        let mut count = quotient.floor();
        if quotient - count > 0.5 {
            count += 1.0;
        }
        self.state.error = (total - self.state.position) - increment;
        self.state.position = remainder;
        // Keep small moves separate from a huge integer-valued float count.
        // This avoids both integer overflow and loss of entry-path steps above 2**53.
        let mut consumed = 0.0;
        let mut finite_count = (self.state.repeats_remaining.is_some()
            || self.state.plays_remaining > 0)
            .then_some(count as u128);
        while finite_count.map_or(count > consumed, |c| c > 0) {
            if self.state.plays_remaining > 0 {
                let length = (self.selection.1 - self.selection.0) as u128;
                let period = if self.selection.2 {
                    2 * length - 1
                } else {
                    length
                };
                let left = finite_count.as_mut().expect("finite play count");
                let skipped = ((*left - 1) / period).min(self.state.plays_remaining as u128);
                self.state.plays_remaining -= skipped as u64;
                *left -= skipped * period;
            }
            let (boundary, period) = self.boundary();
            if period != 0 {
                if let Some(left) = &mut finite_count {
                    let traversals = if self.selection.2 { 2 } else { 1 };
                    let remaining = self.state.repeats_remaining.as_mut().expect("finite count");
                    let skipped =
                        ((*left - 1) / period as u128).min((*remaining / traversals) as u128);
                    *remaining -= skipped as u64 * traversals;
                    *left -= skipped * period as u128;
                    if skipped > 0 && *remaining == 0 {
                        self.state.looping = false;
                        continue;
                    }
                } else {
                    count = ((count % period as f64) - consumed).rem_euclid(period as f64);
                    if count == 0.0 {
                        count = period as f64;
                    }
                    consumed = 0.0;
                }
            }
            let distance = self.state.direction * (boundary - self.state.index);
            let moved = finite_count.map_or_else(
                || (count - consumed).min(distance as f64) as i64,
                |c| c.min(distance as u128) as i64,
            );
            self.state.index += self.state.direction * moved;
            consumed += moved as f64;
            if let Some(left) = &mut finite_count {
                *left -= moved as u128;
            }
            if finite_count.map_or(count > consumed, |c| c > 0) || self.state.position != 0.0 {
                self.settle(frame);
                if self.state.exhausted.is_some() {
                    return Ok(());
                }
            }
        }
        Ok(())
    }

    /// Advance across a release strictly inside the frame.
    pub fn advance_with_release(
        &mut self,
        step: f64,
        fraction: Rational,
        next_frame: i64,
    ) -> Result<(), Error> {
        let (before, after) = split_step(step, fraction)?;
        self.advance(before, next_frame)?;
        if self.state.exhausted.is_none() {
            self.release();
            self.settle(next_frame);
            self.advance(after, next_frame)?;
        }
        Ok(())
    }
}
