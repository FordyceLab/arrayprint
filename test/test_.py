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

    # Project Configuration
    project = "MyProject"
    rows = 56
    columns = 32
    skip_rows = True
    device: Final = "PS1.8K"

    # Generate print array
    print_array = arrayprint.generate_print_array(
        print_plates=[print_plate],
        rows=rows,
        columns=columns,
        skip_rows=skip_rows,
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
        # tail -n 1 MyProject.fld |  head -c 1 | xxd - should return a7 (§)
        # head -n 21 MyProject.fld | tail -n 1 | head -c 9 | tail -c 1 | xxd -
        #     should return b5 (µ)
