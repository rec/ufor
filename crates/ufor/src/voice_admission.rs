//! Ordered retirement actions for a selected batch of instrument voices.

use crate::{error::Error, identifier::Identifier, samples::eligibility::Trigger};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::num::NonZeroU64;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Admission {
    tick: i64,
    ordinal: u64,
    part: Identifier,
    key: Option<i64>,
    voices: Vec<ActiveVoice>,
    chokes: Vec<Choke>,
    count: u64,
    policy: Option<VoicePolicy>,
    #[serde(default)]
    pool_counts: BTreeMap<Identifier, u64>,
    #[serde(default)]
    pools: BTreeMap<Identifier, VoicePolicy>,
    #[serde(default)]
    pool_by_template: BTreeMap<Identifier, Option<Identifier>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ActiveVoice {
    voice_id: Identifier,
    part: Identifier,
    template: Identifier,
    key: Option<i64>,
    choke_group: Option<Identifier>,
    #[serde(rename = "trigger_id", default)]
    _trigger_id: Option<Identifier>,
    #[serde(rename = "template_trigger", default)]
    _template_trigger: Trigger,
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
#[serde(try_from = "ChokeDefinition")]
pub struct Choke {
    group: Identifier,
    mode: ChokeMode,
    fade_seconds: Option<f64>,
}

impl Choke {
    pub fn new(
        group: Identifier,
        mode: ChokeMode,
        fade_seconds: Option<f64>,
    ) -> Result<Self, Error> {
        match (mode, fade_seconds) {
            (ChokeMode::Fade, Some(seconds)) if seconds.is_finite() && seconds > 0.0 => {}
            (ChokeMode::Immediate | ChokeMode::Release, None) => {}
            _ => return Err(Error::Invalid("invalid choke fade duration".into())),
        }
        Ok(Self {
            group,
            mode,
            fade_seconds,
        })
    }

    pub fn group(&self) -> &Identifier {
        &self.group
    }

    pub fn mode(&self) -> ChokeMode {
        self.mode
    }

    pub fn fade_seconds(&self) -> Option<f64> {
        self.fade_seconds
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ChokeDefinition {
    group: Identifier,
    mode: ChokeMode,
    #[serde(default, deserialize_with = "optional_seconds")]
    fade_seconds: Option<f64>,
}

impl TryFrom<ChokeDefinition> for Choke {
    type Error = Error;

    fn try_from(value: ChokeDefinition) -> Result<Self, Error> {
        Self::new(value.group, value.mode, value.fade_seconds)
    }
}

fn optional_seconds<'de, D: Deserializer<'de>>(d: D) -> Result<Option<f64>, D::Error> {
    #[derive(Deserialize)]
    struct Seconds(#[serde(deserialize_with = "seconds")] f64);
    fn seconds<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
        crate::quantity::deserialize_scalar(d, "seconds")
    }
    Option::<Seconds>::deserialize(d).map(|value| value.map(|seconds| seconds.0))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChokeMode {
    Immediate,
    Release,
    Fade,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VoicePolicy {
    pub maximum_voices: NonZeroU64,
    #[serde(default)]
    pub same_key: SameKey,
    #[serde(default)]
    pub overflow: Overflow,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct VoicePool {
    pub name: Identifier,
    pub policy: VoicePolicy,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SameKey {
    #[default]
    Stack,
    Release,
    Replace,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Overflow {
    #[default]
    ReleaseOldest,
    ReplaceOldest,
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Cause {
    Choke,
    SameKey,
    VoiceLimit,
}

#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Action {
    Release,
    Stop,
    Fade,
}

#[derive(Debug, Serialize)]
pub struct Retirement {
    kind: &'static str,
    pub tick: i64,
    pub ordinal: u64,
    pub voice_id: Identifier,
    pub cause: Cause,
    pub action: Action,
    pub fade_seconds: Option<f64>,
}

impl Admission {
    /// Resolve chokes, per-part pools in name order, then the global voice policy.
    pub fn retirements(&self) -> Result<Vec<Retirement>, Error> {
        let mut ids = BTreeSet::new();
        if self.voices.iter().any(|voice| !ids.insert(&voice.voice_id)) {
            return Err(Error::Invalid("duplicate active voice ID".into()));
        }
        let mut plan = Plan {
            batch: self,
            remaining: self.voices.iter().collect(),
            actions: Vec::new(),
        };
        for voice in self.voices.iter().filter(|voice| voice.part == self.part) {
            let mut release = false;
            let mut immediate = false;
            let mut fade: Option<f64> = None;
            for rule in self
                .chokes
                .iter()
                .filter(|rule| Some(&rule.group) == voice.choke_group.as_ref())
            {
                match rule.mode {
                    ChokeMode::Immediate => immediate = true,
                    ChokeMode::Release => release = true,
                    ChokeMode::Fade => {
                        let seconds = rule.fade_seconds.expect("validated fade duration");
                        fade = Some(fade.map_or(seconds, |minimum| minimum.min(seconds)));
                    }
                }
            }
            match (immediate, release, fade) {
                (true, _, _) => plan.retire(voice, Cause::Choke, Action::Stop, None),
                (false, true, None) => plan.retire(voice, Cause::Choke, Action::Release, None),
                (false, false, Some(seconds)) => {
                    plan.retire(voice, Cause::Choke, Action::Fade, Some(seconds));
                }
                (false, true, Some(_)) => {
                    return Err(Error::Invalid(
                        "combined fade and envelope-release chokes are unsupported".into(),
                    ));
                }
                (false, false, None) => {}
            }
        }
        for (pool, count) in &self.pool_counts {
            let policy = self
                .pools
                .get(pool)
                .ok_or_else(|| Error::Invalid(format!("unknown voice pool {}", pool.as_str())))?;
            plan.apply_policy(policy, *count, Some(pool))?;
        }
        if let Some(policy) = &self.policy {
            plan.apply_policy(policy, self.count, None)?;
        }
        Ok(plan.actions)
    }
}

struct Plan<'a> {
    batch: &'a Admission,
    remaining: Vec<&'a ActiveVoice>,
    actions: Vec<Retirement>,
}

impl Plan<'_> {
    fn apply_policy(
        &mut self,
        policy: &VoicePolicy,
        count: u64,
        pool: Option<&Identifier>,
    ) -> Result<(), Error> {
        let capacity = policy
            .maximum_voices
            .get()
            .checked_sub(count)
            .ok_or_else(|| {
                Error::Invalid(pool.map_or_else(
                    || "trigger batch exceeds maximum_voices".into(),
                    |name| format!("trigger batch exceeds voice pool {} limit", name.as_str()),
                ))
            })?;
        let mut scoped = Vec::new();
        for &voice in &self.remaining {
            if let Some(pool) = pool {
                if voice.part != self.batch.part {
                    continue;
                }
                let voice_pool = self
                    .batch
                    .pool_by_template
                    .get(&voice.template)
                    .ok_or_else(|| {
                        Error::Invalid(format!(
                            "missing voice pool assignment for {}",
                            voice.template.as_str()
                        ))
                    })?;
                if voice_pool.as_ref() != Some(pool) {
                    continue;
                }
            }
            if self.batch.key.is_some()
                && voice.key == self.batch.key
                && voice.part == self.batch.part
                && policy.same_key != SameKey::Stack
            {
                scoped.push((voice, true));
            } else {
                scoped.push((voice, false));
            }
        }
        let same_key_action = match policy.same_key {
            SameKey::Release => Action::Release,
            SameKey::Stack | SameKey::Replace => Action::Stop,
        };
        for &(voice, _) in scoped.iter().filter(|(_, matches)| *matches) {
            self.retire(voice, Cause::SameKey, same_key_action, None);
        }
        let survivors = scoped.into_iter().filter(|(_, matches)| !matches);
        let overflow = (survivors.clone().count() as u64).saturating_sub(capacity);
        let overflow_action = match policy.overflow {
            Overflow::ReleaseOldest => Action::Release,
            Overflow::ReplaceOldest => Action::Stop,
        };
        for (voice, _) in survivors.take(overflow as usize) {
            self.retire(voice, Cause::VoiceLimit, overflow_action, None);
        }
        Ok(())
    }

    fn retire(
        &mut self,
        voice: &ActiveVoice,
        cause: Cause,
        action: Action,
        fade_seconds: Option<f64>,
    ) {
        self.remaining.retain(|v| v.voice_id != voice.voice_id);
        self.actions.push(Retirement {
            kind: "voice_retirement",
            tick: self.batch.tick,
            ordinal: self.batch.ordinal,
            voice_id: voice.voice_id.clone(),
            cause,
            action,
            fade_seconds,
        });
    }
}
