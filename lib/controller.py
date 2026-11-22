# ==============================================================================
# This code is from the NXBT project (https://github.com/Brikwerk/nxbt).
#
# Copyright (c) 2019 Reece Walsh
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ==============================================================================

from enum import Enum, StrEnum


class ControllerTypes(Enum):
    """Controller type enumerations for initializing the controller server."""

    JOYCON_L = 1
    JOYCON_R = 2
    PRO_CONTROLLER = 3


class ControllerVariant(StrEnum):
    PRO = "pro"
    LEFT = "joycon_l"
    RIGHT = "joycon_r"
    COMBINED = "combined"

    @property
    def is_single_joycon(self) -> bool:
        return self in (self.LEFT, self.RIGHT)

    @property
    def bluetooth_type(self) -> ControllerTypes:
        return {
            self.LEFT: ControllerTypes.JOYCON_L,
            self.RIGHT: ControllerTypes.JOYCON_R,
            self.PRO: ControllerTypes.PRO_CONTROLLER,
        }[self]

    @property
    def bluetooth_name(self) -> str:
        return {
            self.LEFT: "Joy-Con (L)",
            self.RIGHT: "Joy-Con (R)",
            self.PRO: "Pro Controller",
        }[self]
