"""
Conversion pipeline: any CSV/XLSX/XLS -> template rows.

reader -> profiler -> mapper -> extract -> store. Each step is a plain
function over plain data so LangGraph nodes (and agents) can wrap or
replace it. When a step is unsure it does not guess: it emits a review
item (pending_reviews) instead. See docs/requirements.md.
"""
