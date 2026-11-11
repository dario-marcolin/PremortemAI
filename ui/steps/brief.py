"""Brief: the facts the extractor read from the document, and what the document does not say."""

import streamlit as st

from ui.steps.common import title_row
from ui.theme import esc, html_block
from ui.view import RunView


def render(view: RunView, info) -> None:
    b = view.brief
    if b is None:
        title_row(view, info, "The brief appears when the extractor has read the document.")
        st.caption("Working on it." if info.status == "running" else "Not started yet.")
        return
    missing = len(b.missing_info)
    title_row(view, info, f"Read from <b>{esc(view.document)}</b>. "
                          f"{missing} piece{'s' if missing != 1 else ''} of information the plan needs "
                          f"{'are' if missing != 1 else 'is'} not in the document.")
    price = (f'<div class="v">{esc(b.price_hint)}</div>' if b.price_hint
             else '<div class="v none">Not stated</div>')
    html_block(
        '<div class="pm-facts">'
        f'<div><div class="pm-label">Company</div><div class="v">{esc(b.company_name)}</div></div>'
        f'<div><div class="pm-label">Product</div><div class="v">{esc(b.product_name)}</div></div>'
        f'<div><div class="pm-label">Launch country</div><div class="v">{esc(b.target_country)}</div></div>'
        f'<div><div class="pm-label">Price</div>{price}</div></div>')

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("The product")
        st.write(b.product_description)
        st.subheader("The company")
        st.write(b.company_description)
        st.subheader("Launch goals")
        if b.stated_goals:
            html_block("<ul class='pm-reason'>" + "".join(f"<li>{esc(g)}</li>" for g in b.stated_goals) + "</ul>")
        else:
            st.caption("None stated.")
        st.subheader("Competitors named")
        st.write(", ".join(b.known_competitors) if b.known_competitors else "—")
    with right:
        if b.missing_info:
            items = "".join(f"<li>{esc(m)}</li>" for m in b.missing_info)
            html_block(f'<div class="pm-missing"><h3>Missing from the document · {missing}</h3>'
                       f'<ul style="padding-left:18px;margin:0">{items}</ul></div>')
        else:
            st.caption("The document gives everything the plan needs.")
