"""Render a product as marked Markdown: banner top and bottom, portion marks
on every paragraph, source list, AI-assistance disclosure, and the review
record. Unreleased products carry a not-released watermark."""

from __future__ import annotations

from typing import Dict

from backend.models.governance import Product
from backend.models.marking import PortionMarking
from backend.products import marking_roll


def _fmt(dt) -> str:
    return dt.strftime("%d %b %Y %H:%M UTC") if dt else "n/a"


def render(product: Product, names: Dict[str, str]) -> str:
    if product.banner_classification:
        banner = marking_roll.banner(PortionMarking.parse(
            "({})".format(product.banner_classification) if not product.banner_controls else
            "({}//{})".format(product.banner_classification, "/".join(product.banner_controls))))
    else:
        marked = [PortionMarking.parse(c.portion_marking) for c in product.claims
                  if c.portion_marking]
        banner = marking_roll.banner(marking_roll.combine(marked)) if marked else "UNMARKED DRAFT"
    out = [banner, ""]
    if product.state != "released":
        out += ["**NOT RELEASED: AI-ASSISTED DRAFT ({}). Do not disseminate.**".format(
            product.state.upper()), ""]
    out += ["# " + product.title, ""]
    for c in product.claims:
        refs = "".join("[S{}]".format(n) for n in c.cited_sources)
        tag = " (Analytic judgment)" if c.kind == "judgment" else (
            " (UNCITED)" if c.kind == "uncited" else "")
        out.append("{} {}{} {}".format(c.portion_marking or "(UNMARKED)", c.text, tag, refs).strip())
        out.append("")
    out += ["## Sources", "", "Derived From: Multiple Sources", ""]
    for s in product.sources:
        out.append("- [S{}] {} {} (document {}, {})".format(
            s.num, s.portion_marking, s.doc_title, s.parent_doc_id, s.source_system))
    out += ["", "## AI-assistance disclosure", "",
            "- Drafted with: {} ({} adapter)".format(product.model_name, product.adapter),
            "- Model requested: {}; model reported: {}".format(
                product.model_id_requested, product.model_id_reported or "not reported"),
            "- Model classification ceiling applied: {}".format(product.model_ceiling),
            "- Retrieved items withheld by ceiling: {}".format(len(product.withheld_chunk_ids or [])),
            "- Prompt SHA-256: {}".format(product.prompt_sha256),
            "- Raw model output SHA-256: {}".format(product.raw_output_sha256),
            "- Drafted: {}".format(_fmt(product.created_at)), "",
            "## Review record", "",
            "- Author / derivative classifier: {}".format(names.get(product.author_id, "unknown")),
            "- Policy version applied: {}".format(product.policy_version or "not yet submitted"),
            "- Reviewer: {} ({})".format(names.get(product.reviewer_id, "pending"),
                                         _fmt(product.reviewed_at)),
            "- Releaser: {} ({})".format(names.get(product.releaser_id, "pending"),
                                         _fmt(product.released_at)),
            "- Content SHA-256 at submission: {}".format(product.content_sha256 or "n/a"),
            "", banner, ""]
    return "\n".join(out)
