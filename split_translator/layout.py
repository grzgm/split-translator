"""The two arrangements of the reading window, named in one place.

Both panels build themselves in one of these and can be switched between them;
each workspace's config.json remembers which one it was left in.
"""

# The four dictionary squares, with the two book editions in tabs.
LAYOUT_DEFAULT = "default"
# Two tabbed dictionary squares stacked in one column, with both book editions
# side by side.
LAYOUT_WIDE = "wide"

LAYOUTS = (LAYOUT_DEFAULT, LAYOUT_WIDE)


def normalise_layout(value) -> str:
    """One of the two layout names, whatever came in.

    A missing, misspelt or hand-edited value reads as the default view rather
    than raising, so a config file written by hand cannot stop the app opening.
    """
    return value if value in LAYOUTS else LAYOUT_DEFAULT
