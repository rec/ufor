//! Physical key release and per-part sustain transitions for semantic traces.

use crate::{error::Error, identifier::Identifier, samples::eligibility::Trigger};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseRequest {
    triggers: Vec<ActiveTrigger>,
    event: Event,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ActiveTrigger {
    part: Identifier,
    trigger_id: Identifier,
    #[serde(default)]
    physically_released: bool,
    #[serde(default)]
    logical_released: bool,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Event {
    KeyRelease {
        part: Identifier,
        trigger_id: Identifier,
        sustain_pressed: bool,
    },
    PedalChange {
        part: Identifier,
        was_pressed: bool,
        value: f64,
        threshold: f64,
    },
}

/// Indices refer to the unchanged trigger order in the request.
#[derive(Debug, Default, Serialize)]
pub struct ReleasePlan {
    pub unknown_release: bool,
    pub physical_index: Option<usize>,
    pub logical_indices: Vec<usize>,
    pub sustain_pressed: Option<bool>,
    pub sustain_trigger: Option<Trigger>,
}

impl ReleaseRequest {
    pub fn plan(&self) -> Result<ReleasePlan, Error> {
        match &self.event {
            Event::KeyRelease {
                part,
                trigger_id,
                sustain_pressed,
            } => {
                let active = self.triggers.iter().enumerate().find(|(_, trigger)| {
                    &trigger.part == part && &trigger.trigger_id == trigger_id
                });
                let Some((index, trigger)) = active else {
                    return Ok(ReleasePlan {
                        unknown_release: true,
                        ..ReleasePlan::default()
                    });
                };
                if trigger.physically_released {
                    return Ok(ReleasePlan::default());
                }
                Ok(ReleasePlan {
                    physical_index: Some(index),
                    logical_indices: if *sustain_pressed {
                        vec![]
                    } else {
                        vec![index]
                    },
                    ..ReleasePlan::default()
                })
            }
            Event::PedalChange {
                part,
                was_pressed,
                value,
                threshold,
            } => {
                if !(-1.0..=1.0).contains(value) || !(0.0..=1.0).contains(threshold) {
                    return Err(Error::Invalid(
                        "invalid sustain control value or threshold".into(),
                    ));
                }
                let pressed = value >= threshold;
                let mut plan = ReleasePlan {
                    sustain_pressed: Some(pressed),
                    ..ReleasePlan::default()
                };
                if pressed != *was_pressed {
                    if pressed {
                        plan.sustain_trigger = Some(Trigger::SustainPress);
                    } else {
                        plan.sustain_trigger = Some(Trigger::SustainRelease);
                        plan.logical_indices = self
                            .triggers
                            .iter()
                            .enumerate()
                            .filter_map(|(i, trigger)| {
                                (&trigger.part == part
                                    && trigger.physically_released
                                    && !trigger.logical_released)
                                    .then_some(i)
                            })
                            .collect();
                    }
                }
                Ok(plan)
            }
        }
    }
}
