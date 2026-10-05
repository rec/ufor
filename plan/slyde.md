# slyde: standalone slideshow player

## Goal and scope

Create `slyde` as a separate desktop application and repository that plays
uFor `SlideshowScore` documents. Initial platforms are macOS, Windows, and
Linux. Ship native application bundles that work without a separately installed
Python interpreter, development checkout, recs process, or network connection
when playing a local package. Mobile and browser editions are outside the first
release.

Use the existing [slideshow format](../doc/slideshow-format.md), codec,
validation, and content identities. Keep player state, decoding, device access,
and presentation policy in slyde. A player must never silently alter a score to
make it playable.

The first milestone plays local still images with cut transitions, automatic
and manual advance, fullscreen output, and keyboard controls. The first complete
release adds video, crossfades and wipes, named cues, separate accompaniment,
captions, and reliable run observations. A milestone must clearly report any
unsupported score feature during preparation.

## Recommended implementation

Use Python 3.13+, uv, uFor, and PySide6. Use Qt Widgets for application controls
and a dedicated presentation surface, with Qt Multimedia as the proposed media
backend. Use one Qt event loop and one playback controller. Keep the controller's
timing and navigation logic independent of Qt so tests can drive it with a
controlled clock. Avoid introducing an async runtime alongside the Qt loop.

Validate this choice before building the full player. Qt documents platform and
codec differences in its [multimedia backend](https://doc.qt.io/qt-6/qtmultimedia-index.html).
Prove bounded video playback, seeking, captions, and compositing on each target;
do not infer identical behavior from a shared API. Prototype two simultaneous
video surfaces if transitions between videos need them. If the backend cannot
meet the agreed profile, revise the backend choice at this gate.

Use Qt's [pyside6-deploy](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
as the initial packaging candidate. Build and test bundles on each target OS.
Record the supported OS versions, architectures, image formats, video/audio
profiles, and display limits from those results. Pin a tested release combination
in slyde; do not add GUI or media dependencies to uFor.

## Opening and preparing a show

Opening slyde presents a file chooser and recent local shows. Accept a slideshow
score through Open, drag-and-drop, command line, or the platform's file-opening
mechanism. Recent-show preferences contain local paths, not copies of score data.
Keep the initial window visible while preparation runs; presentation starts only
after the user presses Play.

Preparation must:

1. Parse through uFor and require `kind = "slideshow"`.
2. Resolve selected finite assets beneath the package root, check SHA-256 and
   length, and compare decoded media facts with the declaration.
3. Check every requested advance mode, transition, caption source, media format,
   source range, and output capability before declaring the show ready.
4. Present actionable errors naming the score item, asset, and failing operation.
5. Prepare the first visible item and a bounded amount of look-ahead media.

The initial edition supports sealed relative-file packages. Reject other
locations clearly. Later finite volume, HTTPS, and Git support must use explicit
host policy and reuse reccy's verified acquisition/cache helpers rather than
copying recs' application code or creating another cache. Python providers and
live stream locations are outside the player scope because this slideshow
format requires finite assets.

Do not execute `DirectorySelection` recipes during playback. Their authored item
list is the show; directory changes must not silently change it. A future import
tool can enumerate and seal selections as a separate operation.

## Format decisions before full playback

The models describe valid documents, but the following playback details need a
normative contract in uFor documentation and conformance examples. These are
proposed decisions, not assumptions to hide in the implementation.

- Define the units and timebase of video and accompaniment source ranges, their
  half-open boundaries, and whether slide duration may differ from source extent.
  Start with normal-speed playback and reject incompatible extents; do not
  silently stretch, loop, or pad media.
- Define transition overlap. Recommend that slide duration includes its visible
  transition intervals, with the incoming slide starting when the outgoing
  transition begins. Cuts take no time. Specify the wipe direction and easing
  that an authored `wipe` means, since the current model has no such fields.
- Specify what happens when Next, Back, a cue, or Hold arrives during a
  transition. Recommend completing navigation through one controller, using a
  cut for nonadjacent navigation and discarding superseded pending actions.
- Define accompaniment `continue`, `pause`, and `seek` across manual waits,
  backward navigation, explicit pause, and restart. Recommend explicit pause
  stopping all media; manual waiting then follows the selected manual policy.
  Keep elapsed run time separate from authored score position.
- Specify supported external caption encodings and their timing units, and how
  caption offsets relate to accompaniment position. Inline captions provide the
  first supported caption path.
- Define whether a video range ending early freezes the last frame, advances, or
  fails. Recommend rejecting incompatible authored ranges in preparation and
  treating unexpected decoder end as a playback failure.
- Define the run observations required for replay. `RunEvent.detail` alone does
  not provide a typed pause/resume or media-position contract. Add only the
  minimal versioned format change needed if existing events cannot represent the
  chosen behavior; preserve the source score and write run output separately.

Do not advertise reproducible as-presented replay until those observations can
reconstruct navigation, timing, accompaniment position, and interrupted runs.

## Presentation and operator controls

Provide a clean presentation window and an operator window with current/next
preview, item name, elapsed time, advance mode, cue name, audio state, and errors.
The first milestone can combine controls and preview in one window; support a
separate audience display before the complete release.

Use these defaults, with visible menu equivalents:

| Action | Default input |
| --- | --- |
| Next | Right arrow or Page Down |
| Previous | Left arrow or Page Up |
| Pause/resume | Space |
| Toggle fullscreen | F |
| Blackout/restore presentation | B |
| Leave fullscreen | Escape |
| Stop and return to ready state | Stop control |
| Quit | Platform-standard Quit action |

Blackout hides the audience image while time continues; Pause stops playback
time and media. Show both states in operator controls. Back at the first item is
a no-op; automatic completion of the last item enters Finished and stops audio
without looping. Restart is explicit. Repeated key events must not create an
unbounded navigation queue.

Expose named cue delivery in the operator interface, accepting only cues relevant
to the loaded show. External MIDI, OSC, or remote control can be a later,
separately scoped integration. Do not introduce a server just to drive the UI.

Choose the output monitor explicitly, handle scaling and aspect ratio, and keep
controls off the audience surface. If the audience display disconnects, pause
and notify the operator rather than expose the show or controls on another
monitor automatically. Window focus loss must not advance or restart playback.

Respect authored alt text and descriptions in the operator interface, expose
controls through accessibility APIs, and allow caption language selection when
multiple tracks exist. Crop, metadata orientation, authored rotation, fitting,
background color, and caption placement need one documented rendering order and
visual fixtures.

## Timing, decoding, and audio

Schedule from a monotonic clock using exact score tick conversions. Qt timers
wake the controller; elapsed clock time determines the current position. Do not
accumulate duration by counting timer callbacks. Test late wakes, pause/resume,
manual advance, and navigation across transitions.

Keep image decoding and asset verification off the GUI thread, with a bounded
worker queue and cancellation on stop or show replacement. Limit decoded image
dimensions, pixel count, resident bytes, video decoders, and look-ahead work.
Preload current/next items rather than the whole show. Retain verified asset
handles or leases for the full decoder lifetime, including any local snapshot
required by a path-based media backend. Stop media before releasing its storage.

Start with Qt media playback rather than writing a new audio engine. Assess enge
only if an existing interface is needed to meet synchronization requirements.
Video's embedded audio stays muted: uFor accompaniment is a separate declared
source. Choose an output device during preparation and define tested audiovisual
drift bounds using presented audio/video observations, not only requested player
positions. Device loss, decoder errors, and underruns must be surfaced to the
operator; never silently switch outputs or skip slides.

## Failure, shutdown, and run output

Use explicit Ready, Playing, Paused, Finished, Failed, and Closing states, plus
preparation progress. Own all transitions in the controller. Stopping cancels
pending work and closes media; replacing a show cannot leave an old callback
changing the new show's state.

On playback failure, pause the show, silence accompaniment, and retain the last
safe presentation image or blackout according to the documented failure policy.
Explain the error in the operator window. Resume only through an explicit action
after readiness has been restored.

Closing the window, Quit, and CLI interruption use the same shutdown path. Stop
timers and media, cancel preparation, finish or abandon bounded worker work,
release leases, and flush run output. Define a bounded shutdown deadline for
native decoding; do not claim a Python thread can cancel a blocked native call.
If this cannot be bounded with the selected backend, isolate that operation at
the backend gate rather than adding an untested force-stop mechanism.

Record ordered accepted operator actions and presentation/failure observations
with monotonic elapsed ticks and stable ordinals. Save beside an explicitly
chosen output path using atomic publication, leaving the source score intact.
A disk-full or permission failure must keep the operator informed and retain
the in-memory bounded record where possible. Do not promise crash-durable runs
until a tested incremental persistence strategy exists.

## Project structure and command line

Start a separate `slyde` repository with a small package: `cli.py`, `player.py`,
`media.py`, `assets.py`, and `window.py`, plus tests and packaged fixtures. Split
modules only when responsibilities warrant it. Share portable definitions with
uFor and general asset facilities with reccy; keep slyde's policies and UI local.

Use Tyro with Pydantic command models. Running `slyde` opens the chooser;
`slyde play SCORE` prepares a show, with explicit display/fullscreen options;
`slyde check SCORE` reports preparation diagnostics without starting output.
Return nonzero status for invalid or unsupported shows. The native application
and CLI call the same preparation and controller code.

## Implementation stages and acceptance

1. **Platform/backend gate.** Package a still image, video, and audio probe for
   all three OS families. Prove clean launch without development dependencies,
   media seeking, display selection, media cleanup, and shutdown.
   Document the supported media profile and resolve the format decisions above.
2. **Still-image player.** Open local uFor shows, verify assets, render crop,
   rotation and fit, implement cut/manual/automatic playback, basic controls,
   pause, blackout, and clean completion. Check invalid shows before output.
3. **Complete visual playback.** Add video source ranges, crossfade/wipe,
   named cues, separate operator/audience windows, and display-loss handling.
4. **Accompaniment and captions.** Implement the agreed manual-audio policies,
   inline and selected external caption profiles, device selection, and measured
   synchronization limits. Keep embedded video audio muted.
5. **Run observations and resilience.** Persist independent run records, test
   failure recovery and shutdown, and add replay only after the format can
   represent it completely.
6. **Distribution.** Produce signed/notarized macOS artifacts, Windows release
   bundles, and a documented Linux distribution target. Verify included Qt/media
   components, notices, fonts, fixtures, and applicable distribution obligations.
   Test the actual release artifacts on clean machines before declaring support.

Use focused controller tests with a fake clock and local media fixtures. Add
rendered image regression cases for transforms, captions, and transition
boundaries. Test missing or changed files, corrupt media, oversized images,
unsupported codecs, repeated navigation, cancellation, device/display loss,
run-write failure, and interruption during preparation and playback. Audio
regression files use 48 kHz and at least one second. Automated tests supplement
manual multi-monitor, high-DPI, audio-device, and packaged-app tests on each OS.

## Additional work beyond the prompt

None. This request creates the plan only; application development, dependency
changes, format changes, and release packaging belong to its implementation.
