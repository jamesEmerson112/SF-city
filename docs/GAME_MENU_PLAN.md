# Escape menu and safe exit

Status: delivered, September 6, 2026. The design below is implemented; measured
acceptance and remaining limits are recorded at the end and in the
[patch notes](PATCH_NOTES.md#2026-09-06---escape-menu-and-confirmed-recovery-exit).

Add a game-style vertical options bar opened with Escape, so users can return to
the city, access familiar controls, and close the application without abandoning
an unfinished save. This is independent of the
[citizen coordinate recorder and newcomer fix](CITIZEN_COORDINATE_PLAN.md).

Delivered defaults: opening the menu pauses the city; returning restores its
prior playback state; the main exit action writes a separate recovery checkpoint
before closing. These defaults were implemented after approval to proceed.

## Baseline before implementation

- Before this change, [main.gd](../viewer/main.gd) handled Escape by cancelling dragging.
  The handler sits behind startup and text-input focus checks.
- Window close calls the viewer's close method, emits final aggregate metrics,
  disconnects its simulation client, then exits Godot.
- [launch.py](../civic_center/launch.py) owns the worker lifecycle. After the viewer
  exits it shuts down the worker, closes output capture, stops hardware monitoring,
  and stops telemetry before finalizing the run JSON in the delivered flow.
- [worker.py](../civic_center/worker.py) cancels an unfinished save, load or
  population preparation when it receives shutdown. Closing previously did not
  automatically save the current day.
- Saves already use detached completed-tick captures and validated atomic file
  replacement. Only the final save acknowledgement confirms completion; a
  progress message or an existing file does not. See the
  [command protocol](../contracts/CIVIC_PROTOCOL.md).
- Hardware monitoring and log capture already have bounded shutdown waits.
  Ordinary filesystem writes are not guaranteed to finish within a fixed time.

This baseline motivated the save-before-close flow and visible handling of slow
or unsuccessful operations described below.

## 1. Menu layout and actions

Use a dim, inexpensive overlay with a left-side vertical bar, initially about
360 logical pixels wide and clamped to the viewport. Avoid a blur or a second
render of the city. Stack clearly labelled buttons; scroll on short windows and
at larger UI scales so the exit controls remain reachable.

| Entry | Intended behavior |
| --- | --- |
| Return to city | Close the menu and restore the appropriate playback/input state. |
| Save day | Save the existing quick slot and remain in the menu; disclose that it replaces the prior quick save. |
| Display | A submenu using existing window mode and UI-scale settings. |
| Controls | A compact keyboard/mouse reference, including Escape. |
| Performance | Return to the city and open the existing console, restoring playback as Return does. |
| Save & Exit | Save the latest exit recovery, then start orderly application closure. |

Show the active save/close status in the bar. Put **Exit without saving** in the
exit/error subpage, with an explicit confirmation; it is not the initial keyboard
focus or the default response to failure.

The overlay does not resize the city viewport, change camera mode, clear the
selected citizen, or rearrange the diagnostics dock. Layer it above the current
loading and diagnostics interfaces. Existing window and scale preferences remain
local presentation settings.

The exit recovery uses the worker's configured save directory and protocol slot
**exit-recovery**, producing **exit-recovery.json**. The protocol slot has no
extension; the worker adds it. This never replaces **quick.json**.
A successful later safe exit may atomically replace the previous recovery.
Recovery represents the complete simulation at the acknowledged capture tick,
including a changed roster and playback speed; it is not an individual trajectory
recording. It is saved paused, so loading it starts with an inspectable paused
city. Document loading it through the existing launcher's load-file option.
Do not silently load recovery on every launch or add a new checkpoint format.

## 2. Escape, focus and pause behavior

Handle Escape before ordinary camera and text-field guards, while preserving the
existing automation/probe input isolation. An open dropdown or nested dialog gets
the first Escape; the next returns to the root menu; Escape at the root behaves
like Return. Escape never exits directly.

On opening:

1. Cancel dragging, expose the pointer if necessary, and capture the prior valid
   focus, camera/follow state and authoritative playback state.
2. Block world clicks, wheel zoom, selection, movement, rotation and gameplay
   shortcuts. Gate both event handlers and physical-key polling in the main
   viewer and walking camera; an overlay alone cannot stop polling.
3. Request a pause through the authoritative command API, and show **Pausing...**
   until its acknowledgement and corresponding complete state arrive.
4. Keep networking, decoding, telemetry, loading, menu input and save progress
   processing. Do not pause the entire Godot scene tree or disable all GUI input.

New menu buttons support Tab/Shift-Tab, Up/Down, Enter and visible focus. Start
focus on Return, contain navigation within the active menu/subpage, and restore
the previous valid focus on return. Require release of held movement keys before
camera navigation resumes. Swallow the click/key that closes the menu.

If the day was already paused, Return leaves it paused. Restore only a pause
introduced by this menu. Live population changes replace the transport session
while retaining the day: carry menu-owned pause intent across a validated
population-adjustment handoff, correlated by operation, prior/new session and
roster revision. Matching world identity alone is insufficient. Otherwise Return
could strand a previously running city paused after population growth.

A load, reset or preset restart replaces playback state: wait for its terminal
result and complete new state, establish the new baseline, then pause that
session. Do not apply the previous world's resume flag. Live population changes
must also settle before exit saving begins.

Opening the menu blocks camera movement immediately. While an earlier operation
settles or the worker acknowledges pause, label the transition honestly rather
than claiming the simulation has already stopped. Returning during pause
negotiation must reconcile late replies so the city is not accidentally left
paused or resumed.

Recorded replay uses its existing local pause state. Loading or startup failure
must still offer the menu without requiring a camera, HUD or live worker;
unavailable day/save actions show a short reason.

## 3. A single save-and-exit coordinator

Add a focused viewer coordinator with explicit states:
idle, settling operation, pausing, saving, save error, closing.
Route the menu action and ordinary window-close/Alt-F4 request through it.
Repeated clicks, Escape presses or OS close requests cannot start duplicate saves
or bypass an operation already underway.

For a ready, launcher-owned live session:

1. Block new simulation-changing UI actions. Resolve any pending save, load or
   population operation and its scene handoff before capturing a new exit save.
   Do not queue unlimited retries on an operation-pending rejection.
2. Pause the settled authoritative session and wait for the matching complete
   state. Use the worker tick, not an interpolated presentation tick.
3. Send the recovery save and retain its request ID, action, session and slot.
   Expose request-correlated progress to the menu; the current generic status
   text alone is insufficient.
4. Accept only the matching final successful acknowledgement. Record its
   captured tick and slot. Ignore unrelated, stale or duplicated acknowledgements.
   New-session replacement invalidates a pending close decision.
5. Persist local display preferences and emit one bounded structured exit intent
   with the save outcome, followed by exactly one final viewer metrics record.
   Show **Closing...**, disconnect this viewer and quit through the existing
   close method.
6. The launcher performs worker/child cleanup, output draining, hardware shutdown
   and final atomic run-log persistence before the launcher process returns.

The game window may disappear shortly before launcher cleanup finishes.
The final run status can only be known after process exit and cleanup; do not
display **All logs saved** before that happens. A missing launcher connection
must not be presented as confirmed log persistence.

Preserve the single process owner. A standalone viewer closes only itself and
does not stop an independently started worker. Replay exits without claiming a
simulation checkpoint was saved. During loading, Exit cancels preparation and
uses existing launcher cleanup; explain that there is no ready day to save.
Automation's explicit successful/error termination remains noninteractive.

The initial flow targets the normal single-viewer application. It does not claim
to lock out independent clients issuing their own simulation commands. Session
changes and operation conflicts must be detected; a future shared-control mode
would require an explicit worker-side ownership/barrier contract.

## 4. Slow operations, errors and cancellation

Keep the UI processing while waiting. Show elapsed time and the current operation,
with a slow-operation notice after 15 seconds. This threshold is a UI
notice, not a save deadline or measured capacity promise. Valid large saves may
take considerably longer.

- A save error leaves the application open. Offer Retry, Return to menu, or an
  explicit Exit without saving. Preserve the prior valid recovery on write failure.
- Loss of connection or acknowledgement means **Save outcome unknown**, since
  the file may have been replaced before the reply arrived. Never infer success
  from file existence or automatically kill the application.
- A timeout must not silently turn Save & Exit into an unsaved exit. Continue
  waiting or let the user choose a clearly labelled alternative.
- Cancelling the exit intent does not claim to cancel or roll back an in-flight
  save. Let it settle, ignore its reply for closing purposes, and reconcile pause
  state. A save may already have completed before cancellation.
- Exit without saving skips a new recovery capture, then uses normal cleanup.
  It can cancel preparation, but cannot undo a save replacement already committed.
- Once final closure begins, disable Return/Retry and finish one cleanup sequence.
  Forced process termination remains a launcher fallback, and its use must be
  recorded as forced/incomplete rather than silently reported as graceful.

Apply bounded drain/join waits to owned processes and threads, preserve independent
cleanup attempts on error, and report missing final capture/hardware results.
A clean close cannot guarantee recovery from power loss, OS termination, or
filesystem failure. Do not promise lossless recording under those conditions.

## 5. Diagnostics and product evidence

Keep the existing aggregate JSON report; add a versioned bounded exit summary
and a small set of lifecycle events: reason, save intent/outcome, captured tick,
stage durations, viewer/worker exit codes, graceful/forced cleanup and unavailable
or incomplete diagnostics. Preserve earlier failures when choosing final status.
Do not include coordinates, credentials or complete checkpoints in this report.

Expose persistence failure rather than treating a swallowed log-write error as
success. Add menu-open/closing state to performance phase context so paused menu
frames are not mixed into ordinary city-interaction comparisons.

If the coordinate recorder is implemented first, drain its bounded writer and
record any incomplete tail during worker shutdown. This menu does not require
that planned recorder to exist.

The product impact is discoverable controls, recoverable progress and explicit
save outcomes. No FPS improvement, time saving or zero-data-loss claim is
established by this feature. The [patch notes](PATCH_NOTES.md) and
[aggregate evidence](benchmarks/2026-09-06-game-menu.json) separate measured menu
response, request-to-save-ACK, close dispatch, observed viewer exit and launcher
completion. Physical window disappearance was not timestamped directly.

## 6. Implementation and acceptance

| Step | Work and verification |
| --- | --- |
| 1 | Add the vertical menu and modal input/focus gates. Verify no world input leaks and no camera/layout changes. |
| 2 | Add request-aware pause/save/exit coordination, recovery slot and normal-close routing. |
| 3 | Extend launcher/logging exit outcomes and verify thread/process completion without a second lifecycle owner. |
| 4 | Exercise failures and rendered layouts, then document controls, recovery and measured limits. |

Extend the existing injected-input and workspace layout checks, plus focused
worker/save/launcher tests:

- Overhead, walk, follow and 2D; running, paused and replay; focus in search and
  population inputs; held WASD/QE, drag, wheel, repeated Escape and nested menus.
- Minimum 960 x 540, 1280 x 720, standard desktop and ultrawide layouts at
  100%, 125% and 150% scale; keyboard reachability and fullscreen changes.
- Successful recovery loads the acknowledged tick, roster and speed; quick save
  remains untouched. Existing checkpoint versions remain readable.
- Slow/error/unknown saves, read-only/full storage, retries and cancelled exit;
  pending load/population/save; stale replies, reconnect and duplicate close.
- Loading cancellation, startup failure, standalone viewer and automation;
  no orphaned owned worker/preparation process and no save writer surviving
  confirmed worker shutdown. Remove a cancelled writer's temporary sibling only
  after its owned process has stopped and its exact temporary path is verified;
  do not delete another operation's files or the previous completed checkpoint.
- Exactly one final viewer report; parseable final run JSON with actual child
  exit outcomes; bounded capture/sensor timeouts and log-write failure reported.
- Rendered normal-close and Save & Exit flows in both 2D and 3D; a portable pilot
  smoke check using its bundled runtimes.

### Delivered acceptance evidence

- Python application suite: 839 passed, 1 skipped in 45.65 seconds.
- Eight Godot checks passed: menu layout/input, coordinator races, transport close,
  workspace input/layout, metrics, scene adaptation and telemetry.
- Eight rendered trials passed across 3D/2D menu and OS close, a pending population
  change, failed-save handling, a 1,000-resident city and a bundled portable pilot.
  Successful checkpoints reloaded at the acknowledged tick with quick saves
  unchanged; worker shutdown was acknowledged and owned processes stopped.
- The pilot-only package verified 275 files / 210,453,089 bytes. Native helpers
  were omitted to exercise the supported fallback.
- Final rendered normal and error menus were visually inspected. Headless layout
  checks include 960 x 540 through 5120 x 1440 and all three UI scales.

The tests exercise injected filesystem failures and synthetic transport races;
they do not certify physical disk-full, power-loss, or every OS shutdown scenario.
Dedicated physical ultrawide/mixed-DPI testing and multi-client ownership remain
outside this delivery. A single city save took 24.839 seconds; no FPS, capacity,
or before/after optimization claim follows from these trials. See the
[aggregate report](benchmarks/2026-09-06-game-menu.json) for exact boundaries,
per-trial sources and limitations. The coordinate recorder remains a separate
planned feature.
