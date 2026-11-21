from bumble.core import (
    BT_HIDP_PROTOCOL_ID,
    BT_HUMAN_INTERFACE_DEVICE_SERVICE,
    BT_L2CAP_PROTOCOL_ID,
)
from bumble.sdp import (
    SDP_ADDITIONAL_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
    SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID,
    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_PUBLIC_BROWSE_ROOT,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    DataElement,
    ServiceAttribute,
)

from lib.controller import ControllerVariant

SDP_HID_SERVICE_NAME_ATTRIBUTE_ID = 0x0100
SDP_HID_SERVICE_DESCRIPTION_ATTRIBUTE_ID = 0x0101
SDP_HID_PROVIDER_NAME_ATTRIBUTE_ID = 0x0102
SDP_HID_DEVICE_RELEASE_NUMBER_ATTRIBUTE_ID = 0x0200
SDP_HID_PARSER_VERSION_ATTRIBUTE_ID = 0x0201
SDP_HID_DEVICE_SUBCLASS_ATTRIBUTE_ID = 0x0202
SDP_HID_COUNTRY_CODE_ATTRIBUTE_ID = 0x0203
SDP_HID_VIRTUAL_CABLE_ATTRIBUTE_ID = 0x0204
SDP_HID_RECONNECT_INITIATE_ATTRIBUTE_ID = 0x0205
SDP_HID_DESCRIPTOR_LIST_ATTRIBUTE_ID = 0x0206
SDP_HID_LANGID_BASE_LIST_ATTRIBUTE_ID = 0x0207
SDP_HID_SDP_DISABLE_ATTRIBUTE_ID = 0x0208
SDP_HID_BATTERY_POWER_ATTRIBUTE_ID = 0x0209
SDP_HID_REMOTE_WAKE_ATTRIBUTE_ID = 0x020A
SDP_HID_PROFILE_VERSION_ATTRIBUTE_ID = 0x020B
SDP_HID_SUPERVISION_TIMEOUT_ATTRIBUTE_ID = 0x020C
SDP_HID_NORMALLY_CONNECTABLE_ATTRIBUTE_ID = 0x020D
SDP_HID_BOOT_DEVICE_ATTRIBUTE_ID = 0x020E

LANGUAGE = 0x656E
ENCODING = 0x6A
PRIMARY_LANGUAGE_BASE_ID = 0x100
# HID_COUNTRY_CODE = 0x21
HID_COUNTRY_CODE = 0x00
HID_VIRTUAL_CABLE = True
HID_RECONNECT_INITIATE = True
HID_BATTERY_POWER = True
HID_REMOTE_WAKE = True
HID_SUPERVISION_TIMEOUT = 0xC80
HID_NORMALLY_CONNECTABLE = False
HID_BOOT_DEVICE = False
DEVICE_CLASS_GAMEPAD = 0x002508


# fmt: off
# Disable lint for commenting purposes
HID_REPORT_MAP = bytes(  # Text String, 50 Octet Report Descriptor
    [
        0x05, 0x01,  # Usage Page (Generic Desktop)
        0x09, 0x05,  # Usage (Game Pad)
        0xA1, 0x01,  # Collection (Application)

            0x06, 0x01, 0xFF,  # Usage Page (Vendor Defined 0xFF01)

            0x85, 0x21,  # Report ID (33)
            0x09, 0x21,  # Usage (0x21)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x85, 0x30,  # Report ID (48)
            0x09, 0x30,  # Usage (0x30)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x85, 0x31,  # Report ID (49)
            0x09, 0x31,  # Usage (0x30)
            0x75, 0x08,  # Report Size (8)
            0x96, 0x69,
            0x01, 0x81,

            0x02, 0x30,  # Report ID (50)
            0x09, 0x30,  # Usage (0x32)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (102)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x85, 0x33,  # Report ID (51)
            0x09, 0x33,  # Usage (0x33)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x66,  # Report Count (102)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x85, 0x3F,  # Report ID (63)
            0x05, 0x09,  # Usage Page (Button)
            0x19, 0x01,  # Usage Minimum (Button 1)
            0x29, 0x10,  # Usage Maximum (Button 16)
            0x15, 0x00,  # Logical Minimum (0)
            0x25, 0x01,  # Logical Maximum (1)
            0x75, 0x01,  # Report Size (1)
            0x95, 0x10,  # Report Count (16)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x05, 0x01,  # Usage Page (Generic Desktop)
            0x09, 0x39,  # Usage (Hat switch)
            0x15, 0x00,  # Logical Minimum (0)
            0x25, 0x07,  # Logical Maximum (7)
            0x75, 0x04,  # Report Size (4)
            0x95, 0x01,  # Report Count (1)
            0x81, 0x42,  # Input (Data,Var,Abs,Null State)
            0x05, 0x09,  # Usage Page (Button)
            0x75, 0x04,  # Report Size (4)
            0x95, 0x01,  # Report Count (1)
            0x81, 0x01,  # Input (Constant)

            0x05, 0x01,  # Usage Page (Generic Desktop)
            0x09, 0x30,  # Usage (X)
            0x09, 0x31,  # Usage (Y)
            0x09, 0x33,  # Usage (Rx)
            0x09, 0x34,  # Usage (Ry)
            0x16, 0x00, 0x00,  # Logical Minimum (0)
            0x26, 0xFF, 0xFF,  # Logical Maximum (65535)
            0x75, 0x10,  # Report Size (16)
            0x95, 0x04,  # Report Count (4)
            0x81, 0x02,  # Input (Data, Var, Abs)

            0x06, 0x01, 0xFF,  # Usage Page (Vendor Defined 0xFF01)
            0x85, 0x01,  # Report ID (1)
            0x09, 0x01,  # Usage (0x01)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x91, 0x02,  # Output (Data, Var, Abs)

            0x85, 0x10,  # Report ID (16)
            0x09, 0x10,  # Usage (0x10)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x91, 0x02,  # Output (Data, Var, Abs)

            0x85, 0x11,  # Report ID (17)
            0x09, 0x11,  # Usage (0x11)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x91, 0x02,  # Output (Data, Var, Abs)

            0x85, 0x12,  # Report ID (18)
            0x09, 0x12,  # Usage (0x12)
            0x75, 0x08,  # Report Size (8)
            0x95, 0x30,  # Report Count (48)
            0x91, 0x02,  # Output (Data, Var, Abs)

        0xC0  # End Collection
    ])
    # fmt: on


def sdp_record(variant=ControllerVariant.PRO):
    service_record_handle = 0x00010002
    return {
        service_record_handle: [
            ServiceAttribute(
                SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,  # 0x0001
                DataElement.sequence(
                    [DataElement.uuid(BT_HUMAN_INTERFACE_DEVICE_SERVICE)]  # 0x1124
                ),
            ),
            ServiceAttribute(
                SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,  # 0x0004
                DataElement.sequence(
                    [
                        DataElement.sequence(
                            [
                                DataElement.uuid(BT_L2CAP_PROTOCOL_ID),  # 0x0100
                                DataElement.unsigned_integer_16(0x0011),  # 0x0011
                            ]
                        ),
                        DataElement.sequence(
                            [
                                DataElement.uuid(BT_HIDP_PROTOCOL_ID),  # 0x0011
                            ]
                        ),
                    ]
                ),
            ),
            ServiceAttribute(
                SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,  # 0x0005
                DataElement.sequence(
                    [DataElement.uuid(SDP_PUBLIC_BROWSE_ROOT)]
                ),  # 0x1002
            ),
            ServiceAttribute(
                SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID,  # 0x0006
                DataElement.sequence(
                    [
                        DataElement.unsigned_integer_16(LANGUAGE),  # 0x656E
                        DataElement.unsigned_integer_16(ENCODING),  # 0x006a
                        DataElement.unsigned_integer_16(
                            PRIMARY_LANGUAGE_BASE_ID
                        ),  # 0x0100
                    ]
                ),
            ),
            ServiceAttribute(
                SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,  # 0x0009
                DataElement.sequence(
                    [
                        DataElement.sequence(
                            [
                                DataElement.uuid(
                                    BT_HUMAN_INTERFACE_DEVICE_SERVICE
                                ),  # 0x1124
                                DataElement.unsigned_integer_16(0x0101),  # 0x0101
                            ]
                        )
                    ]
                ),
            ),
            ServiceAttribute(
                SDP_ADDITIONAL_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,  # 0x000D
                DataElement.sequence(
                    [
                        DataElement.sequence(
                            [
                                DataElement.uuid(BT_L2CAP_PROTOCOL_ID),  # 0x0100
                                DataElement.unsigned_integer_16(0x0013),  # 0x0013
                            ]
                        ),
                        DataElement.sequence(
                            [
                                DataElement.uuid(BT_HIDP_PROTOCOL_ID),  # 0x0011
                            ]
                        ),
                    ]
                ),
            ),
            # ------------- HID SDP Atrribute Values See HID v1.1.1 "5.3 Service Discovery Protocol (SDP)" --------------
            ServiceAttribute(
                SDP_HID_SERVICE_NAME_ATTRIBUTE_ID,  # 0x0100
                DataElement(
                    DataElement.TEXT_STRING,
                    b"Wireless Gamepad" if variant == ControllerVariant.PRO
                    else variant.bluetooth_name.encode("ascii"),
                ),
            ),
            ServiceAttribute(
                SDP_HID_SERVICE_DESCRIPTION_ATTRIBUTE_ID,  # 0x0101
                DataElement(DataElement.TEXT_STRING, b"Gamepad"),
            ),
            ServiceAttribute(
                SDP_HID_PROVIDER_NAME_ATTRIBUTE_ID,  # 0x0102
                DataElement(DataElement.TEXT_STRING, b"Nintendo"),
            ),
            ServiceAttribute(
                SDP_HID_PARSER_VERSION_ATTRIBUTE_ID,  # 0x0201
                DataElement.unsigned_integer_16(0x0111),
            ),
            ServiceAttribute(
                SDP_HID_DEVICE_SUBCLASS_ATTRIBUTE_ID,  # 0x0202
                DataElement.unsigned_integer_8(0x08),
            ),
            ServiceAttribute(
                SDP_HID_COUNTRY_CODE_ATTRIBUTE_ID,  # 0x0203
                DataElement.unsigned_integer_8(HID_COUNTRY_CODE),
            ),
            ServiceAttribute(
                SDP_HID_VIRTUAL_CABLE_ATTRIBUTE_ID,  # 0x0204
                DataElement(DataElement.BOOLEAN, HID_VIRTUAL_CABLE),
            ),
            ServiceAttribute(
                SDP_HID_RECONNECT_INITIATE_ATTRIBUTE_ID,  # 0x0205
                DataElement(DataElement.BOOLEAN, HID_VIRTUAL_CABLE),
            ),
            ServiceAttribute(
                SDP_HID_DESCRIPTOR_LIST_ATTRIBUTE_ID,  # 0x0206
                DataElement.sequence(
                    [
                        DataElement.sequence(
                            [
                                DataElement.unsigned_integer_8(
                                    0x22
                                ),  # Report Descriptor Type
                                DataElement(
                                    DataElement.TEXT_STRING,
                                    bytes.fromhex(
                                        "05010905a1010601ff8521092175089530810285300930750895308102853109317508966901810285320932750896690181028533093375089669018102853f05091901291015002501750195108102050109391500250775049501814205097504950181010501093009310933093416000027ffff00007510950481020601ff85010901750895309102851009107508953091028511091175089530910285120912750895309102c0"
                                    ),
                                ),
                            ]
                        ),
                    ]
                ),
            ),
            ServiceAttribute(
                SDP_HID_LANGID_BASE_LIST_ATTRIBUTE_ID,  # 0x0207
                DataElement.sequence(
                    [
                        DataElement.sequence(
                            [
                                DataElement.unsigned_integer_16(
                                    0x0409
                                ),  # English (United States)
                                DataElement.unsigned_integer_16(0x0100),
                            ]
                        ),
                    ]
                ),
            ),
            ServiceAttribute(
                SDP_HID_BATTERY_POWER_ATTRIBUTE_ID,  # 0x0209
                DataElement(DataElement.BOOLEAN, HID_BATTERY_POWER),
            ),
            ServiceAttribute(
                SDP_HID_REMOTE_WAKE_ATTRIBUTE_ID,  # 0x020A
                DataElement(DataElement.BOOLEAN, HID_REMOTE_WAKE),
            ),
            ServiceAttribute(
                SDP_HID_SUPERVISION_TIMEOUT_ATTRIBUTE_ID,  # 0x020C
                DataElement.unsigned_integer_16(HID_SUPERVISION_TIMEOUT),
            ),
            ServiceAttribute(
                SDP_HID_NORMALLY_CONNECTABLE_ATTRIBUTE_ID,  # 0x020D
                DataElement(DataElement.BOOLEAN, HID_NORMALLY_CONNECTABLE),
            ),
            ServiceAttribute(
                SDP_HID_BOOT_DEVICE_ATTRIBUTE_ID,  # 0x020E
                DataElement(DataElement.BOOLEAN, HID_BOOT_DEVICE),
            ),
        ]
    }
