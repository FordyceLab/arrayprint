"""Programmatic spotting using Scienion S3 liquid-handling robots."""

from collections import Counter
from datetime import datetime
from typing import Any, Literal, get_args

import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy import typing as npt

from .field_files import headers_footers

__version__ = "0.1.0"
DeviceTypes = Literal["PS1.8K", "STAMMP-seq"]
assert tuple(headers_footers.keys()) == get_args(DeviceTypes)


def get_block(
    print_array: npt.NDArray[Any], block: int, n_blocks: int
) -> npt.NDArray[Any]:
    """A view of the print array belonging to the given (0-indexed) block."""
    columns = print_array.shape[1]
    width = int(columns // n_blocks)
    return print_array[:, width * block : width * (block + 1)]


def fill_array(
    wells: pd.Series, array: npt.NDArray[Any], seed: int | None = None
) -> None:
    """Randomly fill array in-place, keeping the replicates per well ~constant.

    Args:
        wells: Iterable containing plate well information
        array: Array to fill with values
        seed: Seed for random generation
    """
    rng = np.random.default_rng(seed)

    # Calculate number of replicates per well
    to_fill = np.sum(array == None)  # pylint: disable=singleton-comparison
    replicates = int(to_fill // len(wells))
    if replicates == 0:
        raise ValueError(
            f"There are {len(wells)} variants but only {len(array)} spots."
        )

    # Create randomized set of fill values
    arrays = [
        np.repeat(wells, repeats=replicates),
        rng.choice(wells, size=(to_fill % len(wells),), replace=False),
    ]
    fill_values = np.concat(arrays, axis=0)
    assert len(fill_values) == to_fill
    rng.shuffle(fill_values)

    # Fill array
    array[
        np.nonzero(array == None)  # pylint: disable=singleton-comparison
    ] = fill_values


def generate_print_array(
    print_spec: pd.DataFrame,
    rows: int = 56,
    columns: int = 32,
    skip_rows: bool = True,
    n_blocks: int = 1,
    notch_column: int = 28,
    notch_depth: int = 20,
    seed: int | None = None,
) -> npt.NDArray[Any]:
    """Generate optimized print array from print_spec dataframe.

    Args:
        print_spec: DataFrame containing print data
        rows: Number of rows in device
        columns: Number of columns in device
        skip_rows: Whether to add blank rows
        n_blocks: Number of blocks to divide array into
        notch_column: Column to notch with no spots to orient the slide
        notch_depth: Depth of the notch (0 for no notch)
        seed: Seed for random generation

    Returns:
        Numpy array of strings containing print layout
    """
    print_array = np.full((rows, columns), fill_value=None, dtype="object")
    plate_well = print_spec["Plate"].astype(str) + print_spec["Well"]

    # Add skipped rows and notch
    if skip_rows:
        print_array[1::2] = ""
    print_array[:notch_depth, notch_column] = ""

    # Fill in each block in-place using slicing to produce a view
    for i in range(n_blocks):
        indexing = print_spec["Block"].apply(
            lambda x: i + 1 in x  # pylint: disable=cell-var-from-loop
        )
        fill_array(
            plate_well[indexing], get_block(print_array, i, n_blocks), seed
        )

    return print_array


def get_fld(
    print_array: npt.NDArray[Any], device: DeviceTypes | None = None
) -> str:
    """Get FLD file as a string.

    Args:
        print_array: Array containing mutant positions
        device: Device type used for writing the header and footer
    """
    print_array = np.flip(print_array, axis=1)  # Scienion flips orientation
    rows, columns = print_array.shape

    if device is not None:
        header, footer = headers_footers[device]
        out = [header]
    else:
        out = []

    for i in range(0, columns):
        for j in range(0, rows):
            current_fld_loc = f"{i + 1}/{j+1}"
            array_loc_print = print_array[j, i]

            # Add a plate number to only the non-blank wells
            if len(array_loc_print) >= 1:
                if array_loc_print[0] != "1":
                    array_loc_print = "1" + array_loc_print
                out.append(f"{current_fld_loc}\t{array_loc_print},\t1,")
            else:
                out.append(f"{current_fld_loc}\t\t")

    if device is not None:
        out.append(footer)

    return "\r\n".join(out)


def write_fld(
    basename: str,
    print_array: npt.NDArray[Any],
    device: DeviceTypes | None = None,
) -> None:
    """Write FLD file to disk.

    Args:
        basename: Base filename for the FLD file
        print_array: Array containing mutant positions
        device: Device type used for writing the header and footer
    """
    timestamp = datetime.now().strftime(r"%Y_%m_%d__%H_%M_%S")
    with open(f"{basename}_{timestamp}.fld", "wt", encoding="cp1252") as f:
        f.write(get_fld(print_array, device=device))


def get_print_metrics(print_array: npt.NDArray[Any]) -> dict[str, Any]:
    """Calculate comprehensive print metrics.

    Args:
        print_array: Array containing mutant positions

    Returns:
        Dictionary containing metrics summary
    """
    # Get frequency of each mutant in print
    unique, counts = np.unique(print_array, return_counts=True)
    print_counts = dict(zip(unique, counts))

    # Remove blanks from print_counts
    print_counts.pop("", None)

    if not print_counts:
        return {"error": "No valid entries found in print array"}

    count_values = list(print_counts.values())

    metrics = {
        "Total Variants": len(print_counts),
        "Array Positions": len(print_array.flatten()),
        "Filled Positions": sum(count_values).item(),
        "Blank Positions": (
            len(print_array.flatten()) - sum(count_values)
        ).item(),
        "Fill Rate": (sum(count_values) / len(print_array.flatten())).item(),
        "Mean Replicates": np.mean(count_values).item(),
    }

    counter = Counter(print_counts.values())
    for k in sorted(counter.keys()):
        metrics[f"{k.item()} Replicates"] = counter[k]
    return metrics


def print_metrics_summary(metrics: dict[str, Any]) -> None:
    """Print formatted metrics summary.

    Args:
        metrics: Dictionary from get_print_metrics()
    """
    print(
        pd.Series(metrics, dtype="object").to_string(
            float_format=lambda x: f"{x:.2f}"
        )
    )


def plot_mutant_position(
    print_array: npt.NDArray[Any],
    print_spec: pd.DataFrame,
    variant: str,
    n_blocks: int = 1,
    figsize: tuple[float, float] = (4, 4),
) -> matplotlib.figure.Figure:
    """Visualize the position of a single mutant in the array.

    Args:
        print_array: Array containing mutant positions
        print_spec: DataFrame containing print data
        variant: The variant to highlight
        n_blocks: Number of blocks to divide array into

    Returns:
        fig, ax: Figure and axis objects
    """
    # Get plate-well information for variant
    row = print_spec[variant == print_spec["Name"]]
    if len(row) != 1:
        raise RuntimeError(f"{variant} does not appear exactly once")
    plate_well = f"{row['Plate'].item()}{row['Well'].item()}"

    # Create blocked suplots
    fig, axs = plt.subplots(ncols=n_blocks, figsize=figsize)
    if n_blocks == 1:
        axs = [axs]

    for i in range(n_blocks):
        block = get_block(print_array, i, n_blocks)
        axs[i].imshow(block == plate_well, cmap="binary")
        if n_blocks > 1:
            axs[i].set_title(f"Block {i}")

    fig.suptitle(f"{variant} in Print")
    return fig


def plot_array_heatmap(
    print_array: npt.NDArray[Any], figsize: tuple[float, float] = (10, 6)
) -> matplotlib.figure.Figure:
    """Plot a heatmap visualization of the print array.

    Args:
        print_array: Array containing mutant positions
        color: Whether to use a different color for each variant
        figsize: Figure size tuple

    Returns:
        fig, ax: Figure and axis objects
    """
    # Float representation of print array
    int_print_array = print_array.copy()
    for i, val in enumerate(np.unique(int_print_array)):
        if val == "":
            int_print_array[int_print_array == val] = None
        else:
            int_print_array[int_print_array == val] = i
    int_print_array = int_print_array.astype(float)

    cmap = matplotlib.colormaps["rainbow"].copy()
    cmap.set_bad(color="black")

    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(int_print_array, cmap=cmap)

    return fig
