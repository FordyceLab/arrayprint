# pylint: disable=missing-function-docstring, missing-module-docstring

import filecmp
import glob
import itertools
import pathlib
import tempfile
from string import ascii_uppercase
from typing import Final

import pandas as pd

import arrayprint


def test() -> None:
    # Create print plate
    print_plate = pd.DataFrame(
        columns=range(1, 25), index=list(ascii_uppercase[:16])
    )

    for oligo, column in itertools.chain(
        zip(range(23, 34), range(1, 23, 2), strict=True),
        zip(range(34, 45), range(2, 24, 2), strict=True),
    ):
        for dilution, rowname in enumerate(ascii_uppercase[0:16:2], start=1):
            print_plate.loc[rowname, column] = f"{oligo}-{dilution}"

    # Configure blocks
    l = []
    for col, series in print_plate.items():
        for row, val in series.items():
            if not pd.isna(val):
                l.append(
                    {
                        "Plate": 1,
                        "Well": f"{row}{col}",
                        "Name": val,
                        "Block": (1,),
                    }
                )

    print_spec = pd.DataFrame(l)

    # Project Configuration
    project = "MyProject"
    rows = 56
    columns = 32
    skip_rows = True
    n_blocks = 1
    device: Final = "PS1.8K"

    # Generate print array
    print_array = arrayprint.generate_print_array(
        print_spec=print_spec,
        rows=rows,
        columns=columns,
        skip_rows=skip_rows,
        n_blocks=n_blocks,
        notch_column=28,
        notch_depth=20,
        seed=0,
    )

    with tempfile.TemporaryDirectory() as tmpdirname:
        # Save `.fld` file body in `.txt` output
        basename = pathlib.PurePath(tmpdirname, project)
        arrayprint.write_fld(str(basename), print_array, device=device)

        # Compare with reference
        filename = glob.glob(f"{basename}*.fld")[0]
        refname = pathlib.Path(__file__).parent.joinpath("MyProject.fld")
        assert filecmp.cmp(filename, refname, shallow=False)
