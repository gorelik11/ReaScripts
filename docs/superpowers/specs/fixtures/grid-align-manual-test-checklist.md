# Grid Align Transients — Manual QA Checklist

- [ ] Straight 1/16 groove, triplets off
- [ ] Triplet groove, triplets on
- [ ] Sparse percussion (few transients)
- [ ] Dense material (close attacks)
- [ ] Multiple selected items with different start positions
- [ ] Trimmed item (non-zero D_STARTOFFS) aligns by audible content
- [ ] Unsupported playrate / reversed / section item warns and is skipped
- [ ] Neighbor item untouched; nothing outside time selection moves
- [ ] Auto-detect: no splits created outside corrections (track stays live)
- [ ] Existing-splits source on a pre-sliced item
- [ ] Adaptive: late-after-late inherits prev lag; rush snaps to grid; first event snaps
- [ ] 44.1k / 48k / 96k material yields consistent correction behavior
- [ ] Single undo reverts the whole operation
