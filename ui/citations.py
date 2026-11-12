"""Citation chips with a card on hover and on keyboard focus (roadmap 15.6). Pure HTML and CSS.

In the step views a chip shows the agent's own source id (S3); in the blueprint it shows the
blueprint's number ([3]). Both open the same card: kind, domain, title, the passage or snippet used,
and the evaluation's check of the source when the run was evaluated. A click opens the URL; a
document source has no URL and only shows its card. An unknown id is a red "?" chip.
"""

import re
from urllib.parse import urlparse

from premortem.agents.analyst import SOURCE_ID
from premortem.output.blueprint import CITATION
from ui.theme import esc
from ui.view import RunView, domain

BLUEPRINT_REF = re.compile(r"\[(\d+(?:,\s*\d+)*)\]")
STATUS_WORDS = {"ok": "Page checked", "document": "From the document"}


class Citer:
    def __init__(self, view: RunView):
        self.view = view
        self.sources = view.sources()
        self.hits = view.search_hits()
        self.checks = view.source_checks()
        self.numbers = view.blueprint_numbers()
        self._by_reference = {s.reference: s for s in self.sources.values()}

    # ── one chip ────────────────────────────────────────────────────────────────────────
    def card(self, kind: str, reference: str, url: str | None) -> str:
        hit = self.hits.get(url or "") or {}
        check = self.checks.get(reference) or {}
        if kind == "web":
            where = domain(url) or "web"
            title = hit.get("title") or (domain(url) + (urlparse(url).path or "")) if url else reference
            snippet = hit.get("snippet") or ""
            origin = "Web search" + (f" · ‘{hit['query']}’" if hit.get("query") else "")
        else:
            where = "Company document"
            title = reference.removeprefix("Document: ")
            snippet = self.view.document_passage(reference)
            origin = "From the document"
        status = ""
        if check:
            ok = check.get("valid")
            word = STATUS_WORDS.get(check.get("status"), check.get("status") or "")
            status = f'<span style="color:var({"--positive" if ok else "--negative"})">{esc(word if ok else "Invalid: " + word)}</span>'
        snip = f'<span class="snip">{esc(snippet[:320])}</span>' if snippet else ""
        link = (f'<a class="url" href="{esc(url)}" target="_blank" rel="noopener">Open source ↗'
                f'<span class="addr">{esc(url)}</span></a>') if url else ""
        return (f'<span class="card" role="tooltip"><span class="src"><span>{esc(where)}</span>{status}</span>'
                f'<span class="ttl" style="display:block">{esc(title)}</span>{snip}'
                f'<span style="display:block;color:var(--muted);font-size:12px;margin-bottom:4px">{esc(origin)}</span>{link}</span>')

    def chip(self, label: str, kind: str | None, reference: str | None, url: str | None) -> str:
        if kind is None:
            return (f'<span class="pm-cite bad"><span class="chip" tabindex="0" aria-label="Unknown source {esc(label)}">?</span>'
                    f'<span class="card" role="tooltip"><span class="ttl" style="display:block">Unknown source {esc(label)}</span>'
                    'This id is not in the list of sources: the citation is broken.</span></span>')
        card = self.card(kind, reference or "", url)
        if url:
            return (f'<span class="pm-cite"><a href="{esc(url)}" target="_blank" rel="noopener" '
                    f'aria-label="Source {esc(label)}: {esc(reference)}">{esc(label)}</a>{card}</span>')
        return (f'<span class="pm-cite"><span class="chip" tabindex="0" aria-label="Source {esc(label)}: '
                f'{esc(reference)}">{esc(label)}</span>{card}</span>')

    def source_chip(self, source_id: str) -> str:
        s = self.sources.get(source_id)
        if s is None:
            return self.chip(source_id, None, None, None)
        url = s.reference if s.kind == "web" else None
        return self.chip(source_id, s.kind, s.reference, url)

    def number_chip(self, number: str) -> str:
        entry = self.numbers.get(number)
        if entry is None:
            return self.chip(number, None, None, None)
        source = self._by_reference.get(entry["reference"]) or self._by_reference.get(
            entry["reference"].removeprefix("Document: "))
        kind = source.kind if source else entry["kind"]
        reference = source.reference if source else entry["reference"]
        return self.chip(number, kind, reference, entry.get("url"))

    # ── text with citations ─────────────────────────────────────────────────────────────
    def text(self, value: str | None) -> str:
        """Agent text (escaped) with its source ids as chips: "[S2, S3]", "[S1][S2]" and a bare ", S4"."""
        if not value:
            return ""
        out, last = [], 0
        for m in CITATION.finditer(value):
            token = m.group()
            ids = SOURCE_ID.findall(token)
            if not ids or (not token.startswith("[") and ids[0] not in self.sources):
                continue
            out.append(esc(value[last:m.start()]))
            out.append(("&nbsp;" if not token.startswith("[") else "") + "".join(self.source_chip(i) for i in ids))
            last = m.end()
        out.append(esc(value[last:]))
        return "".join(out)

    def ids(self, source_ids: list[str]) -> str:
        return "".join(self.source_chip(i) for i in source_ids)

    def blueprint_html(self, html: str) -> str:
        """The blueprint, already rendered to HTML: its [1, 2] references become chips.
        The Sources list keeps its own numbers, so it is left as it is."""
        head, sep, tail = html.partition('<h2 id="sources"')
        return BLUEPRINT_REF.sub(lambda m: "".join(self.number_chip(n.strip()) for n in m.group(1).split(",")), head) + sep + tail
