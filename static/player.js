// Vanilla-JS read-aloud player. Ports the design proven in v1's usePlayer.ts
// (Tauri/React) to a plain browser client talking to this app's HTTP API
// instead of Tauri's invoke() IPC. See LEARNINGS.md for why each piece exists.
(function () {
  "use strict";
  if (typeof window.ARTICLE_ID === "undefined") return; // not an article page

  const ARTICLE_ID = window.ARTICLE_ID;
  const LOOKAHEAD = 2;
  const AUTO_SCROLL_IDLE_MS = 2500;

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

  function getAudioContext() {
    if (!audioCtx || audioCtx.state === "closed") {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtx;
  }

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
    updateProgressBar();
    postProgress();
  }

  function setActiveWord(el, wordIdx) {
    if (currentWordEl) currentWordEl.classList.remove("word-active");
    const wordEl = el.querySelector(`.word[data-w="${wordIdx}"]`);
    if (wordEl) {
      wordEl.classList.add("word-active");
      currentWordEl = wordEl;
    }
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

  // ---- playback session (generation-counter guarded, ported from usePlayer.ts) ----
  async function playSegment(index, myGen) {
    if (gen !== myGen) return;
    if (index >= totalSegments) {
      setActiveSegment(-1);
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

  function setSpeed(newSpeed) {
    speed = newSpeed;
    cacheMap.clear();
    // Forget in-flight fetches too (not cancel them -- fetch() has no abort wired
    // here -- but a stale one finishing later just writes an orphaned cacheMap
    // entry for an index nobody reads under the new voice/speed context; a fresh
    // fetchSegment() call right after this always starts a new request instead of
    // awaiting the stale one).
    pending.clear();
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
    if (playing && currentSegment >= 0) startSession(currentSegment);
  }

  // ---- UI wiring ----
  function setPlayingUI(isPlaying) {
    playing = isPlaying;
    const btn = document.getElementById("btn-play-pause");
    if (btn) btn.textContent = isPlaying ? "⏸" : "▶";
  }

  function updateProgressBar() {
    const bar = document.getElementById("progress-bar");
    if (!bar || totalSegments === 0) return;
    const pct = currentSegment >= 0 ? ((currentSegment + 1) / totalSegments) * 100 : 0;
    bar.style.setProperty("--pct", pct + "%");
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
      const speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
      const i = Math.max(0, speeds.indexOf(speed) - 1);
      setSpeed(speeds[i]);
    } else if (e.key === "]") {
      const speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
      const i = Math.min(speeds.length - 1, speeds.indexOf(speed) + 1);
      setSpeed(speeds[i]);
    }
  });

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
