//! Structural checks and pure Patch preparation, independent of any runtime.
use super::*;
use std::collections::{BTreeMap, BTreeSet, VecDeque};

pub(super) fn text(value: &str) -> Result<(), Error> {
    if value.chars().take(4097).count() > 4096 {
        Err(Error::Limit("generator text characters"))
    } else {
        Ok(())
    }
}
pub(super) fn hash(value: Option<&str>) -> Result<(), Error> {
    if value.is_some_and(|v| {
        v.len() != 64
            || !v
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    }) {
        return Err(invalid("invalid SHA-256"));
    }
    Ok(())
}
fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}
fn name(value: &str, score: bool) -> Result<(), Error> {
    if value.is_empty()
        || value.trim_matches(whitespace) != value
        || value.contains([':', '#', '/'])
        || (score && value.contains(".*"))
    {
        return Err(invalid("invalid selector name"));
    }
    Ok(())
}
pub(super) fn selector(value: &str) -> Result<String, Error> {
    text(value)?;
    let mut rest = value.trim_matches(whitespace);
    let mut result = String::new();
    if let Some((library, tail)) = rest.split_once(':') {
        let library = library.trim_matches(whitespace);
        name(library, false)?;
        result.push_str(library);
        result.push(':');
        rest = tail;
    }
    let (words, path) = match rest.split_once('/') {
        Some((w, p)) => (w, Some(p.trim_matches(whitespace))),
        None => (rest, None),
    };
    let mut words = words.split('#');
    let first = words.next().unwrap_or("").trim_matches(whitespace);
    if !first.is_empty() {
        name(first, true)?;
        result.push_str(first);
    }
    let mut tags = BTreeSet::new();
    for word in words {
        let tag = word.trim_matches(whitespace);
        if tag.is_empty()
            || tag
                .chars()
                .any(|c| whitespace(c) || matches!(c, ':' | '#' | '/'))
        {
            return Err(invalid("invalid selector tag"));
        }
        if tags.insert(tag) {
            result.push('#');
            result.push_str(tag);
        }
    }
    if let Some(path) = path {
        if path.contains([':', '#', '\\'])
            || path
                .split('/')
                .any(|p| p.is_empty() || matches!(p, "." | "..") || p.trim_matches(whitespace) != p)
        {
            return Err(invalid("invalid selector address"));
        }
        result.push('/');
        result.push_str(path);
    }
    Ok(result)
}
pub(super) fn score_reference(r: &ScoreReference) -> Result<(), Error> {
    if r.path.is_some() == r.selector.is_some() {
        return Err(invalid("reference requires one path or selector"));
    }
    hash(r.sha256.as_deref())?;
    if let Some(path) = &r.path {
        text(path)?;
        // Match urllib's scheme recognition without accessing a resource.
        let url_text = path
            .trim_start_matches(|c: char| c <= '\u{20}')
            .replace(['\t', '\r', '\n'], "");
        let prefix = url_text.split_once(':').map(|(p, _)| p);
        let scheme = prefix.is_some_and(|p| {
            let mut chars = p.chars();
            chars.next().is_some_and(|c| c.is_ascii_alphabetic())
                && chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'))
        });
        if path.is_empty()
            || path.starts_with('/')
            || path.contains('\\')
            || path.chars().nth(1) == Some(':')
            || scheme
            || path.split('/').all(|p| p.is_empty() || p == ".")
        {
            return Err(invalid("score path must be relative POSIX"));
        }
    }
    Ok(())
}
fn reference(value: &Reference) -> Result<(), Error> {
    for (_, value) in &value.parameters {
        match value {
            ParameterValue::Number(v) => {
                finite(*v)?;
            }
            ParameterValue::Text(v) => text(v)?,
        }
    }
    Ok(())
}
fn markers(values: &[Marker]) -> Result<(), Error> {
    let mut names = BTreeSet::new();
    for v in values {
        if !names.insert(&v.name) {
            return Err(invalid("duplicate marker"));
        }
    }
    Ok(())
}
pub(super) fn generator(value: &mut Generator) -> Result<(), Error> {
    let s = &value.settings;
    if s.position_driver == PositionDriver::Transport {
        if s.clock != Clock::Beats || !matches!(&value.body, Body::Lfo(_) | Body::Reference(_)) {
            return Err(invalid("invalid transport position profile"));
        }
        if let Body::Lfo(v) = &value.body {
            if v.reset != Reset::Transport || v.delay.numerator() != 0 || v.fade_in.numerator() != 0
            {
                return Err(invalid("invalid transport LFO profile"));
            }
        }
    }
    match &mut value.body {
        Body::Lfo(v) => {
            finite(v.center)?;
            finite(v.depth)?;
            if matches!(&v.rate,Rate::Literal(r) if r.numerator()<0)
                || v.phase.numerator() < 0
                || v.phase.numerator() >= v.phase.denominator()
                || v.duty_cycle.numerator() < 0
                || v.duty_cycle.numerator() > v.duty_cycle.denominator()
                || v.delay.numerator() < 0
                || v.fade_in.numerator() < 0
                || v.depth < 0.0
                || finite(v.center - v.depth)? < -1.0
                || finite(v.center + v.depth)? > 1.0
            {
                return Err(invalid("invalid LFO domain"));
            }
            markers(&v.markers)?;
            if v.markers
                .iter()
                .any(|m| m.position.numerator() == m.position.denominator())
            {
                return Err(invalid("LFO marker must be less than one"));
            }
        }
        Body::Envelope(v) => envelope(v, s.clock)?,
        Body::SampleHold(v) => {
            finite(v.minimum)?;
            finite(v.maximum)?;
            if s.scope != Scope::Voice
                || v.minimum < -1.0
                || v.maximum > 1.0
                || v.minimum > v.maximum
            {
                return Err(invalid("invalid sample-hold profile"));
            }
        }
        Body::Stages(v) => {
            for child in &mut v.stages {
                inherited(&child.envelfo, s)?;
                generator(&mut child.envelfo)?;
            }
            stages(v)?;
        }
        Body::Patch(v) => {
            for (_, child) in &mut v.envelfos {
                match child {
                    PatchNode::Generator(g) => {
                        inherited(g, s)?;
                        generator(g)?;
                    }
                    PatchNode::Signal(n) => signal(n, s.scope)?,
                }
            }
            patch(v, s)?;
        }
        Body::Reference(v) => {
            if s.origin.is_some() {
                return Err(invalid("unresolved reference cannot have origin"));
            }
            reference(v)?;
        }
    }
    Ok(())
}
fn inherited(child: &Generator, parent: &Settings) -> Result<(), Error> {
    let c = &child.settings;
    if c.scope != parent.scope
        || c.clock != parent.clock
        || c.position_driver != PositionDriver::Elapsed
        || c.origin.is_some()
    {
        return Err(invalid("child generator settings must be inherited"));
    }
    Ok(())
}
fn envelope(v: &Envelope, clock: Clock) -> Result<(), Error> {
    if v.segments.is_empty() {
        return Err(invalid("envelope requires segments"));
    }
    let mut levels = Vec::new();
    if let Initial::Number(n) = v.initial {
        levels.push(n);
    }
    let mut indefinite = false;
    let mut captured = false;
    for part in v.segments.iter().chain(&v.release) {
        match part {
            EnvelopeSegment::Indefinite => indefinite = true,
            EnvelopeSegment::Approach(a) => {
                captured = true;
                levels.extend([a.asymptote, a.threshold, a.transition_to]);
            }
            EnvelopeSegment::Definite(s) => {
                if s.duration_unit != clock {
                    return Err(invalid("segment units must match clock"));
                }
                levels.push(s.to.value());
            }
        }
    }
    for level in levels {
        finite(level)?;
        if !(-1.0..=1.0).contains(&level) || (v.polarity == Polarity::Unipolar && level < 0.0) {
            return Err(invalid("envelope polarity domain"));
        }
    }
    if (captured
        && (clock != Clock::Seconds
            || !v.markers.is_empty()
            || v.playback != PlaybackMode::Once
            || indefinite))
        || (indefinite && (!v.markers.is_empty() || v.playback != PlaybackMode::Once))
    {
        return Err(invalid("invalid envelope playback profile"));
    }
    markers(&v.markers)?;
    if v.loop_start.is_some() != v.loop_end.is_some()
        || v.repeat_count.is_some_and(|n| n < 1)
        || (v.playback == PlaybackMode::Once
            && (v.loop_start.is_some() || v.repeat_count.is_some()))
    {
        return Err(invalid("invalid envelope loop bounds or count"));
    }
    if let (Some(start), Some(end)) = (&v.loop_start, &v.loop_end) {
        let a = v
            .markers
            .iter()
            .find(|m| &m.name == start)
            .ok_or_else(|| invalid("unknown loop start"))?
            .position;
        let b = v
            .markers
            .iter()
            .find(|m| &m.name == end)
            .ok_or_else(|| invalid("unknown loop end"))?
            .position;
        if a >= b || v.markers.iter().any(|m| m.position > b) {
            return Err(invalid("invalid loop marker order"));
        }
    }
    Ok(())
}
fn body_markers(value: &Generator) -> &[Marker] {
    match &value.body {
        Body::Lfo(v) => &v.markers,
        Body::Envelope(v) => &v.markers,
        _ => &[],
    }
}
fn stage_ports_for(value: &Generator) -> Vec<String> {
    let mut ports: Vec<_> = body_markers(value)
        .iter()
        .map(|m| m.name.as_str().to_owned())
        .collect();
    match &value.body {
        Body::Envelope(v) => {
            if v.playback == PlaybackMode::Once || v.repeat_count.is_some() {
                ports.push("done".into());
            }
            if v.playback != PlaybackMode::Once {
                ports.push("cycle".into());
            }
            if v.playback == PlaybackMode::PingPong {
                ports.push("turned".into());
            }
        }
        _ => ports.push("done".into()),
    }
    ports
}
pub(super) fn stage_ports(value: &Stages) -> Vec<String> {
    let mut ports = BTreeSet::from(["done".to_owned(), "stage.done".to_owned()]);
    for stage in &value.stages {
        ports.extend(
            body_markers(&stage.envelfo)
                .iter()
                .map(|m| m.name.as_str().to_owned()),
        );
        if let Body::Envelope(e) = &stage.envelfo.body {
            if e.playback != PlaybackMode::Once {
                ports.insert("cycle".into());
            }
            if e.playback == PlaybackMode::PingPong {
                ports.insert("turned".into());
            }
        }
    }
    ports.into_iter().collect()
}
fn stages(v: &Stages) -> Result<(), Error> {
    let mut names = BTreeMap::new();
    for (i, s) in v.stages.iter().enumerate() {
        if names.insert(&s.name, i).is_some() {
            return Err(invalid("duplicate stage"));
        }
    }
    let initial = *names
        .get(&v.initial_stage)
        .ok_or_else(|| invalid("unknown initial stage"))?;
    if matches!(
        &v.stages[initial].envelfo.body,
        Body::Envelope(Envelope {
            initial: Initial::Current,
            ..
        })
    ) {
        return Err(invalid("initial stage cannot capture current value"));
    }
    for s in &v.stages {
        if body_markers(&s.envelfo)
            .iter()
            .any(|m| m.name.as_str() == "done")
        {
            return Err(invalid("reserved stage marker"));
        }
        match &s.envelfo.body {
            Body::Lfo(v) if matches!(v.rate, Rate::Parameter(_)) => {
                return Err(invalid("stage LFO requires literal rate"));
            }
            Body::Envelope(v) => {
                if v.start == Start::Event
                    || !v.release.is_empty()
                    || v.segments
                        .iter()
                        .any(|s| matches!(s, EnvelopeSegment::Approach(_)))
                    || !v.segments.iter().any(
                        |s| !matches!(s,EnvelopeSegment::Definite(v) if v.duration.numerator()==0),
                    )
                {
                    return Err(invalid("invalid stage envelope"));
                }
                if v.playback != PlaybackMode::Once
                    && v.markers.iter().any(|m| {
                        m.position.numerator() == 0
                            || m.position.numerator() == m.position.denominator()
                            || matches!(m.name.as_str(), "cycle" | "turned")
                    })
                {
                    return Err(invalid("reserved looping stage marker"));
                }
            }
            Body::Lfo(_) => (),
            _ => return Err(invalid("unsupported stage body")),
        }
    }
    for t in &v.transitions {
        text(&t.event)?;
        if t.from_stages.is_empty() || t.from_stages.iter().any(|n| !names.contains_key(n)) {
            return Err(invalid("invalid transition sources"));
        }
        if let StageAction::Enter { stage } = &t.action {
            if !names.contains_key(stage) {
                return Err(invalid("unknown transition destination"));
            }
        }
        if !matches!(t.event.as_str(), "note_on" | "note_off" | "stage.done")
            && !t.event.starts_with("cue.")
            && !t.event.starts_with("stage.")
        {
            return Err(invalid("unsupported transition event"));
        }
        if let Some(port) = t.event.strip_prefix("stage.") {
            for name in &t.from_stages {
                if !stage_ports_for(&v.stages[names[name]].envelfo)
                    .iter()
                    .any(|p| p == port)
                {
                    return Err(invalid("unknown stage port"));
                }
            }
        }
    }
    Ok(())
}
fn signal(v: &SignalNode, scope: Scope) -> Result<(), Error> {
    match v.operation {
        SignalOperation::Sum | SignalOperation::Product => {
            if v.inputs.len() < 2 {
                return Err(invalid("signal requires at least two inputs"));
            }
        }
        SignalOperation::Affine { scale, offset } => {
            finite(scale)?;
            finite(offset)?;
        }
        SignalOperation::Quantize { step, origin } => {
            finite(step)?;
            finite(origin)?;
            if step <= 0.0 {
                return Err(invalid("invalid quantizer step"));
            }
        }
        SignalOperation::Threshold { lower, upper } => {
            finite(lower)?;
            finite(upper)?;
            if lower >= upper {
                return Err(invalid("invalid threshold window"));
            }
        }
        SignalOperation::Slew {
            rise,
            fall,
            initial,
        } => {
            finite(rise)?;
            finite(fall)?;
            if let Some(v) = initial {
                finite(v)?;
            }
            if rise < 0.0 || fall < 0.0 {
                return Err(invalid("invalid slew rate"));
            }
        }
        SignalOperation::Latch => (),
    }
    if matches!(
        v.operation,
        SignalOperation::Latch | SignalOperation::Slew { .. } | SignalOperation::Threshold { .. }
    ) && scope != Scope::Voice
    {
        return Err(invalid("stateful signal requires voice scope"));
    }
    Ok(())
}
fn ports(node: &PatchNode) -> Vec<String> {
    match node {
        PatchNode::Generator(g) => match &g.body {
            Body::Lfo(v) => v
                .markers
                .iter()
                .map(|m| m.name.as_str().to_owned())
                .collect(),
            Body::Stages(v) => stage_ports(v),
            _ => Vec::new(),
        },
        PatchNode::Signal(v) if matches!(v.operation, SignalOperation::Threshold { .. }) => {
            vec!["rising".into(), "falling".into()]
        }
        _ => Vec::new(),
    }
}
fn event_origin<'a>(
    source: &str,
    nodes: &'a [(Identifier, PatchNode)],
    indices: &BTreeMap<Identifier, usize>,
    settings: &Settings,
) -> Result<&'a PatchNode, Error> {
    text(source)?;
    let (name, port) = source
        .split_once('.')
        .ok_or_else(|| invalid("event must name child.port"))?;
    let id = Identifier::new(name.to_owned())?;
    let node = &nodes[*indices
        .get(&id)
        .ok_or_else(|| invalid("unknown event child"))?]
    .1;
    if !ports(node).iter().any(|p| p == port) {
        return Err(invalid("unknown child event port"));
    }
    if let PatchNode::Generator(g) = node {
        if let Body::Lfo(l) = &g.body {
            if settings.scope != Scope::Voice
                || settings.clock != Clock::Seconds
                || !matches!(&l.rate,Rate::Literal(r) if r.numerator()!=0)
                || l.reset != Reset::Trigger
                || l.delay.numerator() != 0
                || l.fade_in.numerator() != 0
            {
                return Err(invalid("event LFO requires simple voice seconds profile"));
            }
        }
    }
    Ok(node)
}
fn patch(v: &mut Patch, settings: &Settings) -> Result<(), Error> {
    if v.envelfos.is_empty() || v.outputs.is_empty() {
        return Err(invalid("Patch requires children and outputs"));
    }
    let mut indices = BTreeMap::new();
    for (i, (name, node)) in v.envelfos.iter().enumerate() {
        if indices.insert(name.clone(), i).is_some() {
            return Err(invalid("duplicate Patch child"));
        }
        if let PatchNode::Generator(g) = node {
            if matches!(
                &g.body,
                Body::Lfo(Lfo {
                    rate: Rate::Parameter(_),
                    ..
                }) | Body::Envelope(Envelope {
                    initial: Initial::Current,
                    ..
                }) | Body::Patch(_)
                    | Body::Reference(_)
            ) {
                return Err(invalid("unsupported inline generator profile"));
            }
        }
    }
    let mut degrees = vec![0; v.envelfos.len()];
    let mut consumers = vec![Vec::new(); v.envelfos.len()];
    for (i, (_, node)) in v.envelfos.iter().enumerate() {
        if let PatchNode::Signal(n) = node {
            for input in &n.inputs {
                let source = *indices
                    .get(input)
                    .ok_or_else(|| invalid("unknown Patch signal input"))?;
                degrees[i] += 1;
                consumers[source].push(i);
            }
        }
    }
    let mut pending: VecDeque<_> = degrees
        .iter()
        .enumerate()
        .filter_map(|(i, n)| (*n == 0).then_some(i))
        .collect();
    let mut order = Vec::new();
    let mut ranges = vec![(0.0, 0.0); v.envelfos.len()];
    while let Some(index) = pending.pop_front() {
        let node = &v.envelfos[index].1;
        let range = match node {
            PatchNode::Generator(g) => {
                if matches!(
                    &g.body,
                    Body::Envelope(Envelope {
                        polarity: Polarity::Unipolar,
                        ..
                    })
                ) {
                    (0.0, 1.0)
                } else {
                    (-1.0, 1.0)
                }
            }
            PatchNode::Signal(n) => {
                let input = |i: usize| ranges[indices[&n.inputs[i]]];
                match n.operation {
                    SignalOperation::Sum => {
                        let (mut low, mut high) = (0.0, 0.0);
                        for name in &n.inputs {
                            let (a, b) = ranges[indices[name]];
                            low = finite(low + a)?;
                            high = finite(high + b)?;
                        }
                        (low, high)
                    }
                    SignalOperation::Product => {
                        let (mut low, mut high) = (1.0, 1.0);
                        for name in &n.inputs {
                            let (a, b) = ranges[indices[name]];
                            let values = [
                                finite(low * a)?,
                                finite(low * b)?,
                                finite(high * a)?,
                                finite(high * b)?,
                            ];
                            low = values.into_iter().fold(f64::INFINITY, f64::min);
                            high = values.into_iter().fold(f64::NEG_INFINITY, f64::max);
                        }
                        (low, high)
                    }
                    SignalOperation::Affine { scale, offset } => {
                        let (a, b) = input(0);
                        let a = finite(offset + finite(scale * a)?)?;
                        let b = finite(offset + finite(scale * b)?)?;
                        (a.min(b), a.max(b))
                    }
                    SignalOperation::Quantize { step, origin } => {
                        let (a, b) = input(0);
                        (
                            quantize_value(a, step, origin)?,
                            quantize_value(b, step, origin)?,
                        )
                    }
                    SignalOperation::Latch => input(0),
                    SignalOperation::Threshold { .. } => (0.0, 1.0),
                    SignalOperation::Slew { initial, .. } => {
                        let (a, b) = input(0);
                        match initial {
                            Some(i) => (a.min(i), b.max(i)),
                            None => (a, b),
                        }
                    }
                }
            }
        };
        ranges[index] = range;
        order.push(index);
        for next in &consumers[index] {
            degrees[*next] -= 1;
            if degrees[*next] == 0 {
                pending.push_back(*next);
            }
        }
    }
    if order.len() != v.envelfos.len() {
        return Err(invalid("Patch signal cycle"));
    }
    if v.outputs.iter().any(|(_, n)| !indices.contains_key(n)) {
        return Err(invalid("unknown Patch output"));
    }
    for (_, source) in &v.event_outputs {
        event_origin(source, &v.envelfos, &indices, settings)?;
    }
    if !v.events.is_empty() && settings.scope != Scope::Voice {
        return Err(invalid("Patch events require voice scope"));
    }
    for e in &v.events {
        finite(e.probability)?;
        if e.every < 1
            || e.offset < 0
            || !(0.0..=1.0).contains(&e.probability)
            || e.delay.numerator() < 0
            || (e.action == EventAction::Cue) != e.cue.is_some()
        {
            return Err(invalid("invalid Patch event policy"));
        }
        event_origin(&e.source, &v.envelfos, &indices, settings)?;
        let target = &v.envelfos[*indices
            .get(&e.target)
            .ok_or_else(|| invalid("unknown event target"))?]
        .1;
        let valid = match (e.action, target) {
            (
                EventAction::Capture,
                PatchNode::Signal(SignalNode {
                    operation: SignalOperation::Latch,
                    ..
                }),
            ) => true,
            (EventAction::Sample, PatchNode::Generator(g)) => matches!(g.body, Body::SampleHold(_)),
            (EventAction::Start, PatchNode::Generator(g)) => {
                matches!(&g.body,Body::Envelope(e) if e.start==Start::Event && e.release.is_empty() && e.playback==PlaybackMode::Once && e.retrigger==Retrigger::Current)
            }
            (EventAction::Cue, PatchNode::Generator(g)) => match &g.body {
                Body::Stages(s) => s.transitions.iter().any(|t| {
                    e.cue
                        .as_ref()
                        .is_some_and(|cue| t.event == format!("cue.{}", cue.as_str()))
                }),
                _ => false,
            },
            _ => false,
        };
        if !valid {
            return Err(invalid("event action is incompatible with target"));
        }
    }
    v.signal_order = order.iter().map(|i| v.envelfos[*i].0.clone()).collect();
    v.signal_ranges = order
        .iter()
        .map(|i| (v.envelfos[*i].0.clone(), ranges[*i]))
        .collect();
    Ok(())
}
