// Vanilla-JS read-aloud player. Ports the design proven in v1's usePlayer.ts
// (Tauri/React) to a plain browser client talking to this app's HTTP API
// instead of Tauri's invoke() IPC. See LEARNINGS.md for why each piece exists.
(function () {
  "use strict";
  if (typeof window.ARTICLE_ID === "undefined") return; // not an article page

  const ARTICLE_ID = window.ARTICLE_ID;
  const LOOKAHEAD = 2;
  const AUTO_SCROLL_IDLE_MS = 2500;
  // Read from the rendered speed buttons rather than hardcoding a second
  // copy of components.py's SPEEDS list here (used by the [ / ] shortcuts).
  const SPEEDS = Array.from(document.querySelectorAll(".speed-btn")).map((b) => parseFloat(b.dataset.speed));

  // On narrow screens the TOC stacks above the article (see style.css's
  // 900px breakpoint), so a long table of contents would push the article
  // itself below the fold -- collapse the <details> at load there. Desktop
  // keeps the server-rendered `open` (a sticky, always-expanded sidebar).
  // Progressive enhancement: with JS disabled it just stays expanded.
  const tocDetails = document.querySelector(".toc-sidebar");
  if (tocDetails && tocDetails.tagName === "DETAILS" && window.matchMedia("(max-width: 900px)").matches) {
    tocDetails.open = false;
  }

  // ---- DOM: collect every segment element once, indexed by its data-seg ----
  const segEls = [];
  const segTypes = [];
  document.querySelectorAll("[data-seg]").forEach((el) => {
    const idx = parseInt(el.getAttribute("data-seg"), 10);
    segEls[idx] = el;
    segTypes[idx] = el.getAttribute("data-type");
  });
  const totalSegments = segEls.length;

  // ---- state ----
  let audioCtx = null;
  let currentSource = null;
  let wordTimer = null;
  const cacheMap = new Map(); // segmentIndex -> {buffer, wordTimings, duration}
  const pending = new Map(); // segmentIndex -> in-flight fetch Promise (see fetchSegment)
  let gen = 0; // monotonic generation counter -- see scheduleWordHighlights/playSegment
  let currentSegment = -1;
  let currentWordEl = null;
  let playing = false;
  let voice = window.INITIAL_VOICE || "af_heart";
  let speed = window.INITIAL_SPEED || 1.0;
  let userScrolling = false;
  let userScrollTimer = null;
  // Playhead: when the current segment's AudioBufferSourceNode started,
  // in the AudioContext's own clock (ctx.currentTime), so elapsed time is
  // always just `ctx.currentTime - segmentStartedAt` -- recomputed on every
  // seek so it stays correct relative to the *new* source's start point.
  let segmentStartedAt = 0;
  let segmentDuration = 0;
  let playheadDragging = false;

  // ---- document-wide duration estimate, for the playhead's elapsed/total
  // labels (see docElapsedAndTotal below). Audio is generated lazily, one
  // segment at a time -- there's no whole-document duration to know without
  // either generating every segment upfront (slow for a long article) or
  // estimating. Word-count-based estimate per segment, refined to the real
  // duration as each one actually gets generated; recordRealDuration also
  // calibrates the words/sec rate itself from that real data, so later
  // not-yet-generated estimates get more accurate as you listen. ----
  const DEFAULT_WORDS_PER_SECOND = 2.5; // ~150 wpm at 1.0x, typical narration pace
  let observedBaseWordsPerSecond = null; // calibrated from the first real segment we see
  const segmentDurationIsReal = segEls.map(() => false);

  function wordCountOf(index) {
    if (segTypes[index] === "code" || !segEls[index]) return 0;
    return (segEls[index].textContent.match(/\S+/g) || []).length;
  }

  function estimateDuration(words) {
    const baseWps = observedBaseWordsPerSecond || DEFAULT_WORDS_PER_SECOND;
    return words / baseWps / speed;
  }

  const segmentDurations = segEls.map((_, i) => estimateDuration(wordCountOf(i)));

  function recordRealDuration(index, realDuration) {
    segmentDurations[index] = realDuration;
    segmentDurationIsReal[index] = true;
    const words = wordCountOf(index);
    if (words > 0 && realDuration > 0) observedBaseWordsPerSecond = (words / realDuration) * speed;
  }

  function recomputeEstimatesForCurrentSpeed() {
    for (let i = 0; i < segmentDurations.length; i++) {
      if (!segmentDurationIsReal[i]) segmentDurations[i] = estimateDuration(wordCountOf(i));
    }
  }

  function docElapsedAndTotal(withinSegElapsed) {
    let elapsedBefore = 0;
    for (let i = 0; i < currentSegment; i++) elapsedBefore += segmentDurations[i] || 0;
    const total = segmentDurations.reduce((a, b) => a + (b || 0), 0);
    return { elapsed: elapsedBefore + Math.max(0, withinSegElapsed), total };
  }

  // Which segment a document-wide time target falls in -- "jump to a chunk"
  // only needs a segment index (jumpTo() already generates-on-demand and
  // plays whatever segment you jump to, exactly like clicking a TOC entry or
  // a paragraph does), not a precise mid-segment offset. Walks cumulative
  // estimated/real durations rather than segment *count*, so the position
  // roughly tracks actual speaking time even though segments vary in length.
  function segmentIndexAtTime(targetSeconds) {
    let acc = 0;
    for (let i = 0; i < segmentDurations.length; i++) {
      acc += segmentDurations[i] || 0;
      if (targetSeconds <= acc) return i;
    }
    return Math.max(0, segmentDurations.length - 1);
  }

  function getAudioContext() {
    if (!audioCtx || audioCtx.state === "closed") {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtx;
  }

  // ---- iOS silent-switch unlock ----
  // iOS Safari puts pages that only use the Web Audio API into the "ambient"
  // audio session category, which the hardware ring/silent switch mutes.
  // Playing any HTML <audio> element (even silent) flips the page into the
  // "playback" category for the rest of the session, so subsequent
  // AudioBufferSourceNode playback is audible with the switch on silent too.
  // Must run synchronously inside a real user-gesture handler.
  let audioUnlocked = false;
  function unlockAudio() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    getAudioContext().resume().catch(() => {});
    const el = document.getElementById("ios-audio-unlock");
    if (el) el.play().catch(() => {});
  }
  document.addEventListener("pointerdown", unlockAudio, { once: true, passive: true });
  document.addEventListener("keydown", unlockAudio, { once: true });

  // ---- fetch + cache (in-memory, per-page; separate from the server disk cache:
  // this one saves a redundant HTTP round-trip within one page session, the disk
  // cache saves the actual TTS generation across sessions/devices) ----
  function fetchSegment(index) {
    if (index < 0 || index >= totalSegments) return Promise.resolve();
    if (cacheMap.has(index)) return Promise.resolve();
    if (segTypes[index] === "code") return Promise.resolve(); // never spoken
    // If this segment is already being fetched (e.g. lookahead prefetch kicked it
    // off, and playSegment() now needs the same segment right away), return the
    // SAME in-flight promise rather than just checking-and-bailing -- otherwise a
    // caller awaiting this call would resolve immediately while the real fetch is
    // still pending, see an empty cache, and wrongly treat the segment as
    // unplayable (this cascaded through an entire document in milliseconds during
    // manual testing before the fix).
    if (pending.has(index)) return pending.get(index);

    const promise = (async () => {
      try {
        const qs = `?voice=${encodeURIComponent(voice)}&speed=${speed}`;
        const [audioResp, timingsResp] = await Promise.all([
          fetch(`/api/tts/${ARTICLE_ID}/${index}${qs}`),
          fetch(`/api/tts/${ARTICLE_ID}/${index}/timings${qs}`),
        ]);
        if (!audioResp.ok || !timingsResp.ok) throw new Error("tts fetch failed");
        const arrayBuffer = await audioResp.arrayBuffer();
        const timings = await timingsResp.json();
        const audioBuffer = await getAudioContext().decodeAudioData(arrayBuffer);
        cacheMap.set(index, { buffer: audioBuffer, wordTimings: timings.word_timings, duration: timings.duration });
        recordRealDuration(index, timings.duration);
      } catch (e) {
        console.error(`TTS error for segment ${index}:`, e);
      } finally {
        pending.delete(index);
      }
    })();
    pending.set(index, promise);
    return promise;
  }

  function stopAudio() {
    if (currentSource) {
      try {
        currentSource.onended = null;
        currentSource.stop();
        currentSource.disconnect();
      } catch (_) {}
      currentSource = null;
    }
    if (wordTimer) {
      clearTimeout(wordTimer);
      wordTimer = null;
    }
  }

  // ---- word / sentence highlighting ----
  function setWordSpans(el) {
    if (el.dataset.wordsRendered) return;
    const words = JSON.parse(el.getAttribute("data-words") || "[]");
    el.dataset.originalHtml = el.innerHTML;
    el.innerHTML = words.map((w, i) => `<span class="word" data-w="${i}">${escapeHtml(w)}</span>`).join(" ");
    el.dataset.wordsRendered = "1";
  }

  function restoreOriginal(el) {
    if (el && el.dataset.wordsRendered) {
      el.innerHTML = el.dataset.originalHtml;
      delete el.dataset.wordsRendered;
    }
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  // ---- audio-only mode's "now playing" panel: mirrors whatever the main
  // document has for the active segment (word spans/highlighting included),
  // so it stays in sync for free instead of tracking word state twice ----
  const nowPlayingEl = document.getElementById("now-playing-text");
  function syncNowPlaying() {
    if (!nowPlayingEl) return;
    const el = currentSegment >= 0 ? segEls[currentSegment] : null;
    nowPlayingEl.innerHTML = el ? el.innerHTML : "Nothing playing yet";
  }

  function setActiveSegment(index) {
    if (currentSegment >= 0 && segEls[currentSegment]) {
      segEls[currentSegment].classList.remove("sentence-active");
      restoreOriginal(segEls[currentSegment]);
    }
    currentSegment = index;
    currentWordEl = null;
    if (index >= 0 && segEls[index]) {
      const el = segEls[index];
      el.classList.add("sentence-active");
      if (segTypes[index] === "paragraph") setWordSpans(el);
      maybeAutoScroll(el);
    }
    updateDocSeekUI(0);
    syncNowPlaying();
    postProgress();
  }

  function setActiveWord(el, wordIdx) {
    if (currentWordEl) currentWordEl.classList.remove("word-active");
    const wordEl = el.querySelector(`.word[data-w="${wordIdx}"]`);
    if (wordEl) {
      wordEl.classList.add("word-active");
      currentWordEl = wordEl;
    }
    syncNowPlaying();
  }

  function scheduleWordHighlights(el, wordTimings, startedAt, segIndex, myGen) {
    const ctx = audioCtx;
    const scheduleNext = (wordIdx) => {
      if (gen !== myGen) return;
      if (wordIdx >= wordTimings.length) return;
      const timing = wordTimings[wordIdx];
      const elapsed = ctx.currentTime - startedAt;
      const delay = (timing.start - elapsed) * 1000;
      wordTimer = setTimeout(() => {
        if (gen !== myGen || currentSegment !== segIndex) return;
        setActiveWord(el, wordIdx);
        scheduleNext(wordIdx + 1);
      }, Math.max(0, delay));
    };
    scheduleNext(0);
  }

  // ---- auto-scroll with manual-scroll override ----
  window.addEventListener("scroll", () => {
    userScrolling = true;
    clearTimeout(userScrollTimer);
    userScrollTimer = setTimeout(() => { userScrolling = false; }, AUTO_SCROLL_IDLE_MS);
  }, { passive: true });

  function maybeAutoScroll(el) {
    if (userScrolling) return;
    const rect = el.getBoundingClientRect();
    const inView = rect.top >= 80 && rect.bottom <= window.innerHeight - 120;
    if (!inView) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // ---- playhead: elapsed/duration for whatever segment is currently
  // playing, plus a seek bar to jump within it ----
  const playheadSeek = document.getElementById("playhead-seek");
  const playheadElapsedEl = document.getElementById("playhead-elapsed");
  const playheadDurationEl = document.getElementById("playhead-duration");

  // This seek bar/labels are scoped to the *current segment only*
  // (0..withinSegDuration) -- dragging it calls seekWithinSegment. The
  // document-wide bar below is the separate #doc-seek row.
  function updatePlayheadUI(withinSegElapsed, withinSegDuration) {
    if (!playheadSeek) return;
    playheadSeek.max = String(withinSegDuration || 0);
    playheadSeek.disabled = !withinSegDuration;
    if (playheadDragging) return; // don't fight the user's own drag position
    playheadElapsedEl.textContent = formatTime(withinSegElapsed);
    playheadSeek.value = String(withinSegElapsed);
  }

  if (playheadSeek) {
    ["pointerdown", "touchstart"].forEach((evt) => {
      playheadSeek.addEventListener(evt, () => { playheadDragging = true; });
    });
    playheadSeek.addEventListener("input", () => {
      playheadElapsedEl.textContent = formatTime(parseFloat(playheadSeek.value));
    });
    playheadSeek.addEventListener("change", () => {
      playheadDragging = false;
      seekWithinSegment(parseFloat(playheadSeek.value));
    });
  }

  // ---- document-wide bar: elapsed/estimated-total across the whole
  // article, and a coarse-grained "jump to any sentence" scrubber. Unlike
  // the per-segment bar above, dragging this doesn't need sample-accurate
  // seeking -- landing on the nearest *segment* (segmentIndexAtTime) and
  // calling jumpTo() is exactly what clicking a TOC entry or a paragraph in
  // the document already does, generating that segment's audio on demand. ----
  const docSeek = document.getElementById("doc-seek");
  const docElapsedEl = document.getElementById("doc-elapsed");
  const docDurationEl = document.getElementById("doc-duration");
  let docSeekDragging = false;

  function updateDocSeekUI(withinSegElapsed) {
    if (!docSeek) return;
    const { elapsed, total } = docElapsedAndTotal(withinSegElapsed);
    docSeek.max = String(total || 0);
    docSeek.disabled = !total;
    docDurationEl.textContent = formatTime(total);
    if (docSeekDragging) return;
    docElapsedEl.textContent = formatTime(elapsed);
    docSeek.value = String(elapsed);
  }

  if (docSeek) {
    ["pointerdown", "touchstart"].forEach((evt) => {
      docSeek.addEventListener(evt, () => { docSeekDragging = true; });
    });
    docSeek.addEventListener("input", () => {
      docElapsedEl.textContent = formatTime(parseFloat(docSeek.value));
    });
    docSeek.addEventListener("change", () => {
      docSeekDragging = false;
      jumpTo(segmentIndexAtTime(parseFloat(docSeek.value)));
    });
  }

  function tickPlayhead() {
    if (playing && currentSource && audioCtx) {
      const elapsed = Math.max(0, Math.min(audioCtx.currentTime - segmentStartedAt, segmentDuration));
      updatePlayheadUI(elapsed, segmentDuration);
      updateDocSeekUI(elapsed);
    }
    requestAnimationFrame(tickPlayhead);
  }
  requestAnimationFrame(tickPlayhead);
  updateDocSeekUI(0); // show the estimated total right away, before playback starts

  // ---- playback session (generation-counter guarded, ported from usePlayer.ts) ----
  async function playSegment(index, myGen) {
    if (gen !== myGen) return;
    if (index >= totalSegments) {
      setActiveSegment(-1);
      segmentDuration = 0;
      updatePlayheadUI(0, 0);
      // Article finished -- show the doc-wide bar as fully elapsed rather
      // than 0 (docElapsedAndTotal has no "before segment -1" to sum).
      if (docSeek) {
        docSeek.value = docSeek.max;
        docElapsedEl.textContent = formatTime(parseFloat(docSeek.max || "0"));
      }
      setPlayingUI(false);
      return;
    }

    setActiveSegment(index);
    for (let i = 1; i <= LOOKAHEAD; i++) fetchSegment(index + i);

    if (segTypes[index] === "code") {
      if (gen === myGen) await playSegment(index + 1, myGen);
      return;
    }

    if (!cacheMap.has(index)) await fetchSegment(index);
    if (gen !== myGen) return;
    const entry = cacheMap.get(index);
    if (!entry) {
      // Segment could not be spoken at all (e.g. crashed even after the
      // retry/bisect fallback server-side) -- skip it rather than stall.
      if (gen === myGen) await playSegment(index + 1, myGen);
      return;
    }

    try {
      const ctx = getAudioContext();
      if (ctx.state === "suspended") {
        await ctx.resume();
        if (gen !== myGen) return;
      }
      stopAudio();
      const source = ctx.createBufferSource();
      source.buffer = entry.buffer;
      source.connect(ctx.destination);
      currentSource = source;
      const startedAt = ctx.currentTime;
      segmentStartedAt = startedAt;
      segmentDuration = entry.duration;
      updatePlayheadUI(0, entry.duration);
      updateDocSeekUI(0);
      source.start();
      scheduleWordHighlights(segEls[index], entry.wordTimings, startedAt, index, myGen);

      await new Promise((resolve) => { source.onended = resolve; });
      if (gen !== myGen) return;
      currentSource = null;
      await playSegment(index + 1, myGen);
    } catch (e) {
      console.error("Audio playback error:", e);
      if (gen === myGen) await playSegment(index + 1, myGen);
    }
  }

  // Reposition playback within the currently-active segment (dragging the
  // playhead), rather than starting a whole new session from segment 0's
  // lookahead the way jumpTo()/startSession() do. Web Audio has no native
  // seek -- an AudioBufferSourceNode plays the buffer it's given starting
  // from source.start()'s *offset* argument, so seeking means swapping in a
  // fresh source at the new offset. Always resumes playback (matches how
  // dragging a scrubber reads on most audio players); nulling the old
  // source's onended before stopping it, exactly like stopAudio(), keeps it
  // from also (wrongly) advancing to the next segment on its own.
  function seekWithinSegment(offsetSeconds) {
    if (currentSegment < 0) return;
    const entry = cacheMap.get(currentSegment);
    if (!entry) return;
    const myGen = gen;
    const ctx = getAudioContext();
    const clamped = Math.max(0, Math.min(offsetSeconds, Math.max(0, entry.duration - 0.02)));

    if (currentSource) {
      try {
        currentSource.onended = null;
        currentSource.stop();
        currentSource.disconnect();
      } catch (_) {}
      currentSource = null;
    }
    if (wordTimer) { clearTimeout(wordTimer); wordTimer = null; }

    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const source = ctx.createBufferSource();
    source.buffer = entry.buffer;
    source.connect(ctx.destination);
    currentSource = source;
    segmentStartedAt = ctx.currentTime - clamped;
    segmentDuration = entry.duration;
    source.start(0, clamped);
    scheduleWordHighlights(segEls[currentSegment], entry.wordTimings, segmentStartedAt, currentSegment, myGen);
    source.onended = () => {
      if (gen !== myGen || currentSource !== source) return;
      currentSource = null;
      playSegment(currentSegment + 1, myGen);
    };
    setPlayingUI(true);
    updatePlayheadUI(clamped, entry.duration);
    updateDocSeekUI(clamped);
  }

  function startSession(fromSegment) {
    const myGen = ++gen;
    stopAudio();
    for (let i = 0; i <= LOOKAHEAD; i++) fetchSegment(fromSegment + i);
    playSegment(fromSegment, myGen);
  }

  function play(fromSegment) {
    const startAt = fromSegment !== undefined ? fromSegment : Math.max(0, currentSegment);
    setPlayingUI(true);
    startSession(startAt);
  }

  function pause() {
    gen++; // invalidate in-flight session
    stopAudio();
    if (audioCtx) audioCtx.suspend();
    setPlayingUI(false);
  }

  function stop() {
    gen++;
    stopAudio();
    setActiveSegment(-1);
    setPlayingUI(false);
  }

  function skipBack() {
    const prev = Math.max(0, currentSegment - 1);
    setPlayingUI(true);
    startSession(prev);
  }

  function skipForward() {
    const next = Math.min(totalSegments - 1, currentSegment + 1);
    setPlayingUI(true);
    startSession(next);
  }

  function jumpTo(index) {
    setPlayingUI(true);
    startSession(index);
  }

  // Every previously-recorded *real* segment duration was measured at the
  // old voice/speed and no longer applies (a different voice/speed produces
  // different actual durations) -- back every segment out to a fresh
  // estimate along with the audio cache itself, rather than leaving stale
  // real numbers in the document-wide total.
  function resetDurationEstimates() {
    for (let i = 0; i < segmentDurations.length; i++) segmentDurationIsReal[i] = false;
    observedBaseWordsPerSecond = null;
    recomputeEstimatesForCurrentSpeed();
  }

  function setSpeed(newSpeed) {
    speed = newSpeed;
    cacheMap.clear();
    // Forget in-flight fetches too (not cancel them -- fetch() has no abort wired
    // here -- but a stale one finishing later just writes an orphaned cacheMap
    // entry for an index nobody reads under the new voice/speed context; a fresh
    // fetchSegment() call right after this always starts a new request instead of
    // awaiting the stale one).
    pending.clear();
    resetDurationEstimates();
    document.querySelectorAll(".speed-btn").forEach((b) => {
      b.classList.toggle("active", parseFloat(b.dataset.speed) === speed);
    });
    if (currentSegment >= 0) startSession(currentSegment);
  }

  function setVoice(newVoice) {
    voice = newVoice;
    cacheMap.clear();
    // Forget in-flight fetches too (not cancel them -- fetch() has no abort wired
    // here -- but a stale one finishing later just writes an orphaned cacheMap
    // entry for an index nobody reads under the new voice/speed context; a fresh
    // fetchSegment() call right after this always starts a new request instead of
    // awaiting the stale one).
    pending.clear();
    resetDurationEstimates();
    if (playing && currentSegment >= 0) startSession(currentSegment);
  }

  // ---- UI wiring ----
  function setPlayingUI(isPlaying) {
    playing = isPlaying;
    const btn = document.getElementById("btn-play-pause");
    if (btn) btn.textContent = isPlaying ? "⏸" : "▶";
  }

  let progressTimer = null;
  function postProgress() {
    clearTimeout(progressTimer);
    progressTimer = setTimeout(() => {
      fetch(`/api/articles/${ARTICLE_ID}/progress`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ segment_index: currentSegment, voice, speed }),
      }).catch(() => {});
    }, 300);
  }

  document.addEventListener("click", (e) => {
    const jumpEl = e.target.closest("[data-jump]");
    if (jumpEl) {
      jumpTo(parseInt(jumpEl.getAttribute("data-jump"), 10));
      return;
    }
    const segEl = e.target.closest("[data-seg]");
    if (segEl && segTypes[parseInt(segEl.getAttribute("data-seg"), 10)] !== "code") {
      jumpTo(parseInt(segEl.getAttribute("data-seg"), 10));
    }
  });

  const playPauseBtn = document.getElementById("btn-play-pause");
  if (playPauseBtn) {
    playPauseBtn.addEventListener("click", () => {
      if (playing) pause();
      else play(currentSegment >= 0 ? currentSegment : 0);
    });
  }
  const stopBtn = document.getElementById("btn-stop");
  if (stopBtn) stopBtn.addEventListener("click", stop);
  const skipBackBtn = document.getElementById("btn-skip-back");
  if (skipBackBtn) skipBackBtn.addEventListener("click", skipBack);
  const skipForwardBtn = document.getElementById("btn-skip-forward");
  if (skipForwardBtn) skipForwardBtn.addEventListener("click", skipForward);

  document.querySelectorAll(".speed-btn").forEach((btn) => {
    btn.addEventListener("click", () => setSpeed(parseFloat(btn.dataset.speed)));
  });
  const voiceSelect = document.getElementById("voice-select");
  if (voiceSelect) voiceSelect.addEventListener("change", () => setVoice(voiceSelect.value));

  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    if (e.code === "Space") {
      e.preventDefault();
      if (playing) pause(); else play(currentSegment >= 0 ? currentSegment : 0);
    } else if (e.code === "ArrowLeft") {
      skipBack();
    } else if (e.code === "ArrowRight") {
      skipForward();
    } else if (e.key === "[") {
      const i = Math.max(0, SPEEDS.indexOf(speed) - 1);
      setSpeed(SPEEDS[i]);
    } else if (e.key === "]") {
      const i = Math.min(SPEEDS.length - 1, SPEEDS.indexOf(speed) + 1);
      setSpeed(SPEEDS[i]);
    }
  });

  // ---- audio-only mode: hides the article text/TOC, shows the
  // "now playing" panel (syncNowPlaying(), above) instead. Persisted
  // per-browser via localStorage, matching theme.js's pattern -- not
  // per-article, since it's a listening-preference, not article state. ----
  const AUDIO_ONLY_KEY = "audioOnlyMode";
  const audioOnlyToggle = document.getElementById("audio-only-toggle");
  function applyAudioOnlyMode(enabled) {
    document.body.classList.toggle("audio-only-mode", enabled);
    if (audioOnlyToggle) audioOnlyToggle.textContent = enabled ? "📄 Show text" : "🎧 Audio only";
  }
  applyAudioOnlyMode(localStorage.getItem(AUDIO_ONLY_KEY) === "1");
  if (audioOnlyToggle) {
    audioOnlyToggle.addEventListener("click", () => {
      const enabled = !document.body.classList.contains("audio-only-mode");
      localStorage.setItem(AUDIO_ONLY_KEY, enabled ? "1" : "0");
      applyAudioOnlyMode(enabled);
    });
  }

  // ---- resume banner ----
  const lastIndex = window.LAST_SEGMENT_INDEX;
  if (typeof lastIndex === "number" && lastIndex >= 0 && lastIndex < totalSegments) {
    const banner = document.getElementById("resume-banner");
    if (banner) {
      banner.style.display = "flex";
      document.getElementById("btn-resume").addEventListener("click", () => {
        banner.style.display = "none";
        jumpTo(lastIndex);
      });
      document.getElementById("btn-dismiss-resume").addEventListener("click", () => {
        banner.style.display = "none";
      });
    }
  }
})();
