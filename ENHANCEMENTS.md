# Enhancements Tracker

Improvements beyond the core v0.x roadmap. Each entry includes motivation and implementation notes.

---

## ENH-001 — VTO Three Uniques: Split into three distinct blocks

**Status**: Done
**Area**: VTO — Marketing Strategy

**Problem**: The "Three Uniques" section was a single freeform text block. Teams ended up entering all three uniques as unformatted text, which was hard to read and edit.

**Solution**: Replace the single section with three individually labelled and independently editable blocks — *Unique 1*, *Unique 2*, and *Unique 3*. Each block has its own edit button and stores its content in a dedicated `VTOSection` row (`three_uniques_1`, `three_uniques_2`, `three_uniques_3`).

**Migration**: Existing `three_uniques` content is moved to `three_uniques_1` via a data migration.
