class ShowrunPlayerElement extends HTMLElement {
  static get observedAttributes() {
    return ["src", "title", "theme", "chapter", "start"];
  }

  connectedCallback() {
    if (!this.iframe) {
      this.iframe = document.createElement("iframe");
      this.iframe.loading = "lazy";
      this.iframe.allowFullscreen = true;
      this.iframe.referrerPolicy = "strict-origin-when-cross-origin";
      this.iframe.setAttribute("part", "frame");
      this.iframe.setAttribute("allow", "fullscreen");
      this.iframe.style.cssText =
        "display:block;width:100%;aspect-ratio:16/9;border:0";
      this.replaceChildren(this.iframe);
    }
    this.sync();
  }

  attributeChangedCallback() {
    if (this.isConnected) this.sync();
  }

  sync() {
    const source = this.getAttribute("src");
    if (!source) {
      this.iframe.removeAttribute("src");
      this.dataset.hydrated = "false";
      return;
    }

    let url;
    try {
      url = new URL(source, document.baseURI);
    } catch {
      this.iframe.removeAttribute("src");
      this.dataset.hydrated = "false";
      return;
    }
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    ) {
      this.iframe.removeAttribute("src");
      this.dataset.hydrated = "false";
      return;
    }

    const theme = this.getAttribute("theme") || "auto";
    if (["auto", "light", "dark"].includes(theme)) {
      url.searchParams.set("theme", theme);
    }
    const chapter = this.getAttribute("chapter");
    const start = this.getAttribute("start");
    if (chapter && /^\d+$/.test(chapter)) {
      url.searchParams.set("chapter", chapter);
      url.searchParams.delete("start");
    } else if (start && /^\d+(?:\.\d+)?$/.test(start)) {
      url.searchParams.set("start", start);
    }

    const nextSource = url.toString();
    if (this.iframe.src !== nextSource) this.iframe.src = nextSource;
    this.iframe.title = this.getAttribute("title") || "Showrun lesson";
    this.dataset.hydrated = "true";
  }
}

if (!customElements.get("showrun-player")) {
  customElements.define("showrun-player", ShowrunPlayerElement);
}
