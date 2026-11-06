# INTERACTION SPEC

> **TerraView24** : *Damage done by humans, measured against the norm*
>
> Part of the TerraView24 doc set. See `ARCHITECTURE.md` for the system overview.

The globe is the project's argument. If it stutters or the transitions read as two separate things happening, the analysis underneath stops getting credit. Treat this document as exacting.

---

## 1. State machine

Four states. All input gating falls out of this, which is why it is explicit state and not a boolean flag.

```
IDLE  ──click pin──>  FLYING_IN  ──>  PANEL_OPEN  ──dismiss──>  FLYING_OUT  ──>  IDLE
```

| State | Pin clicks | Dismiss clicks | Drag | Idle rotation |
|---|---|---|---|---|
| `IDLE` | accepted | ignored | enabled | running |
| `FLYING_IN` | **swallowed** | swallowed | disabled | stopped |
| `PANEL_OPEN` | **swallowed** | accepted | disabled | stopped |
| `FLYING_OUT` | **swallowed** | swallowed | disabled | stopped |

Transition states swallow all input. This is the requirement that other pins become unresponsive until the animation completes, and implementing it as state rather than a flag will save you when a loading state for the detail fetch is added later.

Live in `web/src/state/machine.ts`, backed by Zustand. Nothing else in the app is allowed to mutate the state field directly.

---

## 2. The open sequence

Total duration **1.4s**. One GSAP timeline, three parallel tracks.

```
t=0.00  ┌─ camera.flyTo: pin to centre, altitude increases (globe shrinks)
        ├─ frustum.xOffset: 0 -> +W/4  (globe slides left)
        └─ globe dim + desaturate post process
t=0.70  └─ panel: scale 0.3 -> 1, opacity 0 -> 1, origin = pin screen position
t=1.40  state -> PANEL_OPEN
```

**The 0.70s panel start is not optional.** It begins while the camera is still moving, at 50 percent through the flight. Waiting for `flyTo` to complete produces a visible dead beat, and that pause is the entire difference between "seamless" and "two things happened in sequence."

```ts
const tl = gsap.timeline({ onComplete: () => machine.set('PANEL_OPEN') });

tl.to(frustum, { xOffset: targetOffset, duration: 1.4, ease: 'power2.inOut' }, 0);
tl.to(dimState, { value: 1, duration: 1.0, ease: 'power1.out' }, 0);
tl.fromTo(panelEl,
  { scale: 0.3, opacity: 0 },
  { scale: 1, opacity: 1, duration: 0.6, ease: 'power3.out' }, 0.70);
```

`camera.flyTo` runs alongside with its own `duration: 1.4` and the same conceptual easing. Cesium owns its interpolation; do not try to drive the camera from GSAP.

---

## 3. Shifting the globe left

**Do not move the Earth.** Move the projection.

```ts
scene.camera.frustum.xOffset = value;  // positive shifts the view right, globe appears left
```

Tween `xOffset` from 0 to roughly a quarter of the canvas width in world units, in parallel with the flight. This is geometrically exact: the camera still points precisely at the pin, so the pin does not drift during the move.

The alternative, offsetting the flight destination's longitude, works but introduces a subtle rotation that makes the pin wander across the screen during the transition. Visible, and it undermines the feeling that the globe is a solid object.

Shrinking is simply a higher target altitude on the same `flyTo`. No separate scale operation.

---

## 4. Camera destination

```ts
camera.flyTo({
  destination: Cartesian3.fromRadians(pinLon, pinLat, FRAMING_ALTITUDE),
  orientation: { heading: 0.0, pitch: CesiumMath.toRadians(-90), roll: 0.0 },
  duration: 1.4,
  easingFunction: EasingFunction.QUADRATIC_IN_OUT
});
```

**The explicit `orientation` is mandatory.** After an arbitrary flight the globe's up vector is wherever interpolation left it. Without forcing heading 0, by the third or fourth pin the user has lost all sense of where on Earth they are.

`FRAMING_ALTITUDE` varies by event type. A 30 sq km fire and a 2000 sq km deforestation front need different framing. Derive it from the event's `area_km2` with sensible clamps.

---

## 5. Panel origin projection

The panel is a DOM element above the canvas, so it needs screen coordinates, not Cartesian.

```ts
const screenPos = SceneTransforms.worldToWindowCoordinates(scene, pinWorldPos);
panelEl.style.transformOrigin = `${screenPos.x}px ${screenPos.y}px`;
```

Capture this **once, at click time.** Do not track the pin during the flight: the pin is moving, the per frame math is expensive, and it looks worse than a fixed origin.

**Guard it.** `worldToWindowCoordinates` returns `undefined` in some cases and, worse, returns a plausible looking but wrong coordinate for points behind the globe. Run the occlusion check from section 6 first, and fall back to a centre screen origin when it fails.

---

## 6. Front hemisphere click gating

Cesium billboards do not depth test against terrain by default, so a pin on the far side of the globe is still pickable. Two fixes, use both.

```ts
billboard.disableDepthTestDistance = 0;  // respect globe occlusion
```

And an explicit angular check, because you also want to reject pins near the limb that are technically visible but too oblique to click comfortably:

```ts
const toPin = Cartesian3.subtract(pinPos, camera.position, scratchA);
const toCentre = Cartesian3.subtract(Cartesian3.ZERO, camera.position, scratchB);
const angle = Cartesian3.angleBetween(toPin, toCentre);
const clickable = angle < CLICK_ANGLE_THRESHOLD;  // start at 0.6 rad, tune
```

Reuse scratch `Cartesian3` objects. This runs for many pins per frame and allocating in the render loop will cause visible GC stutter.

**Feed the same check into pin opacity.** Pins should visibly fade out as they approach the limb, before they become unclickable. A user must never click something that silently does nothing. The fade is the affordance that teaches the rule without explaining it.

---

## 7. Idle rotation

Runs **only** in `IDLE`.

- Natural pace: a full rotation in roughly 120 seconds. Slow enough to read as ambient, fast enough to be noticed.
- **Drag cancels rotation immediately.** No easing on cancel; the user's input must feel direct.
- **Rotation resumes 3 seconds after the last input**, easing back in over roughly 1 second. Without the delay it fights the user.
- When leaving `IDLE` for `FLYING_IN`, rotation **eases out over about 400ms** rather than stopping dead. An abrupt stop is the single most noticeable roughness in this kind of interface.

Implement by advancing camera rotation in the `preRender` tick, multiplied by an eased `rotationWeight` scalar from 0 to 1 that GSAP tweens. Never apply rotation inside a `setInterval`; it will desync from the render loop and jitter.

---

## 8. Dismiss and return

Dismiss triggers on a click anywhere outside the panel, or on the close button. Clicks inside the panel do nothing.

**Return sequence, 0.8s.** Faster than the open, as return transitions should be.

```
t=0.00  ┌─ panel: scale 1 -> 0.3, opacity 1 -> 0  (0.35s, power2.in)
        ├─ frustum.xOffset: +W/4 -> 0
        ├─ globe dim -> 0
        └─ camera: altitude back to IDLE_ALTITUDE
t=0.80  state -> IDLE, rotation eases back in
```

### Option A: stay put

The camera **does not return to its pre click orientation.** It stays over the region of the pin just viewed, returns to idle altitude and centre framing, and resumes idle rotation from there.

Rationale: over a session the user works their way around the globe. Snapping back to a fixed home view every time would make ten pins into ten round trips, and idle rotation means the globe is never in the same place twice anyway, so the "home" that snapping back preserves does not actually exist.

Do **not** store and restore pre click camera state. It is not needed under option A.

---

## 9. Other pins during `PANEL_OPEN`

Related pins stay lit; unrelated pins fade.

"Related" means, in priority order:

1. The same `event_id`, obviously.
2. Pins inside the open event's `bbox` or within a proximity radius.
3. When `intersects_species_range` is true, **the species range polygon stays fully visible** while surrounding pins fade.

Point 3 is the one worth building carefully. A deforestation pin opening inside a Sumatran tiger range, with the range polygon still lit behind the panel, makes the spatial relationship legible without the user having to find and toggle a layer. That is the analytical join from DETECTION_SPEC made visible in a single frame, and it is the best interaction moment in the whole design.

Unrelated pins fade to roughly 0.15 opacity. Do not hide them entirely; the user should retain a sense of global context.

---

## 10. Interruption handling

Under the gating in section 1, pin clicks during transitions are swallowed, so true mid flight interruption should not occur. Build the cancellation path anyway:

- Hold a reference to the active GSAP timeline.
- On any forced transition, `timeline.kill()` and `camera.cancelFlight()` together.
- Never allow two timelines to touch `frustum.xOffset` at once. It is a single scalar and concurrent tweens will fight, producing a jitter that is extremely hard to diagnose later.

---

## 11. Performance rules

Non negotiable. A stuttering globe discredits the analysis.

- `BillboardCollection` for interactive pins. **Never individual `Entity` objects**; entities are convenient and will not survive a few thousand pins.
- `PointPrimitiveCollection` or a heatmap for the `SUSPECTED` tier. Those pins are not interactive, so they must not carry interactive machinery.
- Target 60fps on mid range hardware with 3000 pins visible. Test on an integrated GPU laptop, not a dev machine.
- Reuse scratch objects in every per frame computation.
- Request render mode (`requestRenderMode: true`) is tempting for battery but conflicts with continuous idle rotation. Leave it off, and compensate by keeping the primitive count down.
- Species range polygons at full resolution will destroy frame rate. Simplify aggressively at pipeline time, per DATA_CONTRACTS.

---

## 12. Build order for the frontend

Build the interaction against **fixture JSON matching DATA_CONTRACTS**, before any real data exists.

1. Cesium viewer, imagery, lighting, idle rotation with the 3 second resume.
2. Billboard pins from a fixture file. Hemisphere gating and limb fade.
3. The state machine with no animation; states flip instantly. Confirm gating is correct in isolation.
4. The open timeline: `flyTo`, `xOffset`, dim.
5. Panel entrance with projected origin.
6. The return sequence.
7. Related and unrelated pin treatment.
8. Real data swapped in for fixtures. **Nothing above should need to change.**

Step 3 before step 4 is important. Debugging gating logic through a 1.4 second animation is miserable; debugging it with instant transitions takes minutes.

The durations in this document are starting points. They only become obvious when you click them. Expect to tune the 1.4s and the 0.70s offset by feel once it is running.

---

## 13. Freshness chrome

The globe is the project's argument, and a globe that overstates its own freshness undermines it. The UI chrome states the age and health of what is on screen, in plain words, and never uses "real time" or "live" for anything that has not been measured.

- **Data age.** Show how old the newest data is, from `meta.json` `data_as_of` (satellite acquisition time), not from the time of the last pipeline run. Both numbers can be shown. They are different facts.
- **Staleness.** When the age of `heartbeat.json` `written_at` exceeds its `stale_after_minutes`, say so plainly ("Data is older than expected. The update job may have stopped."). The pipeline owns that threshold, the page only reports it. A stale globe that admits it is stale is trustworthy.
- **Degraded corroboration.** When `meta.corroboration_mode` is `degraded`, say that independent cross sensor checking is no longer available and that corroboration now rests on repeated passes of one sensor family.
- **Truncation.** When `meta.counts.shown` is below `total_active`, say "showing 3000 of 7412 active detections".
- **Unscored events.** A `sigma` of `null` renders as "not scored against a norm", with the reason from `baseline_quality`. Never as 0 or as an empty field.
- **Latency.** Show the measured end to end latency only once `meta.latency.measured` is true. Until then, show nothing about latency.
- **Load failure.** If a payload fails to load or the major `pipeline_version` does not match, show a clear message rather than an empty globe.

This chrome is part of the claim discipline, not decoration. Build it against the fixtures for each state listed in `DATA_CONTRACTS.md`, before real data exists.
