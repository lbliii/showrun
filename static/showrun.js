document.addEventListener("alpine:init", () => {
  Alpine.data("showrunPlayer", (configId) => ({
    config: null,
    time: 0,
    playing: false,
    speed: 1,
    mode: "lesson",
    captions: true,
    transcript: false,
    toast: "",
    timer: null,
    toastTimer: null,
    viewedChapters: new Set(),

    init() {
      const node = document.getElementById(configId);
      this.config = JSON.parse(node.textContent);
      this.trackChapter();
    },

    destroy() {
      window.clearInterval(this.timer);
      window.clearTimeout(this.toastTimer);
    },

    get duration() {
      return this.config?.duration || 0;
    },

    get activeEvent() {
      if (!this.config) return { id: 1, at: 0 };
      return (
        [...this.config.events].reverse().find((event) => event.at <= this.time) ||
        this.config.events[0]
      );
    },

    get activeChapter() {
      if (!this.config) return { name: "", at: 0, caption: "" };
      return (
        [...this.config.chapters]
          .reverse()
          .find((chapter) => chapter.at <= this.time) || this.config.chapters[0]
      );
    },

    get chapterNumber() {
      if (!this.config) return "01";
      const index = this.config.chapters.findIndex(
        (chapter) => chapter.at === this.activeChapter.at,
      );
      return String(index + 1).padStart(2, "0");
    },

    get chapterKicker() {
      return `${this.chapterNumber} · ${this.activeChapter.name}`;
    },

    toggle() {
      if (this.time >= this.duration) this.time = 0;
      this.playing = !this.playing;
      if (this.playing) {
        this.trackOnce("playback.started");
        this.startTimer();
      }
      else this.stopTimer();
    },

    startTimer() {
      this.stopTimer();
      this.timer = window.setInterval(() => {
        const next = this.time + 0.1 * this.speed;
        if (next >= this.duration) {
          this.time = this.duration;
          this.playing = false;
          this.stopTimer();
          this.trackOnce("playback.completed");
          return;
        }
        this.time = next;
        this.trackChapter();
        this.scrollToActive();
      }, 100);
    },

    stopTimer() {
      if (this.timer) window.clearInterval(this.timer);
      this.timer = null;
    },

    jump(at) {
      this.time = Math.max(0, Math.min(this.duration, Number(at)));
      this.playing = false;
      this.stopTimer();
      this.trackChapter();
      this.scrollToActive();
    },

    seek(delta) {
      this.jump(this.time + delta);
    },

    cycleSpeed() {
      this.speed = this.speed === 1 ? 1.5 : this.speed === 1.5 ? 2 : 1;
    },

    formatTime(value) {
      const seconds = Math.max(0, Number(value) || 0);
      const minutes = Math.floor(seconds / 60);
      return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
    },

    scrollToActive() {
      this.$nextTick(() => {
        const current = this.$refs.conversation?.querySelector(".event.current");
        current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    },

    notify(message) {
      this.toast = message;
      window.clearTimeout(this.toastTimer);
      this.toastTimer = window.setTimeout(() => {
        this.toast = "";
      }, 2400);
    },

    trackOnce(event) {
      const slug = this.config?.telemetry?.releaseSlug;
      if (!slug) return;
      const key = `showrun:${slug}:${event}`;
      try {
        if (window.sessionStorage.getItem(key)) return;
        window.sessionStorage.setItem(key, "1");
      } catch {
        // Playback must keep working when an embed blocks storage.
      }
      this.track(event);
    },

    trackChapter() {
      if (!this.config?.telemetry) return;
      const chapter = this.config.chapters.findIndex(
        (candidate) => candidate.at === this.activeChapter.at,
      ) + 1;
      if (!chapter || this.viewedChapters.has(chapter)) return;
      this.viewedChapters.add(chapter);
      this.track("chapter.viewed", { chapter });
    },

    track(event, properties = {}) {
      const telemetry = this.config?.telemetry;
      if (!telemetry) return;
      let origin = "";
      try {
        origin = document.referrer ? new URL(document.referrer).origin : "";
      } catch {
        origin = "";
      }
      const body = JSON.stringify({
        event,
        releaseSlug: telemetry.releaseSlug,
        origin,
        ...properties,
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon(
          telemetry.endpoint,
          new Blob([body], { type: "application/json" }),
        );
        return;
      }
      fetch(telemetry.endpoint, {
        method: "POST",
        body,
        headers: { "Content-Type": "application/json" },
        keepalive: true,
      }).catch(() => {});
    },
  }));
});
