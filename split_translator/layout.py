"""The two arrangements of the reading window, named in one place.

Each panel builds itself in one of these when it is constructed and never
changes afterwards. Choosing the other view rebuilds the window
(``main_window.choose_layout``), the same way choosing another workspace does:
moving live web views between containers leaves them mis-sized, so a view is
only ever laid out once, on a window built for it.

Each workspace's config.json remembers which view it was left in.
"""

# Four dictionary squares, with the two book editions in tabs.
LAYOUT_NORMAL = "normal"
# Two tabbed dictionary squares stacked in one column, with both book editions
# side by side.
LAYOUT_BOOK = "book"

LAYOUTS = (LAYOUT_NORMAL, LAYOUT_BOOK)


def normalise_layout(value) -> str:
    """One of the two layout names, whatever came in.

    A missing, misspelt or hand-edited value reads as the normal view rather
    than raising, so a config file written by hand cannot stop the app opening.
    """
    return value if value in LAYOUTS else LAYOUT_NORMAL
