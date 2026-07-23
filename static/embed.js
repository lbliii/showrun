class ShowrunPlayerElement extends HTMLElement {
  connectedCallback() {
    if (this.dataset.hydrated === "true") return;

    const source = this.getAttribute("src");
    if (!source) return;

    let url;
    try {
      url = new URL(source, document.baseURI);
    } catch {
      return;
    }
    if (!["http:", "https:"].includes(url.protocol)) return;

    const theme = this.getAttribute("theme") || "auto";
    if (["auto", "light", "dark"].includes(theme)) {
      url.searchParams.set("theme", theme);
    }

    const iframe = document.createElement("iframe");
    iframe.src = url.toString();
    iframe.title = this.getAttribute("title") || "Showrun lesson";
    iframe.loading = "lazy";
    iframe.allowFullscreen = true;
    iframe.style.cssText = "display:block;width:100%;aspect-ratio:16/9;border:0";

    this.replaceChildren(iframe);
    this.dataset.hydrated = "true";
  }
}

if (!customElements.get("showrun-player")) {
  customElements.define("showrun-player", ShowrunPlayerElement);
}
