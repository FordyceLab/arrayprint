"""Programmatic spotting using Scienion S3 liquid-handling robots."""

# TODO: add support for two-lagoon devices

import warnings
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from io import StringIO
from typing import Any, Literal, get_args

import matplotlib.figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy import typing as npt

from .field_files import FOOTER, HEADERS

__version__ = "0.1.0"
DeviceTypes = Literal["PS1.8K", "2lagoon"]
assert tuple(HEADERS.keys()) == get_args(DeviceTypes)

WASH = "WASH"
BUF = "BUF"


def get_block(
    print_array: npt.NDArray[Any], block: int, n_blocks: int
) -> npt.NDArray[Any]:
    """A view of the print array belonging to the given (0-indexed) block."""
    columns = print_array.shape[1]
    width = int(columns // n_blocks)
    return print_array[:, width * block : width * (block + 1)]


def fill_array(
    wells: list[str], array: npt.NDArray[Any], seed: int | None = None
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
    fill_values = np.concatenate(arrays, axis=0)
    assert len(fill_values) == to_fill
    rng.shuffle(fill_values)

    # Fill array
    array[
        np.nonzero(array == None)  # pylint: disable=singleton-comparison
    ] = fill_values


def generate_print_array(
    print_plates: Iterable[pd.DataFrame],
    rows: int = 56,
    columns: int = 32,
    skip_rows: bool = True,
    block_info: Iterable[Iterable[str]] | None = None,
    empty_buf_well: str = "",
    wash_array_loc: tuple[int, int] | None = None,
    seed: int | None = None,
) -> npt.NDArray[Any]:
    """Generate optimized print array from a print_plate dataframe.

    Args:
        print_plate: DataFrame containing print data
        rows: Number of rows in device
        columns: Number of columns in device
        skip_rows: Whether to add blank rows
        seed: Seed for random generation

    Returns:
        Numpy array of strings containing print layout
    """
    # Create print array
    print_array = np.full((rows, columns), fill_value=None, dtype="object")
    if skip_rows:
        print_array[1::2] = empty_buf_well

    # Create block_info if not specified
    if block_info is None:
        block_info = [
            np.concatenate(
                [plate.to_numpy().flatten() for plate in print_plates]
            )
        ]
    block_info = [[j for j in i if j not in (WASH, BUF)] for i in block_info]

    # Fill in wash wells
    wash_wells: list[str] = [] if empty_buf_well == "" else [empty_buf_well]
    for plate_idx, plate in enumerate(print_plates, start=1):
        row, col = np.nonzero(plate.to_numpy() == WASH)
        for i, j in zip(row, col):
            wash_wells.append(f"{plate_idx}{plate.index[i]}{plate.columns[j]}")
    if len(wash_wells) > 0:
        if wash_array_loc is None:
            warnings.warn(
                f"Found {len(wash_wells)} wash wells in the print plate"
                " but no location was provided to spot them on the array;"
                " you can do so using the `wash_array_loc` argument"
            )
        else:
            print_array[tuple(i - 1 for i in wash_array_loc)] = ",".join(
                wash_wells
            )

    # Fill in each block in-place using slicing to produce a view
    for i, block in enumerate(block_info):
        wells: list[str] = []
        for val in block:
            for plate_idx, plate in enumerate(print_plates, start=1):
                row, col = np.nonzero(plate.to_numpy() == val)
                for r, c in zip(row, col):
                    wells.append(
                        f"{plate_idx}{plate.index[r]}{plate.columns[c]}"
                    )
        fill_array(wells, get_block(print_array, i, len(block_info)), seed)

    return print_array


def get_fld(
    print_array: npt.NDArray[Any], device: DeviceTypes | None = None
) -> str:
    """Get FLD file as a string.

    Args:
        print_array: Array containing mutant positions
        device: Device type used for writing the header and footer
    """
    # print_array = np.flip(print_array, axis=1)  # Scienion flips orientation
    rows, columns = print_array.shape

    if device is not None:
        header = HEADERS[device]
        out = [header]
    else:
        out = []

    for i in range(0, columns):
        for j in range(0, rows):
            array_loc = f"{i + 1}/{j+1}"
            wells = print_array[j, i]

            if len(wells) >= 1:
                num_spots = len(wells.split(","))
                out.append(f"{array_loc}\t{wells},\t{'1,'*num_spots}")
            else:
                out.append(f"{array_loc}\t\t")

    if device is not None:
        out.append(FOOTER)

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
    filename = f"{basename}_{timestamp}.fld"
    with open(filename, "wt", encoding="cp1252") as f:
        f.write(get_fld(print_array, device=device))

    # Double check that the file was written correctly
    with open(filename, "rb") as f:
        data = f.read()

    crlf_ending = bytearray([0x0D, 0x0A])

    # tail -c 2 *.fld  | xxd -
    assert data[-2:] == crlf_ending

    # head -n 21 *.fld | tail -n 1 | head -c 9 | tail -c 1 | xxd -
    assert data.split(crlf_ending)[20][8] == 0xB5  # µ

    # tail -n 1 *.fld  | head -c 1 | xxd
    assert data.split(crlf_ending)[-2][0] == 0xA7  # §


def load_fld(path: str) -> pd.DataFrame:
    """Load a field file into a dataframe."""
    # TODO: convert to print_array
    with open(path, "rt", encoding="cp1252") as f:
        fld_contents = f.read()
    fields = [
        pd.read_table(
            StringIO(i.split("\n\n")[0]),
            sep="\t",
            header=None,
            names=["array_loc", "well", "spots"],
        )
        for i in fld_contents.split("]\n")[1:]
    ]
    for i in fields:
        i["well"] = i["well"].apply(lambda x: x[:-1] if len(x) > 2 else x[0])
        i["spots"] = i["spots"].apply(lambda x: x[:-1] if len(x) > 2 else x[0])

    return pd.concat(fields, keys=range(len(fields)), axis=0)


def get_pinlist(fld: pd.DataFrame, print_plate: pd.DataFrame) -> pd.DataFrame:
    """Outputs the pinlist expected by ProcessingPack."""
    pinlist = pd.DataFrame(
        {
            "Indices": [
                (int(i), int(j))
                for i, j in fld.loc[0]["array_loc"].str.split("/")
            ],
            "MutantID": [
                (
                    "BLANK"
                    if i.startswith("1P24")
                    else print_plate.loc[i[1], int(i[2:])]
                )
                for i in fld.loc[0]["well"]
            ],
        }
    )
    pinlist["x"] = pinlist["Indices"].apply(lambda x: x[0])
    pinlist["y"] = pinlist["Indices"].apply(lambda x: x[1])
    return pinlist.set_index(["x", "y"], drop=True).sort_index()


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
    plate_well: str,
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
    # Create blocked suplots
    fig, axs = plt.subplots(ncols=n_blocks, figsize=figsize)
    if n_blocks == 1:
        axs = [axs]

    for i in range(n_blocks):
        block = get_block(print_array, i, n_blocks)
        axs[i].imshow(block == plate_well, cmap="binary")
        if n_blocks > 1:
            axs[i].set_title(f"Block {i}")

    fig.suptitle(f"{plate_well} in Print")
    return fig


def plot_array_heatmap(
    print_array: npt.NDArray[Any],
    empty_buf_well: str = "",
    figsize: tuple[float, float] = (10, 6),
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
    unique_vals = np.unique(int_print_array)
    for i, val in enumerate(unique_vals):
        if val == "":
            # Empty wells are white
            fill_value = 2 * len(unique_vals)
        elif empty_buf_well != "" and val == empty_buf_well:
            # Wells with 1X buffer are black
            fill_value = None
        else:
            fill_value = i

        int_print_array[int_print_array == val] = fill_value

    int_print_array = int_print_array.astype(float)

    cmap = matplotlib.colormaps["rainbow"].copy()
    cmap.set_extremes(bad="black", under="white", over="white")

    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(int_print_array, cmap=cmap, vmin=0, vmax=len(unique_vals))

    return fig
