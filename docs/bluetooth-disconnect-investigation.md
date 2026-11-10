# Bluetooth disconnect investigation, 10 November 2026

The HID-close notification describes a symptom. It does not identify whether the
Switch closed L2CAP, the ACL disconnected, or an old callback stopped a new session.
Both reported symptoms remain subject to hardware reproduction after these changes.

## Evidence from the available Switch

- The existing application log records three failures at 03:18:43, 03:18:49 and
  03:18:52. Both HID channels open, the application sends one initial report, and
  both channels close about 135–139 ms later. Restarting is followed by a successful
  session at 03:19:06. No HCI reason was recorded by that version.
- A new debug run returned PAGE_TIMEOUT on the Home screen. After opening
  Controllers > Change Grip/Order, outgoing connections reached the ACL layer.
- At 04:02:28 and 04:03:37, the adapter reported ROLE_SWITCH_FAILED_ERROR before
  connection completion. The app remained CENTRAL. The Switch terminated the ACL
  with reason 0x13 about 150 ms after connection completion, during authentication.
  This happened before HID channels opened, so it is not an exact reproduction of
  the original notification.
- Incoming pairing at 04:03:09 made the app PERIPHERAL, completed secure pairing
  and encryption, opened both HID channels, and completed the controller handshake
  at 04:03:12. This succeeded without restarting after the failed outgoing attempt.
- A process-only experiment skipped locally initiated authentication/encryption.
  Role switching still failed and the Switch disconnected during L2CAP creation.
  This rules out the local authentication request as the sole trigger in that run.
- A second process-only experiment explicitly requested PERIPHERAL after the
  initial failed role switch. The Switch disconnected before that request completed.
  Neither experiment is part of the application changes.

The role-switch failure is a concrete lead at the controller/link layer, not proof
of why the earlier HID-open sessions failed. The trace does not establish whether
the adapter firmware, Switch timing, or link policy causes the failed role switch.
It also does not prove a stale bond: fresh incoming pairing succeeded, but the next
outgoing attempt still failed role switching.

## Confirmed application defects and changes

- HID callbacks previously modified shared session events regardless of which
  channel emitted them. A regression test reproduces an old channel stopping a
  replacement session. Open/close callbacks and interrupt input now check channel
  identity before modifying the session.
- UI cleanup, reconnect failure cleanup, and the session loop could issue separate
  HCI disconnect commands for the same connection. They now share a disconnect
  lock and recheck connection identity. Disconnect completion has a 10 second bound.
- Cleanup exceptions could escape the outer session loop. Session cleanup now logs
  failures and keeps the loop running. This does not reset a controller that fails
  to finish disconnecting; its connection reference remains until the ACL ends.
- Bumble uses CancelledError for a link lost during authentication or channel
  setup. This bypassed the API's Exception handler and produced an HTTP 500 response
  in the live trace. Reconnect now translates it to ConnectionError when the caller
  has not requested cancellation. Actual task cancellation still propagates.
- Normal logs now include ACL connection/disconnection events and the HCI reason,
  allowing the next fast HID-close event to be distinguished from a local cleanup.

## Remaining verification

Validation of the patched application reproduced an outgoing role-switch failure
at 04:07:17. The API returned a handled 503 and continued serving status requests.
Incoming pairing then succeeded in the same process; the UI showed Connected and
the capture preview showed the controller in player slot 1. The app was left in
that state with video active.

The final test run had 225 passing tests and four failures in the unchanged Linux
packaging checksum tests, which expect LF but receive CRLF on Windows. The targeted
Bluetooth/API run passed all 55 tests. Formatting checks pass; lint retains an
existing broad-exception warning at app/main.py's report-send handler.

Capture an exact HID-open/fast-close failure with the new ACL reason logging.
Compare its role-change events with a successful outgoing reconnect on the same
adapter. Reproduce the first-pair/re-pair restart-only symptom while preserving the
trace through several retries. The lifecycle fixes address demonstrated code
defects; they do not establish that either reported hardware symptom is eliminated.

Full local HCI traces and process-only experiment scripts are under `.git/` and
are excluded from source changes. Raw HCI traces contain bond keys and should not
be published without redaction.
