# SPDX-FileCopyrightText: © 2016 Rob Webset
# SPDX-FileCopyrightText: © 2019 Robert Hudson
# SPDX-FileCopyrightText: © 2020-2021 Peter J. Mello <admin@petermello.net>
# SPDX-License-Identifier: MPL-2.0
"""Manual AddonSync entry point."""
import os
import sys

LIB = os.path.join(os.path.dirname(__file__), "resources", "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from addonsync import run_manual  # noqa: E402


if __name__ == "__main__":
    run_manual()
