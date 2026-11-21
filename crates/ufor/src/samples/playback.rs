//! Portable sample traversal declarations in native asset frames.
use crate::{error::Error, identifier::Identifier};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Direction {
    #[default]
    Forward,
    Backward,
    Mirror,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PlaybackMode {
    #[default]
    WhileHeld,
    OneShot,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LoopMode {
    #[default]
    UntilRelease,
    ThroughRelease,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Playback {
    #[serde(default)]
    pub direction: Direction,
    #[serde(default)]
    pub mode: PlaybackMode,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(try_from = "SliceDefinition", into = "SliceDefinition")]
pub struct Slice(SliceDefinition);

impl Slice {
    pub fn name(&self) -> &Identifier {
        &self.0.name
    }

    pub fn asset(&self) -> &Identifier {
        &self.0.asset
    }

    pub fn start_frame(&self) -> i64 {
        self.0.start_frame
    }

    pub fn end_frame(&self) -> i64 {
        self.0.end_frame
    }

    pub fn loop_settings(&self) -> Option<&Loop> {
        self.0.loop_settings.as_ref()
    }

    /// Validate a resolved playback against the available decoded frames.
    /// The repeat budget counts additional plays after the first.
    pub fn validate_playback(
        &self,
        playback: Playback,
        available_frames: i64,
        additional_plays: u64,
    ) -> Result<(), Error> {
        if self.end_frame() > available_frames {
            return Err(invalid("Sample slice exceeds decoded audio"));
        }
        if additional_plays > 0 && playback.mode != PlaybackMode::OneShot {
            return Err(invalid("Repeated sample playback requires one_shot mode"));
        }
        if let Some(loop_settings) = self.loop_settings() {
            if playback.mode != PlaybackMode::WhileHeld {
                return Err(invalid("Sample loops require while_held playback"));
            }
            if playback.direction == Direction::Mirror && loop_settings.crossfade_frames() > 0 {
                return Err(invalid("Mirror loops cannot crossfade"));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(try_from = "LoopDefinition", into = "LoopDefinition")]
pub struct Loop(LoopDefinition);

impl Loop {
    pub fn start_frame(&self) -> i64 {
        self.0.start_frame
    }

    pub fn end_frame(&self) -> i64 {
        self.0.end_frame
    }

    pub fn mode(&self) -> LoopMode {
        self.0.mode
    }

    pub fn direction(&self) -> Direction {
        self.0.direction
    }

    pub fn crossfade_frames(&self) -> i64 {
        self.0.crossfade_frames
    }

    pub fn repeat_count(&self) -> Option<u64> {
        self.0.repeat_count
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SliceDefinition {
    name: Identifier,
    asset: Identifier,
    #[serde(default)]
    start_frame: i64,
    end_frame: i64,
    #[serde(rename = "loop", default, skip_serializing_if = "Option::is_none")]
    loop_settings: Option<Loop>,
}

impl TryFrom<SliceDefinition> for Slice {
    type Error = Error;

    fn try_from(value: SliceDefinition) -> Result<Self, Error> {
        if value.start_frame < 0 || value.end_frame <= value.start_frame {
            return Err(invalid("end_frame must exceed the nonnegative start_frame"));
        }
        if value.loop_settings.as_ref().is_some_and(|settings| {
            settings.start_frame() < value.start_frame || settings.end_frame() > value.end_frame
        }) {
            return Err(invalid("Loop must be contained in the slice interval"));
        }
        Ok(Self(value))
    }
}

impl From<Slice> for SliceDefinition {
    fn from(value: Slice) -> Self {
        value.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LoopDefinition {
    start_frame: i64,
    end_frame: i64,
    #[serde(default)]
    mode: LoopMode,
    #[serde(default)]
    direction: Direction,
    #[serde(default)]
    crossfade_frames: i64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    repeat_count: Option<u64>,
}

impl TryFrom<LoopDefinition> for Loop {
    type Error = Error;

    fn try_from(value: LoopDefinition) -> Result<Self, Error> {
        if value.start_frame < 0 || value.end_frame <= value.start_frame {
            return Err(invalid("A loop requires ordered nonnegative frames"));
        }
        let length = value.end_frame - value.start_frame;
        if length < 2 {
            return Err(invalid("A loop must contain at least two frames"));
        }
        if value.direction == Direction::Mirror && value.crossfade_frames != 0 {
            return Err(invalid("Mirror loops cannot crossfade"));
        }
        if value.crossfade_frames != 0 && !(2..=(length - 1) / 2).contains(&value.crossfade_frames)
        {
            return Err(invalid(
                "Loop crossfade must occupy less than half the loop and contain at least two frames",
            ));
        }
        Ok(Self(value))
    }
}

impl From<Loop> for LoopDefinition {
    fn from(value: Loop) -> Self {
        value.0
    }
}

fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
