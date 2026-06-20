"""Maps page numbers between two editions of a book using interpolated anchors."""


class PageMapper:
    """Maps page numbers between two PDF versions using anchor points with interpolation."""

    def __init__(self, original_page_count: int, translation_page_count: int):
        self.original_page_count = original_page_count
        self.translation_page_count = translation_page_count

        # Default anchors: start and end.
        # Format: (original_page, translation_page) - 0-indexed
        self.anchors: list[tuple[int, int]] = [
            (0, 0),
            (original_page_count - 1, translation_page_count - 1),
        ]

    def set_anchors(self, anchors: list[tuple[int, int]]) -> None:
        """Set anchor points manually.

        Args:
            anchors: List of (original_page, translation_page) tuples, 0-indexed.
        """
        if not anchors:
            return

        self.anchors = sorted(anchors, key=lambda x: x[0])

        # Ensure start anchor exists.
        if self.anchors[0][0] != 0:
            self.anchors.insert(0, (0, 0))

        # Ensure end anchor exists.
        last_orig = self.original_page_count - 1
        last_trans = self.translation_page_count - 1
        if self.anchors[-1][0] != last_orig:
            self.anchors.append((last_orig, last_trans))

    def add_anchor(self, original_page: int, translation_page: int) -> None:
        """Add a single anchor point."""
        # Remove existing anchor at same original page.
        self.anchors = [a for a in self.anchors if a[0] != original_page]

        self.anchors.append((original_page, translation_page))
        self.anchors.sort(key=lambda x: x[0])

    def remove_anchor(self, original_page: int) -> None:
        """Remove anchor at specified original page (keeps start/end)."""
        if original_page == 0 or original_page == self.original_page_count - 1:
            return  # Don't remove start/end anchors.

        self.anchors = [a for a in self.anchors if a[0] != original_page]

    def get_anchors(self) -> list[tuple[int, int]]:
        """Return current anchor points."""
        return self.anchors.copy()

    def original_to_translation(self, original_page: int) -> int:
        """Map original page number to translation page number.

        Args:
            original_page: 0-indexed page number in original PDF.

        Returns:
            0-indexed page number in translation PDF.
        """
        # Clamp to valid range.
        original_page = max(0, min(original_page, self.original_page_count - 1))

        # Find surrounding anchors.
        lower_anchor = self.anchors[0]
        upper_anchor = self.anchors[-1]

        for i in range(len(self.anchors) - 1):
            if self.anchors[i][0] <= original_page <= self.anchors[i + 1][0]:
                lower_anchor = self.anchors[i]
                upper_anchor = self.anchors[i + 1]
                break

        # Exact match.
        if original_page == lower_anchor[0]:
            return lower_anchor[1]
        if original_page == upper_anchor[0]:
            return upper_anchor[1]

        # Linear interpolation.
        orig_range = upper_anchor[0] - lower_anchor[0]
        trans_range = upper_anchor[1] - lower_anchor[1]

        if orig_range == 0:
            return lower_anchor[1]

        position = (original_page - lower_anchor[0]) / orig_range
        translation_page = lower_anchor[1] + (position * trans_range)

        # Clamp result.
        result = int(round(translation_page))
        return max(0, min(result, self.translation_page_count - 1))

    def translation_to_original(self, translation_page: int) -> int:
        """Map translation page number to original page number.

        Args:
            translation_page: 0-indexed page number in translation PDF.

        Returns:
            0-indexed page number in original PDF.
        """
        # Clamp to valid range.
        translation_page = max(
            0, min(translation_page, self.translation_page_count - 1)
        )

        # Find surrounding anchors (by translation page).
        lower_anchor = self.anchors[0]
        upper_anchor = self.anchors[-1]

        for i in range(len(self.anchors) - 1):
            lower_trans = self.anchors[i][1]
            upper_trans = self.anchors[i + 1][1]

            if lower_trans <= translation_page <= upper_trans:
                lower_anchor = self.anchors[i]
                upper_anchor = self.anchors[i + 1]
                break

        # Exact match.
        if translation_page == lower_anchor[1]:
            return lower_anchor[0]
        if translation_page == upper_anchor[1]:
            return upper_anchor[0]

        # Linear interpolation.
        orig_range = upper_anchor[0] - lower_anchor[0]
        trans_range = upper_anchor[1] - lower_anchor[1]

        if trans_range == 0:
            return lower_anchor[0]

        position = (translation_page - lower_anchor[1]) / trans_range
        original_page = lower_anchor[0] + (position * orig_range)

        # Clamp result.
        result = int(round(original_page))
        return max(0, min(result, self.original_page_count - 1))
