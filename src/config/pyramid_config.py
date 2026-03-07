class PyramidConfig:
    """
    Pyramiding configuration parameters.

    pyramid_fraction: Fraction of normal position size for pyramid adds.
        e.g., 0.5 means pyramid adds invest 50% of what a normal BUY would.
    """
    pyramid_fraction: float = 0.5
