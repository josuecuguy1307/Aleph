/* Search-provider choice is requested only when a web capability is submitted. */

const OFFICIAL_INSTALL = "https://docs.searxng.org/admin/installation.html";
const OFFICIAL_SOURCE = "https://github.com/searxng/searxng";
const OFFICIAL_LICENSE = "https://github.com/searxng/searxng/blob/master/LICENSE";
let choiceActive = false;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

async function status(headers) {
  const response = await fetch("/v1/sala/search-provider", { headers: headers({ Accept: "application/json" }) });
  if (!response.ok) throw new Error(`Search provider status: HTTP ${response.status}`);
  return response.json();
}

/** Returns true when the requested capability may proceed, false on Cancel. */
export async function ensureSearchProvider(headers) {
  if (choiceActive) return false;
  choiceActive = true;
  try {
    return await chooseSearchProvider(headers);
  } finally {
    choiceActive = false;
  }
}

async function chooseSearchProvider(headers) {
  const provider = await status(headers);
  if (provider.configured) return true;

  return new Promise((resolve) => {
    const dialog = element("dialog", "sv-search-provider-dialog");
    dialog.setAttribute("aria-labelledby", "sv-search-provider-title");
    const title = element("h2", "", "Web search requires a search provider.");
    title.id = "sv-search-provider-title";
    dialog.append(title);
    dialog.append(element("p", "", provider.reason || "SearXNG is an optional, independently licensed provider. Aleph does not include it."));

    const choices = element("div", "sv-search-provider-choices");
    const connect = element("button", "", "Connect existing SearXNG instance");
    const install = element("button", "", "Install SearXNG locally");
    const cancel = element("button", "", "Cancel");
    for (const button of [connect, install, cancel]) button.type = "button";
    choices.append(connect, install, cancel);
    dialog.append(choices);

    const details = element("div", "sv-search-provider-details");
    details.hidden = true;
    dialog.append(details);
    let finished = false;
    const finish = (result) => {
      if (finished) return;
      finished = true;
      dialog.close();
      dialog.remove();
      resolve(result);
    };

    const showConnect = () => {
      details.replaceChildren();
      details.hidden = false;
      details.append(element("label", "", "SearXNG instance URL"));
      const input = element("input", "");
      input.type = "url";
      input.placeholder = "http://127.0.0.1:8080";
      input.value = provider.url || "";
      input.autocomplete = "url";
      input.required = true;
      input.setAttribute("aria-label", "SearXNG instance URL");
      const save = element("button", "", "Connect and continue");
      save.type = "button";
      const message = element("p", "sv-search-provider-message");
      message.setAttribute("role", "status");
      save.addEventListener("click", async () => {
        if (!input.value.trim()) { message.textContent = "Enter a SearXNG URL."; return; }
        save.disabled = true;
        message.textContent = "Checking the SearXNG JSON API…";
        try {
          const response = await fetch("/v1/sala/search-provider", {
            method: "PUT",
            headers: headers({ "Content-Type": "application/json" }),
            body: JSON.stringify({ url: input.value.trim() }),
          });
          const data = await response.json();
          if (!response.ok) throw new Error(data?.detail?.copy || `HTTP ${response.status}`);
          finish(true);
        } catch (error) {
          message.textContent = error?.message || "Could not connect to the search provider.";
          save.disabled = false;
        }
      });
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") save.click(); });
      details.append(input, save, message);
      input.focus();
    };

    connect.addEventListener("click", showConnect);
    install.addEventListener("click", () => {
      details.replaceChildren();
      details.hidden = false;
      details.append(element("p", "", "SearXNG is AGPL-3.0-or-later third-party software, not owned or installed by Aleph. Follow the official instructions to install it outside Aleph, then connect its URL here."));
      for (const [label, url] of [
        ["Official installation instructions", OFFICIAL_INSTALL],
        ["Upstream source", OFFICIAL_SOURCE],
        ["AGPL license", OFFICIAL_LICENSE],
      ]) {
        const link = element("a", "", label);
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link);
      }
      const after = element("button", "", "I have an instance URL");
      after.type = "button";
      after.addEventListener("click", showConnect);
      details.append(after);
    });
    cancel.addEventListener("click", () => finish(false));
    dialog.addEventListener("cancel", (event) => { event.preventDefault(); finish(false); });
    document.body.append(dialog);
    dialog.showModal();
    connect.focus();
  });
}
